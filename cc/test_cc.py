import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent))

from companion import (
    DEFAULT_CONFIG,
    caption_width,
    load_config,
    read_state,
    should_minimize_to_tray,
    transcript_from_state,
    write_config,
)


class CompanionStateTests(unittest.TestCase):
    def test_root_launcher_is_the_double_click_entry_point(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "Audio Monitor.bat").read_text(encoding="utf-8")
        shortcut = (root / "shortcut.ps1").read_text(encoding="utf-8")
        self.assertIn("start.bat", launcher)
        self.assertIn('"Audio Monitor.bat"', shortcut)

    def test_caption_width_does_not_shrink_below_configured_width(self):
        self.assertEqual(caption_width({"width": 1100}, 240), 1100)

    def test_transcript_is_read_from_monitor_snapshot_and_changes_are_filtered(self):
        state = {"last_transcript": "  Hello world  ", "last_transcript_id": 7}

        self.assertEqual(transcript_from_state(state), (7, "Hello world"))
        self.assertIsNone(transcript_from_state({"last_transcript": ""}))
        self.assertIsNone(transcript_from_state({"last_transcript": None}))

    def test_config_defaults_are_used_and_values_round_trip(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            config = load_config(path)

            self.assertEqual(config, DEFAULT_CONFIG)
            self.assertIn("enabled", config)
            self.assertFalse(config["enabled"])
            self.assertTrue(config["click_through"])

            config["enabled"] = True
            config["font_size"] = 42
            config["monitor_url"] = "http://127.0.0.1:9999/api/state"
            config["click_through"] = True
            write_config(path, config)
            loaded = load_config(path)

            self.assertEqual(loaded["font_size"], 42)
            self.assertEqual(loaded["monitor_url"], "http://127.0.0.1:9999/api/state")
            self.assertTrue(loaded["enabled"])
            self.assertTrue(loaded["click_through"])

            stale = loaded.copy()
            stale["enabled"] = False
            stale["font_size"] = 44
            write_config(path, stale)
            merged = load_config(path)

            self.assertTrue(merged["enabled"])
            self.assertEqual(merged["font_size"], 44)

    def test_settings_page_has_minimize_to_tray_control(self):
        page = (Path(__file__).resolve().parents[1] / "monitor" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="cc-minimize-to-tray"', page)
        self.assertIn("Minimize captions to the system tray", page)

    def test_settings_page_has_version_and_language_selector(self):
        page = (Path(__file__).resolve().parents[1] / "monitor" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="app-version"', page)
        self.assertIn('id="language"', page)
        self.assertIn('value=""', page)
        self.assertIn('value="es"', page)

    def test_close_decision_hides_unless_quit_was_requested(self):
        self.assertTrue(should_minimize_to_tray({"minimize_to_tray": True}))
        self.assertFalse(should_minimize_to_tray({"minimize_to_tray": True}, quit_requested=True))
        self.assertFalse(should_minimize_to_tray({"minimize_to_tray": False}))

    def test_companion_state_callback_has_qt_gui_thread_affinity(self):
        source = (Path(__file__).resolve().parent / "companion.py").read_text(encoding="utf-8")
        self.assertIn("class Companion(QObject):", source)
        self.assertIn("super().__init__()", source)

    def test_invalid_config_falls_back_to_defaults(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text("not json", encoding="utf-8")

            self.assertEqual(load_config(path), DEFAULT_CONFIG)

    def test_unavailable_monitor_returns_no_state(self):
        self.assertIsNone(read_state("http://127.0.0.1:1/api/state", timeout=0.1))


if __name__ == "__main__":
    unittest.main()
