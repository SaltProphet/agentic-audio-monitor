# Caption Companion

The Caption Companion is a separate Windows desktop overlay for the existing Audio Monitor. The monitor's web UI controls its lifecycle and settings. It polls `http://127.0.0.1:8765/api/state`, displays only the monitor's authoritative `last_transcript`, and performs no audio capture, transcription, translation, or cloud communication.

## Start

1. Start the Audio Monitor with the repository's `run.bat` and open its local page.
2. Use the **Closed captions** section to enable and configure the overlay.

PySide6 is included in the root `requirements.txt`; run the existing setup/install flow if the project environment has not been updated. `cc\run.bat` remains available for standalone troubleshooting.

The companion shows `Waiting for Audio Monitor...` while the local API is unavailable and reconnects automatically.

## Layout mode

The monitor UI's **Unlock / Move captions** button disables click-through and makes the overlay draggable/resizable. **Lock captions** restores click-through. The tray menu remains available when running standalone.

Enable **Minimize captions to the system tray** in the monitor UI to hide the overlay when its window is closed without stopping captions. Restore it with the tray icon or the tray menu. Use the tray menu's **Quit** action to stop the companion explicitly.

## Configuration

CC settings are stored separately at `cc\config.json`. The file stores lifecycle state, position, size, font size, compact maximum width, opacity, timeout, lock state, minimize-to-tray preference, and monitor URL.
