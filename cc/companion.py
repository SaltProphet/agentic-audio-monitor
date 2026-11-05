"""Transparent desktop captions for the local Audio Monitor API."""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
DEFAULT_CONFIG = {
    "enabled": False,
    "monitor_url": "http://127.0.0.1:8765/api/state",
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
}


def transcript_from_state(state: dict) -> tuple[int, str] | None:
    value = state.get("last_transcript")
    if not isinstance(value, str):
        return None
    value = value.strip()
    event_id = state.get("last_transcript_id")
    if not value or not isinstance(event_id, int) or isinstance(event_id, bool):
        return None
    return event_id, value


def caption_width(config: dict, suggested_width: int) -> int:
    return max(int(config["width"]), int(suggested_width))


def should_minimize_to_tray(config: dict, quit_requested: bool = False) -> bool:
    return bool(config.get("minimize_to_tray", True)) and not quit_requested


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("configuration must be an object")
    except (OSError, ValueError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()
    config = DEFAULT_CONFIG.copy()
    for key, default in DEFAULT_CONFIG.items():
        value = data.get(key, default)
        if isinstance(default, bool) and isinstance(value, bool):
            config[key] = value
        elif isinstance(default, str) and isinstance(value, str) and value.strip():
            config[key] = value
        elif isinstance(default, (int, float)) and isinstance(value, (int, float)) and not isinstance(value, bool):
            config[key] = value
    return config


def write_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = config.copy()
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        current = {}
    if isinstance(current, dict) and isinstance(current.get("enabled"), bool):
        output["enabled"] = current["enabled"]
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def read_state(url: str, timeout: float = 1.5) -> dict | None:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
        return None


try:
    from PySide6.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QShortcut
    from PySide6.QtWidgets import (
        QApplication,
        QInputDialog,
        QLabel,
        QMenu,
        QSystemTrayIcon,
        QWidget,
    )
except ImportError:  # Keep config/state helpers usable for checks without Qt installed.
    QApplication = None


if QApplication is not None:

    class StatePoller(QObject):
        state_received = Signal(dict)
        connection_changed = Signal(bool)

        def __init__(self, url: str):
            super().__init__()
            self.url = url
            self.stop_event = threading.Event()

        def run(self) -> None:
            connected = False
            while not self.stop_event.is_set():
                payload = read_state(self.url)
                try:
                    if payload is None:
                        raise ValueError("state request failed")
                    if not connected:
                        connected = True
                        self.connection_changed.emit(True)
                    self.state_received.emit(payload)
                except ValueError:
                    if connected:
                        connected = False
                        self.connection_changed.emit(False)
                self.stop_event.wait(0.75)

        def stop(self) -> None:
            self.stop_event.set()


    class CaptionWindow(QWidget):
        def __init__(self, config: dict):
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            flags |= Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
            super().__init__(None, flags)
            self.config = config
            self.editing = False
            self.click_through = bool(config["click_through"])
            self.drag_origin = None
            self.resize_origin = None
            self.caption_started = 0.0
            self.last_transcript = None
            self.last_transcript_event = None
            self.remote_position_revision = int(config.get("position_revision", 0))
            self.label = QLabel(self)
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.label.setWordWrap(True)
            self.label.setMargin(18)
            self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.label.setMaximumWidth(int(config["max_width"]))
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.resize(int(config["width"]), int(config["height"]))
            self._place_initially()
            self._set_text("Waiting for Audio Monitor...")
            self._set_click_through(self.click_through)
            self.expiry_timer = QTimer(self)
            self.expiry_timer.timeout.connect(self._expire_caption)
            self.expiry_timer.start(250)

        def _place_initially(self) -> None:
            if self.config["x"] >= 0 and self.config["y"] >= 0:
                self.move(int(self.config["x"]), int(self.config["y"]))
                return
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                screen.left() + (screen.width() - self.width()) // 2,
                screen.top() + screen.height() - self.height() - 80,
            )

        def _set_text(self, text: str) -> None:
            self.label.setText(text)
            self.label.setStyleSheet(
                "QLabel { color: white; background-color: rgba(0, 0, 0, %d); "
                "border: %s; border-radius: 8px; }"
                % (int(float(self.config["opacity"]) * 255), "2px solid #f0c674" if self.editing else "none")
            )
            font = QFont("Segoe UI", int(self.config["font_size"]))
            font.setWeight(QFont.Weight.DemiBold)
            self.label.setFont(font)
            if self.editing:
                self.label.setGeometry(self.rect())
            else:
                self.label.setMaximumWidth(int(self.config["max_width"]))
                width = caption_width(self.config, self.label.sizeHint().width())
                self.label.setFixedWidth(width)
                self.label.adjustSize()
                self.resize(width, self.label.sizeHint().height())
                self.label.setGeometry(self.rect())

        def apply_remote_config(self, remote: dict) -> None:
            if not isinstance(remote, dict):
                return
            for key in ("font_size", "opacity", "max_width", "caption_timeout"):
                if key in remote:
                    self.config[key] = remote[key]
            if isinstance(remote.get("minimize_to_tray"), bool):
                self.config["minimize_to_tray"] = remote["minimize_to_tray"]
            revision = int(remote.get("position_revision", self.remote_position_revision))
            if revision != self.remote_position_revision:
                self.remote_position_revision = revision
                self.config["x"], self.config["y"] = -1, -1
                self._place_initially()
                write_config(CONFIG_PATH, self.config)
            click_through = bool(remote.get("click_through", self.click_through))
            self.set_editing(not click_through)
            self.click_through = click_through
            self._set_click_through(click_through and not self.editing)
            self._set_text(self.label.text())

        def show_caption(self, event: tuple[int, str] | None) -> None:
            if event and event != self.last_transcript_event:
                self.last_transcript_event = event
                _, text = event
                self.last_transcript = text
                self.caption_started = time.monotonic()
                self._set_text(text)

        def show_connection(self, connected: bool) -> None:
            if not connected:
                self.last_transcript = None
                self._set_text("Waiting for Audio Monitor...")
            elif self.last_transcript is None:
                self._set_text("Connected - waiting for captions...")

        def _expire_caption(self) -> None:
            timeout = float(self.config["caption_timeout"])
            if self.last_transcript and timeout > 0 and time.monotonic() - self.caption_started >= timeout:
                self.last_transcript = None
                self._set_text("")

        def set_editing(self, editing: bool) -> None:
            self.editing = editing
            self._set_click_through(self.click_through and not editing)
            self._set_text(self.label.text())

        def set_click_through(self, enabled: bool) -> None:
            self.click_through = enabled
            self.config["click_through"] = enabled
            self._set_click_through(enabled and not self.editing)
            write_config(CONFIG_PATH, self.config)

        def _set_click_through(self, enabled: bool) -> None:
            if sys.platform != "win32" or not self.winId():
                return
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            get_style = user32.GetWindowLongPtrW
            set_style = user32.SetWindowLongPtrW
            style = get_style(hwnd, -20)
            no_activate = 0x08000000
            layered = 0x00080000
            transparent = 0x00000020
            if enabled:
                style |= no_activate | layered | transparent
            else:
                style &= ~transparent
            set_style(hwnd, -20, style)

        def resizeEvent(self, event) -> None:
            self.label.setGeometry(self.rect())
            super().resizeEvent(event)

        def moveEvent(self, event) -> None:
            self.config["x"], self.config["y"] = self.x(), self.y()
            super().moveEvent(event)

        def mousePressEvent(self, event) -> None:
            if (self.click_through and not self.editing) or event.button() != Qt.MouseButton.LeftButton:
                return
            point = event.position().toPoint()
            if self.editing and point.x() > self.width() - 24 and point.y() > self.height() - 24:
                self.resize_origin = (point, self.size())
            else:
                self.drag_origin = (event.globalPosition().toPoint(), self.pos())

        def mouseMoveEvent(self, event) -> None:
            if self.click_through and not self.editing:
                return
            point = event.position().toPoint()
            if self.resize_origin:
                _, original_size = self.resize_origin
                delta = point - self.resize_origin[0]
                self.resize(max(360, original_size.width() + delta.x()), max(90, original_size.height() + delta.y()))
            elif self.drag_origin:
                origin, original_pos = self.drag_origin
                self.move(original_pos + event.globalPosition().toPoint() - origin)

        def mouseReleaseEvent(self, event) -> None:
            was_moving = self.drag_origin is not None
            was_resizing = self.resize_origin is not None
            self.drag_origin = None
            self.resize_origin = None
            self.config["width"], self.config["height"] = self.width(), self.height()
            if was_moving or was_resizing:
                write_config(CONFIG_PATH, self.config)

        def closeEvent(self, event) -> None:
            if should_minimize_to_tray(self.config, getattr(self, "quit_requested", False)):
                event.ignore()
                self.hide()
                return
            self.config["x"], self.config["y"] = self.x(), self.y()
            self.config["width"], self.config["height"] = self.width(), self.height()
            write_config(CONFIG_PATH, self.config)
            super().closeEvent(event)


    class Companion(QObject):
        def __init__(self, config: dict):
            super().__init__()
            self.config = config
            self.window = CaptionWindow(config)
            self.window.quit_requested = False
            self.thread = QThread()
            self.poller = StatePoller(config["monitor_url"])
            self.poller.moveToThread(self.thread)
            self.thread.started.connect(self.poller.run)
            self.poller.state_received.connect(self._state_received)
            self.poller.connection_changed.connect(self.window.show_connection)
            self.tray = QSystemTrayIcon(QIcon(), self.window)
            self.tray.activated.connect(self._tray_activated)
            self._build_menu()
            self.tray.show()
            self.window.show()

        def _build_menu(self) -> None:
            menu = QMenu()
            show_action = QAction("Show captions", menu)
            show_action.triggered.connect(self.window.showNormal)
            menu.addAction(show_action)
            hide_action = QAction("Hide captions", menu)
            hide_action.triggered.connect(self.window.hide)
            menu.addAction(hide_action)
            menu.addSeparator()
            layout = QAction("Enter layout mode", menu)
            layout.triggered.connect(lambda: self.window.set_editing(not self.window.editing))
            menu.addAction(layout)
            click_through = QAction("Click-through", menu)
            click_through.setCheckable(True)
            click_through.setChecked(self.window.click_through)
            click_through.toggled.connect(self.window.set_click_through)
            menu.addAction(click_through)
            menu.addAction(self._setting_action(menu, "Font size", "font_size", 12, 96, int))
            menu.addAction(self._setting_action(menu, "Background opacity", "opacity", 0.1, 1.0, float))
            menu.addAction(self._setting_action(menu, "Caption timeout (seconds)", "caption_timeout", 0, 120, float))
            menu.addSeparator()
            quit_action = QAction("Quit", menu)
            quit_action.triggered.connect(self._quit)
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)

        def _tray_activated(self, reason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self.window.showNormal()

        def _quit(self) -> None:
            self.window.quit_requested = True
            QApplication.quit()

        def _setting_action(self, menu, name, key, minimum, maximum, converter):
            action = QAction(name, menu)

            def change():
                value, ok = QInputDialog.getDouble(self.window, name, name, float(self.config[key]), minimum, maximum, 1)
                if ok:
                    self.config[key] = converter(value)
                    self.window._set_text(self.window.label.text())
                    write_config(CONFIG_PATH, self.config)

            action.triggered.connect(change)
            return action

        def _state_received(self, state: dict) -> None:
            remote = state.get("cc")
            if isinstance(remote, dict):
                if not remote.get("enabled", True):
                    QApplication.quit()
                    return
                self.window.apply_remote_config(remote)
            self.window.show_caption(transcript_from_state(state))

        def start(self) -> None:
            self.thread.start()

        def stop(self) -> None:
            self.poller.stop()
            self.thread.quit()
            self.thread.wait(2500)
            write_config(CONFIG_PATH, self.config)


def run_app() -> int:
    if QApplication is None:
        print("PySide6 is required. Run cc\\run.bat or install the project requirements.", file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    write_config(CONFIG_PATH, config)
    companion = Companion(config)
    companion.start()
    app.aboutToQuit.connect(companion.stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_app())
