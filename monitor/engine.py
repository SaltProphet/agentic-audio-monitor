"""Wires capture, voice activity, transcription, and the log. No substitute audio source."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from . import devices
from .captions import CCController
from .config import Config, save_config
from .signal import Segmenter, dbfs, peak, resample, rms
from .store import Store
from .transcribe import plan_load, probe_cuda, run_model

log = logging.getLogger("audiomonitor")


class Engine:
    def __init__(self, cfg: Config, config_path: Path, cc_controller: CCController | None = None):
        self.cfg = cfg
        self.config_path = config_path
        self.data_dir = config_path.parent
        self.models_dir = self.data_dir / "models"
        self.store = Store(self.data_dir)
        self.segmenter = Segmenter(16000, cfg.sensitivity)
        self.segmenter.set_max_duration(4.0 if cfg.task == "translate" else 20.0)
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.capture = None
        self.captures = []
        self.capturing = False
        self.capture_mode = "none"
        self.capture_endpoint = ""
        self.capture_hostapi = ""
        self.capture_channels = 0
        self.capture_error = ""
        self.capture_status = ""
        self.overflows = 0
        self.input_rate = 0
        self.rms = 0.0
        self.peak = 0.0
        self.model = None
        self.model_state = "not_loaded"
        self.model_error = ""
        self.model_note = "Speech model is not loaded."
        self.model_gen = 0
        self.queue: list = []
        self.partial_job = None
        self.partial_mark = 0
        self.partial_interval = int(2.0 * 16000)
        self.partial_window = 4.0
        self.untranscribed = 0
        self.dropped = 0
        self.last_transcript = ""
        self.last_transcript_id = 0
        self.last_confidence = None
        self.last_note = ""
        self.recent = self.store.tail(40)
        self._worker: threading.Thread | None = None
        self._pruner: threading.Thread | None = None
        self._loader: threading.Thread | None = None
        self.cc = cc_controller or CCController(config_path.parent)

    def start(self) -> None:
        ignored = [flag for flag in self.cfg.ignored_flags() if flag != "loopback"]
        if ignored:
            log.warning("Ignoring flags that this build does not implement: %s", ", ".join(ignored))
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.store.prune(self.cfg.retention_days)
        self._worker = threading.Thread(target=self._transcribe_loop, name="transcribe", daemon=True)
        self._worker.start()
        self._pruner = threading.Thread(target=self._prune_loop, name="prune", daemon=True)
        self._pruner.start()
        self._refresh_model_note()
        error = self._start_sources(self.cfg.source_mode)
        if error:
            self.capture_error = error
            log.error("Capture did not start: requested=%s error=%s", self.cfg.source_mode, error)
        self._maybe_autoload()
        self.cc.start_if_enabled()

    def stop(self) -> None:
        self.stop_event.set()
        self._stop_capture()
        with self.cv:
            self.cv.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=2)
        if self._pruner is not None:
            self._pruner.join(timeout=1)
        self.cc.stop()

    def update_cc(self, patch: dict) -> tuple[bool, str]:
        return self.cc.apply(patch)

    def list_devices(self) -> dict:
        try:
            rows = devices.list_inputs()
        except Exception as exc:
            return {"error": str(exc), "devices": []}
        return {"error": None, "devices": rows}

    def select_device(self, index: int | None, name: str, hostapi: str) -> tuple[bool, str]:
        try:
            rows = devices.list_inputs()
        except Exception as exc:
            self.capture_error = str(exc)
            return False, str(exc)
        match = devices.resolve(rows, index=index, name=name, hostapi=hostapi)
        if match is None:
            return False, "That device is not in the current input list. Refresh and pick it again."
        self.cfg.device_index = match["index"]
        self.cfg.device_name = match["name"]
        self.cfg.device_hostapi = match["hostapi"]
        if self.cfg.source_mode == "system":
            self.cfg.source_mode = "external"
        save_config(self.config_path, self.cfg)
        error = self._start_sources(self.cfg.source_mode, match=match)
        if error:
            return False, error
        self._maybe_autoload()
        return True, "listening"

    def update_settings(self, patch: dict) -> tuple[bool, str]:
        if not isinstance(patch, dict):
            return False, "Settings must be an object."
        refused = set(patch) & {"flags", "echo", "idle_speech", "host", "port"}
        if refused:
            return False, "That setting is file-only, or it is not implemented in this build."
        allowed = {
            "sensitivity",
            "save_clips",
            "retention_days",
            "model",
            "model_path",
            "language",
            "task",
            "loopback",
            "source_mode",
            "compute_device",
            "compute_type",
            "allow_cpu",
            "offline",
        }
        unknown = set(patch) - allowed
        if unknown:
            return False, "Unknown setting: " + ", ".join(sorted(unknown))
        nxt = Config(**{**self.cfg.__dict__})
        nxt.flags = dict(self.cfg.flags)
        for key, value in patch.items():
            if key == "retention_days":
                value = int(value)
            if key == "sensitivity":
                value = float(value)
            if key == "loopback":
                nxt.source_mode = "system" if bool(value) else "external"
            elif key == "source_mode":
                nxt.source_mode = value
            else:
                setattr(nxt, key, value)
        try:
            nxt.validate()
        except (TypeError, ValueError) as exc:
            return False, str(exc)
        model_keys = {"model", "model_path", "compute_device", "compute_type", "allow_cpu", "offline"}
        reload_needed = any(getattr(nxt, key) != getattr(self.cfg, key) for key in model_keys)
        source_changed = nxt.source_mode != self.cfg.source_mode
        with self.lock:
            self.cfg = nxt
            self.segmenter.set_sensitivity(nxt.sensitivity)
            self.segmenter.set_max_duration(4.0 if nxt.task == "translate" else 20.0)
            if reload_needed:
                self.model = None
                self.model_gen += 1
                self.model_state = "not_loaded"
                self.queue.clear()
                self.cv.notify_all()
        save_config(self.config_path, self.cfg)
        if source_changed:
            error = self._start_sources(self.cfg.source_mode)
            if error:
                self.capture_error = error
                return False, error
        if reload_needed:
            self._refresh_model_note()
        return True, "saved"

    def request_load(self) -> tuple[bool, str]:
        plan = self._plan()
        if plan.action == "error":
            self.model_state = "error"
            self.model_error = plan.message
            self.model_note = plan.message
            return False, plan.message
        if self.model_state == "loading":
            return False, "The speech model is already loading."
        if self.model_state == "ready" and plan.action == "load":
            return True, "The speech model is already loaded."
        self._start_loader(plan)
        return True, plan.message

    def live(self) -> dict:
        with self.lock:
            vad = "off"
            if self.capturing:
                vad = self.segmenter.state()
            return {
                "capturing": self.capturing,
                "vad": vad,
                "rms": self.rms if self.capturing else 0.0,
                "peak": self.peak if self.capturing else 0.0,
                "db": dbfs(self.rms) if self.capturing else -90.0,
                "noise": self.segmenter.noise if self.capturing else 0.0,
                "threshold": self.segmenter.threshold() if self.capturing else 0.0,
                "overflows": self.overflows,
                "capture_error": self.capture_error,
                "capture_status": self.capture_status,
                "input_rate": self.input_rate,
                "source": self.capture_mode,
                "requested_source": self.cfg.source_mode,
            }

    def snapshot(self) -> dict:
        live = self.live()
        device = None
        if self.cfg.device_name and self.cfg.source_mode != "system":
            device = {
                "name": self.cfg.device_name,
                "hostapi": self.cfg.device_hostapi,
                "index": self.cfg.device_index,
                "input_rate": self.input_rate,
            }
        return {
            "version": "0.1.0",
            "step": 1,
            **live,
            "device": device,
            "model_state": self.model_state,
            "model_error": self.model_error,
            "model_note": self.model_note,
            "model": self.cfg.model,
            "model_path": self.cfg.model_path,
            "language": self.cfg.language,
            "task": self.cfg.task,
            "loopback": self.cfg.source_mode == "system",
            "source_mode": self.cfg.source_mode,
            "sensitivity": self.cfg.sensitivity,
            "save_clips": self.cfg.save_clips,
            "retention_days": self.cfg.retention_days,
            "offline": self.cfg.offline,
            "allow_cpu": self.cfg.allow_cpu,
            "compute_device": self.cfg.compute_device,
            "compute_type": self.cfg.compute_type,
            "last_transcript": self.last_transcript,
            "last_transcript_id": self.last_transcript_id,
            "last_confidence": self.last_confidence,
            "last_note": self.last_note,
            "ignored_flags": self.cfg.ignored_flags(),
            "recent_events": list(self.recent),
            "untranscribed": self.untranscribed,
            "dropped": self.dropped,
            "host": self.cfg.host,
            "port": self.cfg.port,
            "bind_warning": self.cfg.bind_warning(),
            "capture_endpoint": self.capture_endpoint,
            "capture_hostapi": self.capture_hostapi,
            "capture_channels": self.capture_channels,
            "cc": self.cc.snapshot(),
        }

    def on_chunk(self, chunk, rate: int) -> None:
        if self.stop_event.is_set() or not self.capturing:
            return
        raw = [float(value) for value in chunk]
        level = rms(raw)
        if level != level:  # NaN
            return
        audio = resample(raw, int(rate), 16000)
        with self.lock:
            if not self.capturing:
                return
            utterances = self.segmenter.push(audio)
            partial = None
            if self.model_state == "ready" and self.model is not None and self.segmenter.in_speech:
                if len(self.segmenter.buffer) - self.partial_mark >= self.partial_interval:
                    partial = self.segmenter.partial(self.partial_window)
                    self.partial_mark = len(self.segmenter.buffer)
            elif not self.segmenter.in_speech:
                self.partial_mark = 0
            self.rms = level
            self.peak = max(peak(raw), self.peak * 0.85)
            self.input_rate = int(rate)
        for utterance in utterances:
            self._enqueue(utterance)
        if partial is not None:
            self._enqueue_partial(partial)

    def on_status(self, status: str, overflows: int) -> None:
        with self.lock:
            self.capture_status = status
            self.overflows = overflows

    def _enqueue(self, utterance) -> None:
        with self.cv:
            self.partial_job = None
            if self.model_state == "ready" and self.model is not None:
                if len(self.queue) >= 4:
                    self.queue.pop(0)
                    self.dropped += 1
                self.queue.append(utterance)
                self.cv.notify()
            elif self.model_state == "loading":
                if len(self.queue) >= 2:
                    self.queue.pop(0)
                    self.dropped += 1
                self.queue.append(utterance)
            else:
                self.untranscribed += 1

    def _enqueue_partial(self, utterance) -> None:
        with self.cv:
            if self.model_state == "ready" and self.model is not None:
                self.partial_job = utterance
                self.cv.notify()

    def _transcribe_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.cv:
                if self.model_state != "ready" or self.model is None or (not self.queue and self.partial_job is None):
                    self.cv.wait(timeout=0.3)
                    continue
                is_partial = not self.queue
                utterance = self.partial_job if is_partial else self.queue.pop(0)
                if is_partial:
                    self.partial_job = None
                model = self.model
                language = self.cfg.language
                task = self.cfg.task
                save_clips = self.cfg.save_clips
                if self.cfg.source_mode == "system":
                    device_name = "WASAPI loopback"
                elif self.cfg.source_mode == "both":
                    device_name = f"{self.cfg.device_name} + WASAPI loopback"
                else:
                    device_name = self.cfg.device_name
            try:
                text, confidence, no_speech = run_model(model, utterance.samples, language, task)
            except Exception as exc:
                log.exception("transcription failed")
                with self.lock:
                    self.last_note = f"transcription error: {exc}"
                    self.last_transcript = ""
                    self.last_confidence = None
                continue
            if is_partial:
                self._finish_partial(text, confidence)
            else:
                self._finish(utterance, text, confidence, no_speech, save_clips, device_name)

    def _finish_partial(self, text, confidence) -> None:
        if not text:
            return
        with self.lock:
            self.last_transcript = text
            self.last_transcript_id += 1
            self.last_confidence = confidence
            self.last_note = ""

    def _finish(self, utterance, text, confidence, no_speech, save_clips, device_name) -> None:
        if not text:
            with self.lock:
                self.last_transcript = ""
                self.last_confidence = confidence
                self.last_note = "Speech was detected. Transcription returned no words."
            return
        clip = None
        if save_clips:
            clip = self.store.write_clip(utterance.samples, 16000, utterance.started_at)
        record = {
            "ts": datetime.fromtimestamp(utterance.started_at).astimezone().isoformat(timespec="seconds"),
            "transcript": text,
            "reason": None,
            "flagged": False,
            "confidence": None if confidence is None else round(confidence, 4),
            "no_speech_prob": None if no_speech is None else round(no_speech, 4),
            "duration_ms": int(round(len(utterance.samples) / 16.0)),
            "rms": round(utterance.level, 5),
            "clip": clip,
            "device": device_name,
        }
        self.store.append(record)
        with self.lock:
            self.last_transcript = text
            self.last_transcript_id += 1
            self.last_confidence = record["confidence"]
            self.last_note = ""
            self.recent.insert(0, record)
            del self.recent[40:]

    def _start_capture(self, match: dict) -> str | None:
        return self._start_sources("external", match=match)

    def _start_loopback_capture(self) -> str | None:
        return self._start_sources("system")

    def _start_sources(self, mode: str, match: dict | None = None) -> str | None:
        from .capture import Capture, LoopbackCapture

        self._stop_capture()
        self.capture_error = ""
        self.capture_status = ""
        started = []
        endpoint_names = []
        hostapis = []
        channels = 0
        rate = 0
        try:
            if mode in ("external", "both"):
                if match is None:
                    if not self.cfg.device_name:
                        raise RuntimeError("No external microphone is selected.")
                    rows = devices.list_inputs()
                    match = devices.resolve(
                        rows,
                        index=self.cfg.device_index,
                        name=self.cfg.device_name,
                        hostapi=self.cfg.device_hostapi,
                    )
                    if match is None:
                        raise RuntimeError("The saved microphone is not in the current input list. Refresh and select it again.")
                capture = Capture(match["index"], match["channels"], self.on_chunk, self.on_status)
                capture.start()
                started.append(capture)
                endpoint_names.append(match["name"])
                hostapis.append(match["hostapi"])
                channels += capture.channels
                rate = capture.rate
                log.info(
                    "Listening on external audio: endpoint=%s index=%s hostapi=%s rate=%s channels=%s",
                    match["name"], match["index"], match["hostapi"], capture.rate, capture.channels,
                )
            if mode in ("system", "both"):
                capture = LoopbackCapture(self.on_chunk, self.on_status)
                capture.start()
                started.append(capture)
                endpoint_names.append(capture.endpoint_name)
                hostapis.append("Windows WASAPI")
                channels += capture.channels
                rate = capture.rate
                log.info(
                    "Listening on system audio: output=%s endpoint=%s index=%s rate=%s channels=%s",
                    capture.output_name, capture.endpoint_name, capture.endpoint_index, capture.rate, capture.channels,
                )
        except Exception as exc:
            for capture in reversed(started):
                capture.stop()
            self.capture = None
            self.captures = []
            self.capturing = False
            self.capture_mode = "none"
            self.capture_endpoint = ""
            self.capture_hostapi = ""
            self.capture_channels = 0
            self.input_rate = 0
            self.capture_error = str(exc)
            self.rms = 0.0
            self.peak = 0.0
            log.error("Could not open requested capture mode=%s error=%s", mode, exc)
            return str(exc)
        self.captures = started
        self.capture = started[0]
        self.capturing = True
        self.capture_mode = mode
        self.capture_endpoint = " + ".join(endpoint_names)
        self.capture_hostapi = " + ".join(dict.fromkeys(hostapis))
        self.capture_channels = channels
        self.input_rate = rate
        return None

    def _stop_capture(self) -> None:
        self.capturing = False
        captures = list(self.captures)
        if not captures and self.capture is not None:
            captures = [self.capture]
        self.capture = None
        self.captures = []
        for capture in captures:
            capture.stop()
        with self.lock:
            self.rms = 0.0
            self.peak = 0.0
            self.input_rate = 0
            self.segmenter.flush()
        self.capture_mode = "none"
        self.capture_endpoint = ""
        self.capture_hostapi = ""
        self.capture_channels = 0

    def _plan(self):
        if self.cfg.compute_device == "cuda":
            count, error = probe_cuda()
        else:
            count, error = 0, None
        return plan_load(self.cfg, self.models_dir, cuda_count=count, cuda_error=error)

    def _refresh_model_note(self) -> None:
        plan = self._plan()
        self.model_note = plan.message
        if plan.action == "error":
            self.model_state = "error"
            self.model_error = plan.message
        elif self.model_state != "ready":
            self.model_state = "not_loaded"
            self.model_error = ""

    def _maybe_autoload(self) -> None:
        plan = self._plan()
        if plan.action == "load" and plan.local_files_only:
            self._start_loader(plan)
        else:
            self.model_note = plan.message
            if plan.action == "error" and self.model_state != "ready":
                self.model_state = "error"
                self.model_error = plan.message

    def _start_loader(self, plan) -> None:
        with self.cv:
            if self.model_state == "loading":
                return
            self.model_state = "loading"
            self.model_error = ""
            self.model_note = plan.message
            self.model_gen += 1
            gen = self.model_gen

        def work() -> None:
            try:
                from .transcribe import load_whisper

                model = load_whisper(plan, self.models_dir, self.cfg.offline)
            except Exception as exc:
                log.exception("model load failed")
                with self.cv:
                    if gen != self.model_gen:
                        return
                    self.model = None
                    self.model_state = "error"
                    self.model_error = str(exc)
                    self.model_note = str(exc)
                    self.cv.notify_all()
                return
            with self.cv:
                if gen != self.model_gen:
                    return
                self.model = model
                self.model_state = "ready"
                self.model_error = ""
                self.model_note = "Speech model is loaded. Transcription stays on this machine."
                self.cv.notify_all()
            log.info("Speech model ready (%s, %s)", plan.model_arg, plan.device)

        self._loader = threading.Thread(target=work, name="model-load", daemon=True)
        self._loader.start()

    def clip_file(self, name: str):
        return self.store.clip_file(name)

    def _prune_loop(self) -> None:
        while not self.stop_event.wait(3600):
            try:
                stats = self.store.prune(self.cfg.retention_days)
                with self.lock:
                    self.recent = self.store.tail(40)
                log.info("retention cleanup %s", stats)
            except Exception:
                log.exception("retention cleanup failed")
