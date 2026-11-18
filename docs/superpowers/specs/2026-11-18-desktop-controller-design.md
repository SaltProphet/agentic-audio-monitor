# Desktop controller for Audio Monitor

Date: 2026-11-18
Status: approved design, ready for plan
Target release: 0.3.0

## Intent

Replace the daily file-and-folder ritual with one desktop control surface. Today the
user opens the install folder, runs a `.bat`, gets a console window and the full
settings dashboard, configures source/model/task/language, finds a small captions
checkbox, and later has to run a second `.bat` because closing the window leaves the
caption overlay running.

The user wants a system tray icon as the minimum control surface, an optional small
floating status pill with a live waveform, and an X on the caption overlay that turns
captions off. Starting should use the saved configuration and should not open the
dashboard or a console. Stopping should stop the monitor and the captions together.

## Goals

- Start, stop, and restart the whole app from a tray icon.
- Show running/stopped state at a glance, including for colorblind users.
- Start hidden, with the saved source, model, task, and language.
- Open the main web UI only when requested; if stopped, start first and then open it.
- Stop the monitor and caption overlay together, with no orphan overlay.
- Provide an optional floating pill: status shape plus a small live waveform,
  draggable and position-remembering.
- Provide a hover X on the caption overlay that disables captions without stopping
  the monitor.
- Make "start with Windows" a setting.
- Handle a first run, a port collision, and a crashed/orphaned caption companion
  without sending the user back to a folder.
- Package the controller as a Windows executable and provide a real installer.

## Non-goals

- A Chrome extension. It cannot start or stop a local Python process, capture desktop
  audio, or draw an always-on-top desktop overlay outside Chrome.
- Bundling CUDA, faster-whisper, and model weights into one executable.
- Redesigning the main settings dashboard.
- Cloud services, accounts, or remote access.
- Auto-update, code signing, and installer branding.

## User experience

### Tray icon

The controller owns one notification-area icon. State is conveyed by shape as well as
color:

- Grey ring: monitor stopped.
- Amber diamond: starting, or the monitor is up but the model is loading.
- Green circle: monitor is capturing and the model is ready.
- Red square: the monitor is up but capture or model load failed.

Left-click or double-click opens the main UI. Right-click opens:

- Start
- Stop
- Restart monitor
- Open main UI
- Source: Microphone / System audio / Both
- Task: Transcribe / Translate
- Captions on/off
- Show waveform
- Start with Windows (and begin listening)
- Open monitor log
- Open desktop log
- Quit

`Quit` stops the monitor, stops captions, and exits the controller. Closing the main
UI does not stop anything; the tray icon remains.

The tooltip reports `Audio Monitor - running/stopped`, the current level when running,
the model state, and whether captions are on.

### Opening the main UI

The page is served by the monitor. If the monitor is stopped, `Open main UI` starts it
first, waits for the API, then opens the browser. If startup fails, the user gets a
tray notification instead of a dead browser tab.

### First run and error recovery

On controller start, if any of these are true, open the main UI automatically:

- `config.toml` is missing or has no device selected.
- The first model load has no weights and no model path.
- The monitor reports `capture_error` or `model_state == error`.

The page can then show the device list or the model loader. A tray notification says
what needs attention. This is the only time the dashboard opens without the user
asking.

### Start sequence

1. User chooses Start from the tray menu, double-clicks the pill while stopped, or
   the controller is launched at login with autostart enabled.
2. The controller starts the monitor as a hidden child process using the project
   virtual environment and the saved `config.toml`.
3. The controller waits for `http://127.0.0.1:<port>/api/state` and changes the icon
   from amber to green when capturing and the model is ready.
4. Captions follow the saved `cc/config.json` enabled flag. If they were on, the
   companion appears; if not, the monitor runs without captions.
5. The dashboard is not opened automatically, except for the first-run/error cases.

If startup fails (missing environment, port in use, monitor exits), the icon returns
to stopped and a tray notification points at `monitor.log`.

### Stop sequence

1. User chooses Stop or Quit.
2. The controller posts to the local `/api/quit` endpoint so the monitor can stop its
   threads and the caption companion cleanly.
3. If the process does not exit within five seconds, the controller terminates its
   process tree.
4. The tray icon returns to stopped and the pill waveform goes flat and grey.

The existing `stop.bat` / `stop.ps1` remains a command-line fallback and also stops
the controller.

### Restart

`Restart monitor` performs Stop then Start with the saved configuration. It is the
recovery action after a device change, crash, or port adjustment.

### Floating pill (optional)

Setting: `Show waveform`, a checkable tray item. Default off. The setting and the
saved position live in `desktop.json`.

When enabled, a small always-on-top, taskbar-less pill sits on the desktop:

- Left: status shape (green circle, amber diamond, red square, grey ring).
- Right: five waveform bars driven by the monitor's live `rms`/`db`.
- Silence: flat short bars. Sound: bars rise and fall with the input.
- Stopped or not capturing: flat, dim bars.
- Drag anywhere to move; the position is saved and clamped to the visible screen.
- Hover expands the pill to reveal three small buttons: Open UI, Captions on/off,
  and Stop. When stopped, Stop is hidden and double-clicking the pill starts the
  monitor.
- Hovering does not steal keyboard focus.

The waveform is a level history, not a raw-sample oscilloscope. No extra audio capture
is opened; it reads the same `/api/state` values the page uses.

### Caption overlay X

When the cursor is within the caption area, a small X appears at its top-right corner.
Clicking it:

1. Posts `{"enabled": false}` to the local `/api/cc`.
2. The monitor stops the companion and saves the disabled state.
3. The overlay disappears.

The X lives in `cc/companion.py`, because that process owns the real caption window,
its z-order, and its hover state. The overlay stays click-through for its text. The X
is implemented as a tiny separate top-level button window that follows the caption
rectangle, so click-through text does not become click-blocking. Captions are
re-enabled from the tray menu, the pill hover, or the main UI.

### Captions reconciliation

The monitor is authoritative for whether captions run. The controller:

- Starts the monitor, which starts the companion when `cc\config.json` is enabled.
- On adoption, if captions are enabled but the companion is not running, posts
  `{"enabled": true}` once to reconcile.
- On stop, waits for the companion to exit; any orphan `cc\companion.py` whose command
  line points at this install is swept.
- Shows captions state in the tray tooltip and pill hover.
- A companion launched directly by `cc\run.bat` keeps its own tray icon for standalone
  use; a monitor-spawned companion runs in managed mode and hides its tray icon.

### Captions while stopped

The tray Captions item stays enabled while the monitor is stopped. It edits the
validated `cc\config.json` so the next start honors the choice. While the monitor is
running it uses `/api/cc`, which remains authoritative.

### Source, task, and language shortcuts

The tray Source submenu writes `source_mode` through `/api/settings` while the monitor
is running, or updates `config.toml` while stopped. The Task submenu does the same for
`transcribe`/`translate`. Language stays in the main UI to avoid a long tray menu.

### Start with Windows

Checkable tray item, default off. The label is **Start with Windows (and begin
listening)** so the behavior is explicit. It writes or removes a per-user startup
entry that launches the controller. When enabled, the controller starts at login and
starts the monitor with the saved configuration, so the tray icon comes up green and
captions follow `cc\config.json`. When disabled, nothing starts at login; launching
the controller by hand starts the monitor.

The installer offers to enable it.

### Port collision

The controller reads `host` and `port` from `config.toml`. If the monitor cannot bind
because the port is in use, the controller shows a dialog with the current port and a
field for a new one. On submit it writes `config.toml`, rewrites `monitor_url` in
`cc\config.json`, and starts again. It does not silently pick a random port.

### Tray overflow

Windows 11 hides new tray icons by default. On first run the controller shows a
notification: `Audio Monitor is running in the tray. Pin it to keep it visible.` If
the floating pill is enabled, it provides a visible fallback.

### Ownership and reconciliation

The controller can be launched when a monitor is already running from `run.bat` or
`start.ps1`.

- If the API answers and `monitor.pid` belongs to a process whose command line points
  at this install root, the controller **adopts** that monitor: it shows green/amber
  from the live state and controls it through `/api/quit`.
- If the API answers but the process is not from this install, the controller leaves
  it alone, shows a warning, and does not kill it.
- If no API answers and a stale `monitor.pid` remains, the controller clears it before
  starting.
- The controller also sweeps orphan `cc\companion.py --managed` processes whose command
  line points at this install. A companion launched directly by `cc\run.bat` lacks the
  managed flag and is left alone, so its own tray icon keeps working for standalone use.

Adoption uses the same `monitor.pid` plus command-line scoping as `stop.ps1`, so the
controller has a fallback tree-kill target if `/api/quit` times out.

### Port and URL resolution

The controller reads `host` and `port` from `config.toml` before starting. It watches
`127.0.0.1` when the host is loopback or a wildcard bind, and the configured address
otherwise. Before starting the monitor it rewrites `monitor_url` in `cc\config.json`
to the same origin, so the companion and controller never disagree about the port.

## Architecture

### New package: `desktop/`

- `desktop/__init__.py`
- `desktop/__main__.py` - entry point for `pythonw -m desktop` and PyInstaller.
- `desktop/controller.py` - tray icon, menu, process lifecycle, state polling.
- `desktop/pill.py` - floating status/waveform widget.
- `desktop/settings.py` - `desktop.json` load/save, startup entry, position clamping.
- `desktop/runner.py` - start/stop/adopt child process, DLL environment, `/api/quit`.
- `desktop/tray_icon.py` - generated QIcons and state shapes/colors.
- `desktop/first_run.py` - first-run detection and open-UI behavior.

Keep GUI code free of monitor internals. The controller talks to the monitor only via
the local HTTP API and its child process handle.

### Monitor changes

- Add `POST /api/quit` to `monitor/server.py`. It requires the existing JSON/Origin
  guard, accepts only loopback clients, returns `{"ok": true}`, then shuts the HTTP
  server down on a helper thread. `monitor.__main__` already stops the engine and
  captions in its `finally` block.
- Add a source/task shortcut through the existing `/api/settings`; no new endpoint.
- No new network binding.

### Child process

- Use `<root>\.venv\Scripts\pythonw.exe -m monitor run --config <root>\config.toml`.
- Set `cwd` to the install root. Prepend
  `.venv\Lib\site-packages\nvidia\cublas\bin` and
  `.venv\Lib\site-packages\nvidia\cudnn\bin` to `PATH` so CTranslate2 finds the CUDA
  DLLs without `run.ps1`.
- Redirect stdout/stderr to `desktop.log`; the monitor already writes `monitor.log`.
- Use `CREATE_NO_WINDOW`.

### State and polling

- Poll `/api/state` every 500 ms for tray state, and every 100 ms while the pill is
  visible for the waveform.
- Use `capturing`, `rms`, `db`, `vad`, `model_state`, `model_error`, and `cc` from the
  response.
- Exponential smoothing on the bar heights so they do not flicker.

### Settings

`desktop.json` beside `config.toml`:

```json
{
  "show_pill": false,
  "pill_x": null,
  "pill_y": null,
  "start_with_windows": false
}
```

- Ignored by git.
- Corrupt or missing file falls back to defaults.
- Position is saved on drag release; if the saved position is off-screen, snap it
  back to the nearest visible edge.

### Startup entry

Use `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value
`AgenticAudioMonitor`. The command is the frozen executable when packaged, otherwise
the venv `pythonw.exe -m desktop` with the project root as the working directory.
Removing the check removes the value.

### Single instance

A named mutex or lock file in the install root prevents two controllers. A second
launch opens the main UI and exits.

### Packaging

- Build `AudioMonitor.exe` with PyInstaller, `--noconsole`, one file, PySide6 only.
  The exe is the controller; it starts the installed `.venv` monitor.
- The installer bundles the official Python 3.12 x64 installer. If a supported
  Python 3.11-3.13 is already present, it uses that instead. It then runs the existing
  requirements install and creates `.venv`.
- Provide an installer script (Inno Setup preferred, PowerShell fallback) that runs
  setup, copies the exe, creates desktop and Start-menu shortcuts, and optionally
  enables Start with Windows.
- The uninstaller removes the Run entry, shortcuts, the controller exe, `.venv`, and
  optionally logs/clips/config/models.
- Full bundling of CUDA, faster-whisper, and weights is out of scope.

### Launchers

- `Audio Monitor.bat` becomes a visible shortcut to the controller, or the packaged
  exe directly. It must not open a console window.
- `run.bat` stays as the direct, console-visible monitor for debugging.
- `stop.ps1` also matches the controller process.
- `agentic-audio-monitor.bat start|stop|restart|status` operates on the controller.

## Failure handling

- Missing `.venv` or `pythonw.exe`: tray notification with the install command; no
  silent failure.
- Port already in use: show the change-port dialog, write config, rewrite the
  companion URL, retry.
- Monitor exits unexpectedly: icon returns to stopped; tooltip reports the last error;
  pill goes flat; Restart is one click.
- `/api/quit` unreachable: terminate the child process tree and report that fallback.
- Caption X HTTP failure: hide the X and leave the overlay running; tray menu remains
  available.
- Caption companion crash with `enabled: true`: reconcile on controller start or show
  a tray warning.
- Off-screen pill position: clamp to the nearest screen.
- Foreign process on the port: warn, do not kill, leave the controller stopped.

## Testing

Automated, hardware-independent:

- `/api/quit` returns 200 for loopback JSON and rejects non-loopback, non-JSON, and
  foreign-origin requests.
- `desktop.settings` round-trips, rejects corrupt JSON, and clamps positions.
- Waveform mapping: silence is flat, loud input is tall, stopped is flat.
- Tray state mapping: stopped/starting/loading/running/error shapes and labels.
- Source/task menu actions write the right setting while running and while stopped.
- First-run detection opens the UI when config is missing or no device is selected.
- Captions X helper posts the correct JSON body to `/api/cc`.
- Captions reconciliation starts/leaves/stops the companion in the right cases.
- Existing monitor and companion suites stay green.
- PowerShell entry points parse.

Manual verification on Windows:

- Start from tray: no console, no dashboard, captions follow saved state.
- Open UI while stopped: monitor starts, then the page opens.
- Stop from tray: monitor and captions both end; no orphan overlay.
- Optional pill: drag, restart, position restored; waveform reacts to system audio.
- Caption hover X disables captions and leaves the monitor running.
- Source/task submenus change behavior without opening the dashboard.
- Port collision dialog recovers with a new port.
- Start with Windows adds/removes the Run entry and starts listening at logon.
- Uninstall removes the Run entry, shortcuts, controller, and optional data.

## Risks

- Click-through caption overlay plus hover X. Separate top-level X window avoids
  making the text block clicks; DPI and z-order need manual checks.
- `pythonw` hides early crashes. Redirect stderr and show a tray notification.
- Windows may hide new tray icons in the overflow area. First-run notification and the
  optional pill mitigate this.
- Unsigned executables may trigger SmartScreen. Code signing is out of scope.
- Two monitor instances or a stale `monitor.pid`: adoption check and process scoping.
- A bundled Python installer may be blocked by policy on managed machines. The
  installer must offer a clear fallback and an existing-Python path.
- `/api/quit` is powerful. Loopback-only plus the existing JSON/Origin guard is the
  accepted local threat model.

## Decisions made here

- Tray icon is the primary control; the pill is optional and off by default.
- Green means capturing and model ready; amber means starting/loading; red means the
  monitor is up but capture or model load failed; shapes differ as well as colors.
- The pill shows a level-history waveform, not raw audio.
- Quit stops the monitor and exits; closing the main UI does not.
- A monitor already running from this install is adopted rather than refused; a
  foreign process on the port is never killed.
- The caption X lives in `cc/companion.py`; the monitor-spawned companion hides its
  own tray icon.
- The Captions tray item works while stopped by editing `cc/config.json`.
- The controller resolves the monitor URL from `config.toml` and rewrites the
  companion's `monitor_url` before starting.
- Start with Windows defaults off and also begins listening.
- Source and task are available from the tray; language stays in the main UI.
- The installer bundles the official Python 3.12 installer and falls back to an
  existing supported Python.
- Packaging uses PyInstaller for the controller only, with the existing virtual
  environment for the monitor.

## Open for the builder

- Exact Qt painting and hover timing for the pill. The X placement and hover window
  are companion-side.
- Whether to use `/api/live` SSE instead of polling for the waveform if polling is
  too coarse.
- Inno Setup versus PowerShell installer implementation.
- Icon artwork.
