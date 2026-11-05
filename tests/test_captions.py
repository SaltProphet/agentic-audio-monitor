import tempfile
import unittest
from pathlib import Path

from monitor.captions import CCController, companion_python


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class CaptionControllerTests(unittest.TestCase):
    def test_companion_uses_project_virtualenv_when_monitor_uses_system_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_path = root / ".venv" / "Scripts" / "python.exe"
            python_path.parent.mkdir(parents=True)
            python_path.write_text("", encoding="utf-8")

            self.assertEqual(companion_python(root), str(python_path))

    def test_defaults_are_disabled_and_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = CCController(Path(tmp), process_factory=lambda command, **kwargs: FakeProcess())

            state = controller.snapshot()
            self.assertFalse(state["enabled"])
            self.assertTrue(state["click_through"])
            self.assertEqual(state["opacity"], 0.55)
            self.assertEqual(state["caption_timeout"], 0.0)

            ok, message = controller.apply({"enabled": True, "font_size": 42, "opacity": 0.3})
            self.assertTrue(ok, message)
            self.assertTrue(controller.snapshot()["running"])
            self.assertEqual(controller.snapshot()["font_size"], 42)

            reloaded = CCController(Path(tmp), process_factory=lambda command, **kwargs: FakeProcess())
            self.assertTrue(reloaded.snapshot()["enabled"])
            self.assertEqual(reloaded.snapshot()["opacity"], 0.3)
            self.assertTrue(reloaded.snapshot()["minimize_to_tray"])

    def test_minimize_to_tray_setting_round_trips_and_rejects_non_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = CCController(Path(tmp), process_factory=lambda command, **kwargs: FakeProcess())

            ok, message = controller.apply({"minimize_to_tray": False})
            self.assertTrue(ok, message)
            self.assertFalse(controller.snapshot()["minimize_to_tray"])

            ok, message = controller.apply({"minimize_to_tray": "no"})
            self.assertFalse(ok)
            self.assertIn("minimize_to_tray", message)

    def test_repeated_enable_does_not_launch_duplicate_process(self):
        processes = []

        def launch(command, **kwargs):
            process = FakeProcess()
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as tmp:
            controller = CCController(Path(tmp), process_factory=launch)
            controller.apply({"enabled": True})
            controller.apply({"enabled": True})

            self.assertEqual(len(processes), 1)

    def test_disable_stops_companion_and_rejects_unknown_settings(self):
        processes = []

        def launch(command, **kwargs):
            process = FakeProcess()
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as tmp:
            controller = CCController(Path(tmp), process_factory=launch)
            controller.apply({"enabled": True})
            ok, message = controller.apply({"not_a_setting": True})
            self.assertFalse(ok)
            self.assertIn("not_a_setting", message)
            controller.apply({"enabled": False})

            self.assertTrue(processes[0].terminated)
            self.assertFalse(controller.snapshot()["running"])

    def test_failed_companion_launch_is_reported_without_failing_monitor_control(self):
        def launch(command, **kwargs):
            raise OSError("PySide6 is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            controller = CCController(Path(tmp), process_factory=launch)
            ok, message = controller.apply({"enabled": True})

            self.assertTrue(ok, message)
            self.assertFalse(controller.snapshot()["running"])
            self.assertIn("PySide6", controller.snapshot()["error"])


if __name__ == "__main__":
    unittest.main()
