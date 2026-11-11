import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor.config import Config, load_config, save_config
from monitor.engine import Engine


class FakeCapture:
    instances = []

    def __init__(self, *args):
        self.rate = 44100
        self.channels = 1
        self.stopped = False
        self.started = False
        FakeCapture.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeLoopbackCapture(FakeCapture):
    fail = False

    def __init__(self, *args):
        super().__init__(*args)
        self.rate = 48000
        self.endpoint_name = "Default output [Loopback]"
        self.endpoint_index = 13
        self.output_name = "Default output"

    def start(self):
        if self.fail:
            raise RuntimeError("WASAPI loopback endpoint could not be opened")
        super().start()


class FailingCapture(FakeCapture):
    def start(self):
        raise RuntimeError("device could not be opened")


class CaptureSourceTests(unittest.TestCase):
    def _engine(self, tmp):
        path = Path(tmp) / "config.toml"
        cfg = Config(device_name="Microphone", device_hostapi="Windows WASAPI", device_index=4)
        save_config(path, cfg)
        return Engine(cfg, path)

    def test_switching_microphone_to_loopback_stops_old_capture_first(self):
        FakeCapture.instances = []
        FakeLoopbackCapture.fail = False
        with tempfile.TemporaryDirectory() as tmp, patch("monitor.capture.Capture", FakeCapture), patch(
            "monitor.capture.LoopbackCapture", FakeLoopbackCapture
        ), patch(
            "monitor.engine.devices.list_inputs",
            return_value=[{"index": 4, "channels": 1, "name": "Microphone", "hostapi": "Windows WASAPI"}],
        ):
            engine = self._engine(tmp)
            engine._start_sources("external", match={"index": 4, "channels": 1, "name": "Microphone", "hostapi": "Windows WASAPI"})
            microphone = FakeCapture.instances[-1]
            ok, message = engine.update_settings({"loopback": True})

            self.assertTrue(ok, message)
            self.assertTrue(microphone.stopped)
            self.assertIsInstance(engine.capture, FakeLoopbackCapture)
            self.assertTrue(engine.capturing)
            self.assertEqual(engine.snapshot()["source"], "system")
            self.assertTrue(load_config(Path(tmp) / "config.toml").flags["loopback"])
            engine.stop()

    def test_switching_loopback_to_microphone_stops_old_capture_first(self):
        FakeCapture.instances = []
        FakeLoopbackCapture.fail = False
        with tempfile.TemporaryDirectory() as tmp, patch("monitor.capture.Capture", FakeCapture), patch(
            "monitor.capture.LoopbackCapture", FakeLoopbackCapture
        ), patch(
            "monitor.engine.devices.list_inputs",
            return_value=[{"index": 4, "channels": 1, "name": "Microphone", "hostapi": "Windows WASAPI"}],
        ):
            engine = self._engine(tmp)
            engine.cfg.source_mode = "system"
            engine._start_sources("system")
            loopback = FakeCapture.instances[-1]
            ok, message = engine.update_settings({"source_mode": "external"})

            self.assertTrue(ok, message)
            self.assertTrue(loopback.stopped)
            self.assertIsInstance(engine.capture, FakeCapture)
            self.assertNotIsInstance(engine.capture, FakeLoopbackCapture)
            self.assertTrue(engine.capturing)
            self.assertEqual(engine.snapshot()["source"], "external")
            engine.stop()

    def test_failed_loopback_start_is_reported_and_not_reported_as_active_source(self):
        FakeCapture.instances = []
        FakeLoopbackCapture.fail = True
        with tempfile.TemporaryDirectory() as tmp, patch("monitor.capture.LoopbackCapture", FakeLoopbackCapture):
            engine = self._engine(tmp)
            ok, message = engine.update_settings({"loopback": True})

            self.assertFalse(ok)
            self.assertIn("WASAPI loopback", message)
            self.assertFalse(engine.capturing)
            self.assertIsNone(engine.capture)
            self.assertEqual(engine.snapshot()["source"], "none")
            self.assertIn("WASAPI loopback", engine.snapshot()["capture_error"])
            self.assertEqual(load_config(Path(tmp) / "config.toml").source_mode, "external")
            engine.stop()

    def test_failed_device_select_keeps_the_saved_device(self):
        FakeCapture.instances = []
        with tempfile.TemporaryDirectory() as tmp, patch("monitor.capture.Capture", FailingCapture), patch(
            "monitor.engine.devices.list_inputs",
            return_value=[{"index": 9, "channels": 1, "name": "Other mic", "hostapi": "MME"}],
        ):
            engine = self._engine(tmp)
            before = load_config(Path(tmp) / "config.toml")

            ok, message = engine.select_device(9, "Other mic", "MME")

            self.assertFalse(ok)
            self.assertIn("could not be opened", message)
            after = load_config(Path(tmp) / "config.toml")
            self.assertEqual(after.device_name, before.device_name)
            self.assertEqual(after.device_index, before.device_index)
            self.assertEqual(after.source_mode, before.source_mode)
            engine.stop()

    def test_selecting_a_device_explicitly_switches_from_loopback_to_microphone(self):
        FakeCapture.instances = []
        FakeLoopbackCapture.fail = False
        with tempfile.TemporaryDirectory() as tmp, patch("monitor.capture.Capture", FakeCapture), patch(
            "monitor.capture.LoopbackCapture", FakeLoopbackCapture
        ), patch(
            "monitor.engine.devices.list_inputs",
            return_value=[{"index": 4, "channels": 1, "name": "Microphone", "hostapi": "Windows WASAPI"}],
        ):
            engine = self._engine(tmp)
            engine.cfg.source_mode = "system"
            engine.cfg.flags["loopback"] = True
            engine._start_sources("system")
            loopback = FakeCapture.instances[-1]

            ok, message = engine.select_device(4, "Microphone", "Windows WASAPI")

            self.assertTrue(ok, message)
            self.assertFalse(engine.cfg.flags["loopback"])
            saved = load_config(Path(tmp) / "config.toml")
            self.assertEqual(saved.source_mode, "external")
            self.assertFalse(saved.flags["loopback"])
            self.assertTrue(loopback.stopped)
            self.assertIsInstance(engine.capture, FakeCapture)
            self.assertNotIsInstance(engine.capture, FakeLoopbackCapture)
            self.assertEqual(engine.snapshot()["source"], "external")
            engine.stop()

    def test_both_source_mode_starts_external_and_system_capture(self):
        FakeCapture.instances = []
        FakeLoopbackCapture.fail = False
        with tempfile.TemporaryDirectory() as tmp, patch("monitor.capture.Capture", FakeCapture), patch(
            "monitor.capture.LoopbackCapture", FakeLoopbackCapture
        ), patch(
            "monitor.engine.devices.list_inputs",
            return_value=[{"index": 4, "channels": 1, "name": "Microphone", "hostapi": "Windows WASAPI"}],
        ):
            engine = self._engine(tmp)
            ok, message = engine.update_settings({"source_mode": "both"})

            self.assertTrue(ok, message)
            self.assertEqual(engine.cfg.source_mode, "both")
            self.assertEqual(len(FakeCapture.instances), 2)
            self.assertEqual(engine.snapshot()["source"], "both")
            self.assertTrue(all(not capture.stopped for capture in FakeCapture.instances))
            engine.stop()


if __name__ == "__main__":
    unittest.main()
