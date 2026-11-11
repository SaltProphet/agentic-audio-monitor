"""Behavior tests. Synthetic samples exercise math only; the app has no demo audio source."""

from __future__ import annotations

import json
import math
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from monitor.config import Config, ensure_config, load_config, render_toml, save_config
from monitor.engine import Engine
from monitor.server import MonitorServer
from monitor.signal import Segmenter, dbfs, resample, rms
from monitor.store import Store
from monitor.transcribe import plan_load, weights_present

ROOT = Path(__file__).resolve().parents[1]


class FakeCaptionProcess:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0


class SignalTests(unittest.TestCase):
    def test_rms_and_silence_floor(self):
        self.assertEqual(rms([]), 0.0)
        self.assertAlmostEqual(rms([0.6, 0.8]), math.sqrt(0.5), places=5)
        self.assertEqual(dbfs(0.0), -90.0)
        self.assertAlmostEqual(dbfs(1.0), 0.0, places=5)

    def test_resample_box_and_linear(self):
        down = resample([1.0] * 480, 48000, 16000)
        self.assertEqual(len(down), 160)
        self.assertTrue(all(abs(value - 1.0) < 1e-9 for value in down))
        up = resample([0.0, 1.0], 8000, 16000)
        self.assertGreaterEqual(len(up), 3)
        self.assertEqual(up[0], 0.0)

    def test_segmenter_requires_real_energy(self):
        segmenter = Segmenter(16000, 0.55)
        self.assertEqual(segmenter.push([0.0] * 16000), [])
        self.assertEqual(segmenter.state(), "silence")
        short = segmenter.push([0.3] * 3200 + [0.0] * 16000)
        self.assertEqual(short, [])
        heard = segmenter.push([0.3] * 16000 + [0.0] * 16000)
        self.assertEqual(len(heard), 1)
        self.assertGreater(heard[0].level, 0.05)
        self.assertGreater(len(heard[0].samples), 7200)
        self.assertEqual(segmenter.state(), "silence")

    def test_segmenter_exposes_a_partial_speech_window(self):
        segmenter = Segmenter(16000, 0.55)
        segmenter.push([0.3] * 3 * 16000)

        partial = segmenter.partial(2.0)

        self.assertIsNotNone(partial)
        self.assertEqual(len(partial.samples), 2 * 16000)
        self.assertEqual(segmenter.state(), "speech")


class ConfigTests(unittest.TestCase):
    def test_task_validates_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            cfg = Config(task="translate", language="es")
            save_config(path, cfg)
            self.assertIn('task = "translate"', path.read_text(encoding="utf-8"))
            loaded = load_config(path)
            self.assertEqual(loaded.task, "translate")
            self.assertEqual(loaded.language, "es")

    def test_task_rejects_unknown_value(self):
        cfg = Config(task="summarize")
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_roundtrip_and_rejected_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            cfg = Config(device_name='Mic "A"', sensitivity=0.4)
            save_config(path, cfg)
            loaded = load_config(path)
            self.assertEqual(loaded.device_name, 'Mic "A"')
            self.assertEqual(loaded.sensitivity, 0.4)
            self.assertEqual(loaded.ignored_flags(), [])
            path.write_text(path.read_text(encoding="utf-8").replace("echo = false", "echo = true"), encoding="utf-8")
            flagged = load_config(path)
            self.assertEqual(flagged.ignored_flags(), ["echo"])
            bad = Path(tmp) / "bad.toml"
            bad.write_text(render_toml(Config()).replace("loopback = false", 'loopback = "yes"\nextra = true'), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(bad)

    def test_cpu_is_opt_in(self):
        cfg = Config()
        cfg.compute_device = "cpu"
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_example_matches_defaults(self):
        example = ROOT / "config.example.toml"
        self.assertEqual(load_config(example), Config())

    def test_source_modes_roundtrip_and_legacy_loopback_migrates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_config(path, Config(source_mode="both"))
            self.assertEqual(load_config(path).source_mode, "both")
            legacy = path.read_text(encoding="utf-8").replace('source_mode = "both"\n', "")
            legacy = legacy.replace("loopback = false", "loopback = true")
            path.write_text(legacy, encoding="utf-8")
            self.assertEqual(load_config(path).source_mode, "system")


class PlanTests(unittest.TestCase):
    def test_download_is_explicit_and_cuda_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            missing = plan_load(Config(), models, cuda_count=1, cuda_error=None)
            self.assertEqual(missing.action, "needs_download")
            self.assertFalse(missing.local_files_only)
            offline = plan_load(Config(offline=True), models, cuda_count=1, cuda_error=None)
            self.assertEqual(offline.action, "error")
            blind = plan_load(Config(), models, cuda_count=0, cuda_error=None)
            self.assertEqual(blind.action, "error")
            broken = plan_load(Config(), models, cuda_count=None, cuda_error="CUDA library is not installed")
            self.assertEqual(broken.action, "error")
            folder = models / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
            folder.mkdir(parents=True)
            (folder / "model.bin").write_bytes(b"not a real model")
            self.assertTrue(weights_present(models, "small"))
            ready = plan_load(Config(), models, cuda_count=1, cuda_error=None)
            self.assertEqual(ready.action, "load")
            self.assertTrue(ready.local_files_only)
            custom = Config(model_path=str(Path(tmp) / "missing"))
            self.assertEqual(plan_load(custom, models, cuda_count=1, cuda_error=None).action, "error")

    def test_cpu_plan_does_not_silently_replace_cuda(self):
        cfg = Config(compute_device="cpu", allow_cpu=False)
        plan = plan_load(cfg, Path("."), cuda_count=0, cuda_error=None)
        self.assertEqual(plan.action, "error")


class StoreTests(unittest.TestCase):
    def test_log_prune_and_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.append({"ts": "2000-01-01T00:00:00+00:00", "transcript": "old", "reason": None, "flagged": False})
            store.append({"ts": "2099-01-01T00:00:00+00:00", "transcript": "new", "reason": None, "flagged": False})
            stats = store.prune(7)
            self.assertEqual(stats["events_removed"], 1)
            rows = store.tail(10)
            self.assertEqual([row["transcript"] for row in rows], ["new"])
            rel = store.write_clip([0.0, 0.5, -0.5], 16000, 1_700_000_000)
            self.assertTrue(rel.endswith(".wav"))
            path = store.clip_file(Path(rel).name)
            self.assertIsNotNone(path)
            self.assertGreater(path.stat().st_size, 44)
            self.assertIsNone(store.clip_file("../config.toml"))
            self.assertIsNone(store.clip_file("missing.wav"))


class EngineTests(unittest.TestCase):
    def test_idle_engine_has_no_transcript_or_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            engine = Engine(ensure_config(path), path)
            state = engine.snapshot()
            self.assertFalse(state["capturing"])
            self.assertEqual(state["rms"], 0.0)
            self.assertEqual(state["last_transcript"], "")
            self.assertEqual(state["recent_events"], [])
            engine.capturing = True
            engine.on_chunk([0.0, 0.25, -0.25, 0.25], 16000)
            self.assertGreater(engine.rms, 0.05)
            engine.capturing = False
            self.assertEqual(engine.live()["rms"], 0.0)
            ok, message = engine.update_settings({"sensitivity": 1.5})
            self.assertFalse(ok)
            self.assertIn("sensitivity", message)
            ok, message = engine.update_settings({"echo": True})
            self.assertFalse(ok)
            engine.stop()

    def test_each_completed_transcript_has_a_distinct_event_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            engine = Engine(ensure_config(path), path)
            utterance = SimpleNamespace(started_at=1_700_000_000, samples=[0.1] * 160, level=0.1)

            engine._finish(utterance, "same words", 0.9, 0.1, False, "test device")
            first_id = engine.snapshot()["last_transcript_id"]
            engine._finish(utterance, "same words", 0.9, 0.1, False, "test device")

            self.assertEqual(first_id, 1)
            self.assertEqual(engine.snapshot()["last_transcript_id"], 2)
            engine.stop()

    def test_malformed_settings_return_a_message_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            engine = Engine(ensure_config(path), path)

            for patch, field in (({"retention_days": "abc"}, "retention_days"), ({"sensitivity": None}, "sensitivity")):
                ok, message = engine.update_settings(patch)
                self.assertFalse(ok)
                self.assertIn(field, message)
            engine.stop()

    def test_empty_transcription_keeps_the_previous_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            engine = Engine(ensure_config(path), path)
            utterance = SimpleNamespace(started_at=1_700_000_000, samples=[0.1] * 160, level=0.1)

            engine._finish(utterance, "kept words", 0.9, 0.1, False, "test device")
            engine._finish(utterance, "", 0.4, 0.9, False, "test device")

            state = engine.snapshot()
            self.assertEqual(state["last_transcript"], "kept words")
            self.assertIn("no words", state["last_note"])
            engine.stop()

    def test_partial_transcription_keeps_only_the_latest_pending_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            engine = Engine(ensure_config(path), path)
            first = SimpleNamespace(started_at=1_700_000_000, samples=[0.1] * 160, level=0.1)
            second = SimpleNamespace(started_at=1_700_000_001, samples=[0.2] * 160, level=0.2)
            engine.model_state = "ready"
            engine.model = object()

            engine._enqueue_partial(first)
            engine._enqueue_partial(second)

            self.assertIs(engine.partial_job, second)
            engine._enqueue(first)
            self.assertIsNone(engine.partial_job)
            engine.stop()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "config.toml"
        self.engine = Engine(ensure_config(path), path)
        self.httpd = MonitorServer(("127.0.0.1", 0), self.engine)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.engine.stop()
        self.tmp.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.read()

    def _post(self, path, payload, headers=None):
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_page_and_state_are_empty_until_a_device_is_opened(self):
        status, body = self._get("/")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("Audio Monitor", text)
        self.assertIn("No transcript yet.", text)
        self.assertNotIn("http://", text.replace("http://127.0.0.1", ""))
        self.assertNotIn("https://", text)
        status, raw = self._get("/api/state")
        state = json.loads(raw.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertFalse(state["capturing"])
        self.assertEqual(state["rms"], 0.0)
        self.assertEqual(state["last_transcript"], "")
        code, payload = self._post("/api/settings", {"sensitivity": 2})
        self.assertEqual(code, 400)
        self.assertEqual(payload["state"]["last_transcript"], "")
        code, payload = self._post("/api/settings", {"flags": {"echo": True}})
        self.assertEqual(code, 400)
        code, payload = self._post("/api/device", {"index": 0, "name": "not-a-real-device", "hostapi": "none"})
        self.assertEqual(code, 409)
        self.assertFalse(payload["state"]["capturing"])
        self.assertEqual(payload["state"]["last_transcript"], "")
        devices_status, devices_raw = self._get("/api/devices")
        devices = json.loads(devices_raw.decode("utf-8"))
        self.assertEqual(devices_status, 200)
        self.assertTrue(devices["error"] or isinstance(devices["devices"], list))

    def test_closed_caption_controls_are_local_and_state_is_compatible(self):
        processes = []
        self.engine.cc.process_factory = lambda command, **kwargs: processes.append(FakeCaptionProcess()) or processes[-1]

        status, raw = self._get("/api/cc")
        cc = json.loads(raw.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertFalse(cc["enabled"])
        self.assertTrue(cc["click_through"])

        code, payload = self._post("/api/cc", {"enabled": True, "font_size": 40})
        self.assertEqual(code, 200)
        self.assertTrue(payload["state"]["cc"]["enabled"])
        self.assertEqual(payload["state"]["cc"]["font_size"], 40)
        self.assertEqual(len(processes), 1)

        state_status, state_raw = self._get("/api/state")
        self.assertEqual(state_status, 200)
        self.assertIn("last_transcript", json.loads(state_raw.decode("utf-8")))

        code, payload = self._post("/api/cc", {"enabled": False})
        self.assertEqual(code, 200)
        self.assertFalse(payload["state"]["cc"]["enabled"])
        self.assertTrue(processes[0].stopped)

    def test_closed_caption_minimize_to_tray_setting_is_exposed_by_api(self):
        status, raw = self._get("/api/cc")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw.decode("utf-8"))["minimize_to_tray"])

        code, payload = self._post("/api/cc", {"minimize_to_tray": False})
        self.assertEqual(code, 200)
        self.assertFalse(payload["state"]["cc"]["minimize_to_tray"])

    def test_malformed_settings_are_rejected_instead_of_dropping_the_connection(self):
        cases = (
            ("/api/settings", {"retention_days": "abc"}, "retention_days"),
            ("/api/settings", {"retention_days": None}, "retention_days"),
            ("/api/settings", {"sensitivity": "abc"}, "sensitivity"),
            ("/api/settings", {"sensitivity": None}, "sensitivity"),
            ("/api/cc", {"font_size": None}, "font_size"),
            ("/api/cc", {"max_width": "wide"}, "max_width"),
            ("/api/cc", {"caption_timeout": None}, "caption_timeout"),
            ("/api/cc", {"opacity": []}, "opacity"),
        )
        for path, payload, field in cases:
            code, body = self._post(path, payload)
            self.assertEqual(code, 400, payload)
            self.assertIn(field, body["message"], payload)
        status, raw = self._get("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["last_transcript"], "")

    def test_writes_require_json_from_this_page(self):
        code, _body = self._post("/api/settings", {"sensitivity": 0.6}, {"Content-Type": "text/plain"})
        self.assertEqual(code, 403)
        code, _body = self._post("/api/settings", {"sensitivity": 0.6}, {"Origin": "http://127.0.0.1:9999"})
        self.assertEqual(code, 403)
        self.assertAlmostEqual(self.engine.cfg.sensitivity, 0.55)

        code, body = self._post("/api/settings", {"sensitivity": 0.6}, {"Origin": self.base})
        self.assertEqual(code, 200, body)
        self.assertAlmostEqual(self.engine.cfg.sensitivity, 0.6)


class HygieneTests(unittest.TestCase):
    def test_package_has_no_remote_identity_or_demo_switch(self):
        banned = re.compile(
            "gr"
            + "ok|x\\.ai|\\bx"
            + "ai\\b|open"
            + "ai\\.com|api\\.open"
            + "ai|--sim"
            + "ulate|fake_"
            + "device|demo_"
            + "mode|lorem ip"
            + "sum",
            re.I,
        )
        url = re.compile(r"https?://[^\s)\"']+")
        skip = {"runtime", "__pycache__", ".venv", "models", "logs", "clips"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in skip for part in path.parts):
                continue
            if path.suffix.lower() not in {".py", ".md", ".html", ".toml", ".txt", ".ps1", ".bat", ".json"}:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(banned.search(text), f"{path} matched {banned.search(text)}")
            for found in url.findall(text):
                self.assertTrue(
                    "127.0.0.1" in found or "localhost" in found,
                    f"{path} has non-local URL {found}",
                )


if __name__ == "__main__":
    unittest.main()
