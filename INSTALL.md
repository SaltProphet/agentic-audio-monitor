# Install Audio Monitor

Windows 11 only. Extract the folder, then double-click `setup.bat`. That is the installer. It prints what it will add, waits until you type YES, installs those libraries into `.venv`, and creates an **Audio Monitor** shortcut on the desktop and in the Start menu.

It does not use Docker. It does not install a CUDA toolkit. It does not send microphone audio anywhere. The speech-model weights are not downloaded by the installer.

## Before you start

You need:

- Windows 11 on the PC that has the microphone (this package is meant for the Shadow PC with the RTX A4500).
- An NVIDIA driver already installed. The installer will not add one.
- Python 3.12 if it is not already there. 3.11 and 3.13 are also accepted. 3.10 and older are not. 3.14 and newer are not.
- A folder you can write to. Setup creates `.venv` in that same folder. Later, the app writes `config.toml`, `logs`, and `models` there.
- Network access while setup installs the libraries. The speech model is a separate download, only if you later press **Load speech model** and `models` does not already have the weights.

You do not need ffmpeg, WSL, or an account.

## 1. Confirm the GPU is visible

1. Open PowerShell.
2. Run:

```
nvidia-smi
```

3. You should see the GPU name (RTX A4500), a driver version, and memory. If the command is not found, stop. Transcription will refuse to start until the driver is visible. Do not switch the app to CPU to hide that.

## 2. Put the folder on the PC

1. Copy `agentic-audio-monitor.zip` onto the Windows PC.
2. If the zip was downloaded, right-click it, open Properties, and if there is an **Unblock** checkbox, check it and click Apply. Then extract.
3. Extract the whole folder. A simple path is easier, for example `C:\AudioMonitor`. Do not put it somewhere you cannot write to. Leave it there. The shortcut points at this copy. If you move the folder later, double-click `shortcut.bat` again.
4. You should see `setup.bat` in that folder.

## 3. Run the installer

1. Double-click `setup.bat`.
2. Read the report. It is the same check as `preflight.bat` and it installs nothing by itself.

| Line | What you want |
| --- | --- |
| `Python:` | A version starting with `3.11`, `3.12`, or `3.13`. |
| `NVIDIA:` | The GPU name and driver. If it says `nvidia-smi was not found`, go back to step 1. |
| `Existing .venv:` | `no` on a first install. |
| `Would install into .\.venv only:` | `pip`, `sounddevice==0.5.6`, `faster-whisper==1.2.1`, plus `numpy`, `cffi`, `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av`, and `tqdm`. |
| `Would not install:` | CUDA toolkit, Docker, system ffmpeg, CPU fallback. |
| Last line of the check | `No install was performed.` |

3. If Python says `MISSING`, close the window and install Python 3.12 from the Python Windows installer. Enable **Add python.exe to PATH** and the **py launcher**. Then run `setup.bat` again.
4. At the prompt, type `YES` and press Enter. Anything else installs nothing.
5. Wait until it says `Setup finished.` The first run can take several minutes because the GPU speech library is large.
6. It writes two shortcuts named **Audio Monitor**, one on the desktop and one in the Start menu. Both start `run.bat` in this folder.
7. Type `YES` again only if you want the monitor to start now. Otherwise close the window and use the shortcut later.

## 4. First start

1. Double-click the **Audio Monitor** shortcut, or double-click `run.bat`.
2. Leave that window open. Closing it stops the monitor.
3. The window prints `Audio Monitor is at http://127.0.0.1:8765/` and opens that page. If the browser does not open, type that address yourself. It is only this PC.
4. The page should show **not capturing**, **Voice activity off**, and **No transcript yet.** That is correct. It has not opened a microphone yet.
5. Refresh the device list if it is empty, pick the input, and click **Use this device**. The meter moves only after this. The choice is saved in `config.toml`.
6. Click **Load speech model**. The first time, if `models` is empty, this downloads the `small` weights into that folder. That is a few hundred megabytes and the only model download.
7. Speak after the note says the model is loaded. A row appears in `logs\events.jsonl` only when the model returns words.

## Later starts

Double-click **Audio Monitor**. The device is remembered. If the weights are already in `.\models`, they load from disk and are not downloaded again.

## Stop

Double-click `stop.bat`, or close the Audio Monitor window.

`stop.bat` stops the process id in `monitor.pid`. It does not delete logs, shortcuts, or the model.

## Uninstall

1. Double-click `uninstall.bat`. It prints what it would remove and removes nothing.
2. To remove the private libraries and the shortcuts, open PowerShell in this folder and run:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1 -Yes
```

3. To also remove logs, clips, and `config.toml`, add `-DeleteData`.
4. To also remove downloaded weights in `.\models`, add `-DeleteModels`.
5. A `model_path` that points outside this folder is never deleted.
6. The program files stay until you delete the folder yourself.

## If you want the steps split apart

- `preflight.bat` only prints the check.
- `install.bat` installs the libraries after you have read that check. It does not create shortcuts.
- `shortcut.bat` writes only the desktop shortcut.
- `run.bat` starts the monitor.

## If a step fails

- **Python: MISSING.** Install Python 3.12 with the py launcher and PATH option. Run `setup.bat` again.
- **nvidia-smi was not found**, or the page says no CUDA device or the CUDA library is missing. The driver is not visible. The app will not fall back to the CPU. Fix the driver, then start again.
- **No module named sounddevice** on the page. Setup did not finish. Run `setup.bat` again in this same folder.
- **No input devices reported.** Windows returned none. Check Settings, System, Sound, Input. Then click **Refresh devices**.
- **Meter never moves after Use this device.** Read the error under the device list. Try the device marked system default.
- **Load speech model fails.** Read the note on the page. If `offline = true` before the weights exist, it will not download.
- **The shortcut does nothing or the window flashes closed.** The folder was moved. Double-click `shortcut.bat` from the new folder, or run `setup.bat` again.
- **Address already in use.** Another copy is running. Use `stop.bat`, then the shortcut.

## What this install does not do

Echo, idle-speech, and speaker-match flags are in `config.toml` and are ignored. Leave them false. They are step 2 and are not part of this install.
