# Project Layout

The repository keeps the user-facing Windows entry points at the root so existing shortcuts and instructions continue to work.

## Application code

- `monitor\` — Audio Monitor Python package: capture, VAD, transcription, local HTTP server, and web UI.
- `monitor\web\` — The browser control page served by the monitor.
- `cc\` — Separate PySide6 desktop caption companion and its CC-only configuration.

## Verification and references

- `tests\` — Hardware-independent Python regression tests for the monitor, capture-source switching, CC controls, and CC configuration.
- `evals\` — Evaluation fixtures.
- `docs\reference\` — Design or future-step notes that are not runtime code.

## Root entry points

- `run.bat` / `run.ps1` — Start Audio Monitor.
- `agentic-audio-monitor.bat` — Unified start/stop/restart/status launcher. CC is managed by the running monitor.
- `setup.bat` / `setup.ps1` — Install the project environment.
- `preflight.bat` / `preflight.ps1` — Inspect or install prerequisites.
- `stop.bat` / `stop.ps1` — Stop the running monitor.
- `uninstall.bat` / `uninstall.ps1` — Preview or perform removal.
- `shortcut.bat` / `shortcut.ps1` — Create Windows shortcuts.

These remain at the root because the launcher scripts, Windows shortcuts, and installation documentation refer to them there.

## Runtime state and generated data

- `config.toml` — Main monitor configuration.
- `cc\config.json` — Caption companion configuration.
- `logs\` — Local event log and saved clips.
- `models\` — Locally cached speech-model files.
- `monitor.log` / `monitor.pid` — Monitor runtime log and process marker.
- `.venv\` — Project Python environment.

Backup files named `*.bak-*` are retained as-is and are not part of the active runtime tree. The nested `agentic-audio-monitor\` directory is a duplicate repository and is intentionally not used.
