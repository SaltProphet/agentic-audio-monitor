---
name: agentic-audio-monitor
description: "Operate the local Windows audio monitor: list a real input, show its level, transcribe on-GPU with faster-whisper, and append a local log. Use when asked to watch the microphone, keep room audio on this PC, or run Audio Monitor. No cloud transcription and no simulated audio."
type: tool
lifecycle: active
---

# Audio Monitor

Step 1 of a local listener. Capture, level, voice activity, GPU transcription, and a JSONL log are separate. Echo, idle-speech, and speaker-loopback are named in config and are not implemented.

## When to use

- Run, stop, or uninstall the monitor on a Windows PC.
- Inspect `logs/events.jsonl` for what the microphone actually produced.
- Change device, sensitivity, retention, or the speech model in `config.toml`.

## When not to use

- Do not use this skill to invent a transcript, a level trace, or a flagged event.
- Do not add a network client, an account, or a remote upload.
- Do not turn on `flags.echo` or `flags.idle_speech` and claim they work. `source_mode` supports external, system, or both audio sources.
- Do not build step 2 unless the operator asks after testing step 1.

## Rules

1. Run `preflight.ps1` and show the operator the install list before `preflight.ps1 -Install`.
2. If `sounddevice` or `faster-whisper` is missing, say so. Do not substitute a fake meter.
3. Bind the page to `127.0.0.1` unless the operator edits `host`.
4. GPU transcription is required. Do not flip `compute_device` to `cpu` after a CUDA error unless the operator sets `allow_cpu` themselves.
5. Download weights only from the Load action, and only when `.\models` does not already contain them.
6. Log a row only when the model returns words. `reason` stays null and `flagged` stays false in this build.
7. Keep clips and logs inside the install folder. Retention uses `retention_days`.

## Operate

- Installer: `setup.bat`. It prints the preflight report and installs only after the operator types YES. It also creates the desktop and Start menu shortcuts. Do not skip the report.
- Devices without the page: `.venv\Scripts\python.exe -m monitor devices`
- Stop: `stop.bat`
- Uninstall preview: `uninstall.bat`
- Uninstall for real: `uninstall.ps1 -Yes` plus optional `-DeleteData` and `-DeleteModels`

Read `README.md` before changing behavior.

## Handoff

Report only observed facts:

- device name and host API actually opened, or the error string
- whether the meter is moving
- model state (`not_loaded`, `loading`, `ready`, `error`) and the model note
- path of `logs/events.jsonl` and the last real row, or that the file has no rows
- anything ignored because it belongs to step 2
