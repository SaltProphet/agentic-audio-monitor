# Audio Monitor

Local audio monitor for Windows 11. It listens to a microphone or the default speaker output through WASAPI loopback, shows the real level, transcribes or translates speech on the GPU, and appends a log on this PC.

It does not invent levels or transcripts. If the device or the speech model is unavailable, the page shows that error and leaves the transcript empty.

## Not in this build

Echo and keyboard-idle speech are still stored settings and are not implemented. `source_mode` selects external microphone, system audio loopback, or both sources.

The page is the whole control surface. An optional caption companion draws closed captions on the desktop and adds its own tray icon; the page's **Closed captions** section starts and stops it.

## What can leave this PC

- `setup.bat` is the installer. It prints the list below, then waits until you type YES. It installs into `.\.venv` and adds an Audio Monitor shortcut on the desktop and in the Start menu. It does not send audio and it does not download the speech model.
- The first time you press **Load speech model**, and only if `.\models` does not already contain those weights, the speech library downloads them into `.\models`.
- After the weights are on disk, later runs open them locally even if `offline` is still false.
- Set `offline = true` before that first load if you do not want the download. Transcription then stays off until you place a `model.bin` folder yourself and set `model_path`.

No account, no phone-home switch, and no cloud transcription.

## What will be installed

Nothing is installed until you type YES in `setup.bat` (or run `install.bat` / `preflight.ps1 -Install` yourself).

`preflight.bat` only prints what is already there. On a machine that does not have the libraries yet, the install step creates `.\.venv` and installs:

- `pip` inside that `.venv`
- `sounddevice==0.5.6`
- `PyAudioWPatch`
- `faster-whisper==1.2.1`
- `PySide6` for the caption companion
- their dependencies: `numpy`, `cffi`, `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av`, `tqdm`

It does not install a CUDA toolkit, Docker, a system ffmpeg, or a CPU transcription fallback. The NVIDIA driver is assumed to already be on the machine. `nvidia-smi` must work or GPU transcription will refuse to start.

Use Python 3.12 if you can. 3.11 and 3.13 are accepted. Older than 3.11 and newer than 3.13 are not supported.

## Run

Follow [INSTALL.md](INSTALL.md). Short form: extract the folder, double-click `setup.bat`, type YES. The page is `http://127.0.0.1:8765/`.

For a normal desktop start, double-click `Audio Monitor.bat` or the **Audio Monitor** shortcut. For lifecycle commands, run `agentic-audio-monitor.bat start`, `agentic-audio-monitor.bat stop`, or `agentic-audio-monitor.bat restart`. Use `agentic-audio-monitor.bat status` to check the monitor process. Closed captions start and stop with the setting saved on the page.

## Project layout

See [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md) for the distinction between application code, the separate CC companion, tests, launchers, and runtime data.

## Stop

Double-click `stop.bat`, or close the `run.bat` window.

`stop.bat` reads `monitor.pid` and stops that process. It does not delete logs.

## Uninstall

- `uninstall.bat` prints what it would remove and removes nothing.
- To remove the private library folder: `powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1 -Yes`
- Also remove logs, clips, `config.toml`, and `cc\config.json`: add `-DeleteData`
- Also remove downloaded weights in `.\models`: add `-DeleteModels`

A `model_path` outside this folder is never deleted. The program files stay until you delete the folder.

## Config

`config.toml` is created next to `run.bat` on the first start, from `config.example.toml`. The page rewrites it when you save or pick a device.

| Key | Meaning |
| --- | --- |
| `device_name`, `device_hostapi`, `device_index` | Remembered input. Empty until you pick one. |
| `sensitivity` | `0` to `1`. Higher hears quieter sound. |
| `save_clips` | WAV next to each transcript. Off by default. |
| `retention_days` | Delete older log rows and clips. Default 7. |
| `model` | `tiny`, `base`, `small`, `medium`, `large-v3`, or the `.en` variants except `large-v3`. Default `small`. |
| `model_path` | Folder that already contains `model.bin`. No download is attempted for this path. |
| `language` | `en` by default. Empty lets the model choose. |
| `task` | `transcribe` or `translate`; translation produces English text from supported source languages. |
| `compute_device` | `cuda`. `cpu` is rejected unless `allow_cpu` is true. |
| `compute_type` | `float16` on the GPU. Use `int8` if you opted into CPU. |
| `allow_cpu` | `false`. Must be true before `compute_device = "cpu"` is accepted. |
| `offline` | Refuse the weight download. |
| `host`, `port` | Page bind. Default `127.0.0.1` and `8765`. Restart after editing these. |
| `flags.echo`, `flags.idle_speech` | Stored but not implemented. |
| `source_mode` | `external`, `system`, or `both`. System audio uses the Windows default WASAPI loopback endpoint. |

Files written beside the config:

- `logs/events.jsonl` — time, transcript, `reason` (null in this build), `flagged` (false), confidence, duration, level, clip name, device
- `clips/*.wav` — only when `save_clips` is true and there is a transcript
- `models/` — speech weights after the first load
- `monitor.log` — process errors, not transcripts
- `monitor.pid` — the running process

## If it will not listen or will not transcribe

- No devices, or an import error: run `install.bat` and then `run.bat` again. The page is telling you the audio library is missing or the host returned no inputs. Loopback requires the default output to expose a Windows WASAPI loopback device.
- Meter stays at "not capturing": you have not pressed **Use this device**, or that device failed to open. The error is on the page. Pick another input. Prefer the one marked system default if you want the default microphone.
- Model line says no CUDA device, or that the CUDA library is missing: `nvidia-smi` is the check. This build will not quietly switch to the CPU.
- Model line says weights are not on disk: press **Load speech model**, or set `offline = true` and provide `model_path`.
- Utterance count climbs but the log stays empty: the model was not loaded yet, or it returned no words. Nothing is filled in for those.

## Tests

From this folder, after install, or with any Python 3.11-3.13 even before install:

```
python -m unittest discover -s tests -v
```

The companion has its own suite:

```
python -m unittest discover -s cc -p "test_*.py" -v
```

The tests do not open a microphone and do not download a model. GitHub Actions runs both suites on Windows for Python 3.11, 3.12, and 3.13.

`pyproject.toml` holds the version and dependency metadata; `requirements.txt` is the installer manifest and the two are checked against each other by `tests/test_release.py`.

## License

This project is licensed under the PolyForm Noncommercial License 1.0.0. See [LICENSE](LICENSE).

Personal, hobby, research, educational, and other noncommercial use is allowed. Commercial use, resale, or inclusion in a paid product requires a separate written license from the copyright holder.
