# Changelog

## 0.2.2

- Save the model selected on the page before **Load speech model** runs, so choosing `medium`, `large-v3`, or another model actually loads that model.
- Make **Reload speech model** reload a model that is already ready instead of returning "already loaded".
- Stop a local model load from switching the process-wide Hugging Face offline flag. That flag was cached at import time, so after `small` loaded from disk, every later `medium` or `large` download failed with `OfflineModeIsEnabled`.
- Show a download message while larger weights are being fetched, and keep the offline setting stable during the load.

## 0.2.1

- Install the CUDA 12 runtime DLLs (`nvidia-cublas-cu12` and `nvidia-cudnn-cu12`) with the other dependencies. A fresh install could previously start without them, so GPU transcription failed even though `nvidia-smi` worked.
- Preflight now reports missing `nvidia.cublas` and `nvidia.cudnn` modules and installs them on request.

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
