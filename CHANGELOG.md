# Changelog

## 0.2.0

- Harden the local API: malformed settings return 400, writes must be JSON from this page, and unexpected errors return 500 instead of dropping the connection.
- Open the requested audio sources before saving a source or device change, so a failed switch leaves the config file and the running capture untouched.
- Keep the last transcript on screen when a segment returns no words.
- Add response security headers and remove the unused package-download hook.
- Single-source the version from `monitor.__version__` and add `pyproject.toml` plus release contract tests.
- Run the monitor and companion suites on Windows in GitHub Actions for Python 3.11, 3.12, and 3.13.
- Scope `stop.ps1` to this install and stop forcing closed captions on at start; both now follow the saved setting.
- Add the PolyForm Noncommercial 1.0.0 license: free for noncommercial use, commercial use requires a separate license.
- Remove the duplicate nested repository, stale backup files, dead capture wrappers, and an empty references folder.

## 0.1.0

- Step 1: choose an input, live level, energy voice activity, local GPU transcription, JSONL log, optional WAV per transcript, retention.
- `setup.bat` installs the libraries after YES and adds desktop and Start menu shortcuts to `run.bat`.
- Echo and idle-speech flags are stored and not acted on.
