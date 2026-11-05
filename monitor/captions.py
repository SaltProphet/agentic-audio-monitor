"""Optional local controller for the separate closed-caption process."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


DEFAULTS = {
    "enabled": False,
    "x": -1,
    "y": -1,
    "width": 1100,
    "height": 180,
    "font_size": 34,
    "opacity": 0.55,
    "max_width": 720,
    "caption_timeout": 0.0,
    "click_through": True,
    "minimize_to_tray": True,
    "position_revision": 0,
    "monitor_url": "http://127.0.0.1:8765/api/state",
}
ALLOWED = set(DEFAULTS) | {"reset_position"}


def companion_python(root: Path) -> str:
    """Use the project's environment so the CC dependencies match the monitor."""
    root = Path(root)
    candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


class CCController:
    def __init__(self, root: Path, process_factory=subprocess.Popen):
        self.root = Path(root)
        self.path = self.root / "cc" / "config.json"
        self.process_factory = process_factory
        self.config = self._load()
        self.process = None
        self.error = ""

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("configuration must be an object")
        except (OSError, ValueError, json.JSONDecodeError):
            raw = {}
        config = DEFAULTS.copy()
        for key, default in DEFAULTS.items():
            value = raw.get(key, default)
            if isinstance(default, bool) and isinstance(value, bool):
                config[key] = value
            elif isinstance(default, str) and isinstance(value, str) and value.strip():
                config[key] = value
            elif isinstance(default, (int, float)) and isinstance(value, (int, float)) and not isinstance(value, bool):
                config[key] = value
        return config

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")

    def snapshot(self) -> dict:
        self._sync_geometry()
        returncode = None if self.process is None else self.process.poll()
        running = self.process is not None and returncode is None
        if self.config["enabled"] and self.process is not None and returncode is not None and not self.error:
            self.error = f"CC companion exited with code {returncode}."
        return {**self.config, "running": running, "error": self.error}

    def apply(self, patch: dict) -> tuple[bool, str]:
        if not isinstance(patch, dict):
            return False, "Closed-caption settings must be an object."
        unknown = set(patch) - ALLOWED
        if unknown:
            return False, "Unknown closed-caption setting: " + ", ".join(sorted(unknown))
        self._sync_geometry()
        candidate = self.config.copy()
        if patch.get("reset_position"):
            candidate["x"], candidate["y"] = -1, -1
            candidate["position_revision"] = int(candidate.get("position_revision", 0)) + 1
        candidate.update({key: value for key, value in patch.items() if key != "reset_position"})
        try:
            self._validate(candidate)
        except ValueError as exc:
            return False, str(exc)
        self.config = candidate
        self._save()
        self.error = ""
        if self.config["enabled"]:
            self._start()
        else:
            self._stop()
        return True, "Closed captions enabled." if self.config["enabled"] else "Closed captions disabled."

    def start_if_enabled(self) -> None:
        if self.config["enabled"]:
            self._start()

    def stop(self) -> None:
        self._stop()

    def _validate(self, config: dict) -> None:
        if any(not isinstance(config[key], bool) for key in ("enabled", "click_through", "minimize_to_tray")):
            raise ValueError("enabled, click_through, and minimize_to_tray must be boolean")
        if not 12 <= int(config["font_size"]) <= 96:
            raise ValueError("font_size must be between 12 and 96")
        if not 0.1 <= float(config["opacity"]) <= 1:
            raise ValueError("opacity must be between 0.1 and 1")
        if not 240 <= int(config["max_width"]) <= 2000:
            raise ValueError("max_width must be between 240 and 2000")
        if not 0 <= float(config["caption_timeout"]) <= 120:
            raise ValueError("caption_timeout must be between 0 and 120")

    def _sync_geometry(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for key in ("x", "y", "width", "height", "position_revision"):
            if isinstance(raw.get(key), (int, float)) and not isinstance(raw[key], bool):
                self.config[key] = raw[key]

    def _start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        command = [companion_python(self.root), str(self.root / "cc" / "companion.py")]
        kwargs = {
            "cwd": str(self.root),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self.process = self.process_factory(command, **kwargs)
            self.error = ""
        except (OSError, ValueError) as exc:
            self.process = None
            self.error = str(exc)

    def _stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
