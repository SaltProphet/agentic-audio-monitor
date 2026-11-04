"""Microphone and WASAPI loopback capture."""

from __future__ import annotations

import queue
import threading


class Capture:
    def __init__(self, device_index: int, channels: int, on_chunk, on_status):
        self.device_index = device_index
        self.channels = max(1, int(channels))
        self.on_chunk = on_chunk
        self.on_status = on_status
        self.rate = 0
        self.overflows = 0
        self.last_status = ""
        self.error = ""
        self._queue: queue.Queue = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._stream = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import sounddevice as sd

        info = sd.query_devices(self.device_index, "input")
        self.rate = int(round(float(info["default_samplerate"])))
        if self.rate <= 0:
            raise RuntimeError("The selected device did not report a sample rate.")
        max_channels = int(info["max_input_channels"])
        use_channels = 1 if max_channels >= 1 else 0
        if use_channels < 1:
            raise RuntimeError("The selected device has no input channels.")
        try:
            self._stream = self._open(sd, use_channels)
        except Exception:
            if max_channels > 1:
                use_channels = min(2, max_channels)
                self._stream = self._open(sd, use_channels)
            else:
                raise
        self.channels = use_channels
        self._stream.start()
        self._thread = threading.Thread(target=self._loop, name="audio-capture", daemon=True)
        self._thread.start()

    def _open(self, sd, channels: int):
        return sd.InputStream(
            device=self.device_index,
            channels=channels,
            samplerate=self.rate,
            dtype="float32",
            blocksize=max(1, int(self.rate * 0.1)),
            latency="high",
            callback=self._callback,
        )

    def stop(self) -> None:
        self._stop.set()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self.overflows += 1
            self.last_status = str(status)
            self.on_status(self.last_status, self.overflows)
        try:
            mono = indata[:, 0].copy()
            self._queue.put_nowait(mono)
        except queue.Full:
            self.overflows += 1
            self.on_status("capture queue full", self.overflows)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.on_chunk(chunk, self.rate)
            except Exception as exc:
                self.error = str(exc)
                self.on_status(self.error, self.overflows)


class LoopbackCapture:
    """Capture the default Windows output through PyAudioWPatch WASAPI loopback."""

    def __init__(self, on_chunk, on_status):
        self.on_chunk = on_chunk
        self.on_status = on_status
        self.rate = 0
        self.channels = 0
        self.endpoint_name = ""
        self.endpoint_index = None
        self.output_name = ""
        self.overflows = 0
        self.last_status = ""
        self.error = ""
        self._queue: queue.Queue = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._audio = None
        self._stream = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import numpy as np
        import pyaudiowpatch as pyaudio

        self._audio = pyaudio.PyAudio()
        wasapi = self._audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        output_index = int(wasapi["defaultOutputDevice"])
        output = self._audio.get_device_info_by_index(output_index)
        self.output_name = str(output["name"])
        loopback = next(
            (item for item in self._audio.get_loopback_device_info_generator()
             if int(item["index"]) == output_index or item["name"].startswith(output["name"])),
            None,
        )
        if loopback is None:
            raise RuntimeError(f"No WASAPI loopback device found for {output['name']}")
        self.rate = int(round(float(loopback["defaultSampleRate"])))
        channels = max(1, int(loopback["maxInputChannels"]))
        self.channels = channels
        self.endpoint_index = int(loopback["index"])
        self.endpoint_name = str(loopback["name"])

        def callback(in_data, frame_count, time_info, status_flags):
            if status_flags:
                self.overflows += 1
                self.last_status = str(status_flags)
                self.on_status(self.last_status, self.overflows)
            data = np.frombuffer(in_data, dtype=np.float32)
            if channels > 1:
                data = data.reshape(-1, channels).mean(axis=1)
            try:
                self._queue.put_nowait(data.copy())
            except queue.Full:
                self.overflows += 1
                self.on_status("loopback queue full", self.overflows)
            return (None, pyaudio.paContinue)

        self._stream = self._audio.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=self.rate,
            input=True,
            input_device_index=self.endpoint_index,
            frames_per_buffer=max(1, int(self.rate * 0.1)),
            stream_callback=callback,
        )
        self._stream.start_stream()
        self._thread = threading.Thread(target=self._loop, name="audio-loopback", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.on_chunk(chunk, self.rate)
            except Exception as exc:
                self.error = str(exc)
                self.on_status(self.error, self.overflows)
