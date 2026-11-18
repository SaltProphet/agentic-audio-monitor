# Desktop Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `.bat` start/stop ritual with a tray controller, an optional floating waveform pill, a hover X on the captions, and an installable Windows package.

**Architecture:** A new PySide6 `desktop` package runs as a tray application. It starts and stops the existing monitor as a hidden `pythonw` child, polls the local HTTP API, and owns the optional pill. The monitor gains a loopback-only `/api/quit`; the caption companion gains a hover X and a managed mode. Packaging is a PyInstaller controller plus an installer that sets up Python and the existing environment.

**Tech Stack:** Python 3.11-3.13, PySide6 6.x, stdlib HTTP/urllib, `tomllib`, PyInstaller, Inno Setup or a PowerShell installer.

**Spec:** `docs/superpowers/specs/2026-11-18-desktop-controller-design.md`

## Global Constraints

- Windows only. The target is Windows 10/11; the existing app already requires Windows for WASAPI and MMCSS behavior.
- Python 3.11, 3.12, or 3.13. The current `.venv` is Python 3.12.
- Use the existing `PySide6>=6.7,<7` dependency. Do not add a new GUI toolkit.
- The monitor stays localhost-only. Do not add a cloud client, account, or remote URL.
- All normal launches are hidden: no console window and no automatic dashboard.
- Keep `config.toml` and `cc\config.json` backward compatible. `desktop.json` is new and git-ignored.
- Tests use `python -m unittest`; run from the repo with `.venv\Scripts\python.exe`.
- Monitor suite: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
- Companion suite: `.venv\Scripts\python.exe -m unittest discover -s cc -p "test_*.py" -v`
- Lint: `uvx ruff check .`
- Target version: `0.3.0`.
- Pure desktop modules (`settings`, `startup`, `runner`, `state`, `waveform`, `policy`, `captions`) must import without PySide6 so CI can test them on a bare Python.

## Review Focus

1. A monitor is already running, or a foreign process owns the port: the controller must adopt its own monitor, warn on a foreign one, and never kill the foreign process.
2. The configured `host`/`port` changes: the controller must watch the right URL and rewrite the companion's `monitor_url` before starting.
3. The caption overlay is click-through: the hover X must remain clickable without making the caption text block desktop clicks.
4. First run has no device and no model: the controller must open the UI or notify instead of showing a green icon over silence.
5. Autostart at logon and tray overflow: the user must not get surprise audio capture or an invisible icon.

---

### Task 1: Loopback-only quit endpoint

**Files:**
- Modify: `monitor/server.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `Engine.stop_event` and `MonitorServer.shutdown`.
- Produces: module-level `is_loopback(host: str) -> bool`; `POST /api/quit` returns `{"ok": true}` and shuts the server down.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_monitor.py` (extend the existing `monitor.server` import with `is_loopback`):

```python
from monitor.server import MonitorServer, is_loopbackdef test_is_loopback_accepts_local_addresses_only(self):
    self.assertTrue(is_loopback("127.0.0.1"))
    self.assertTrue(is_loopback("::1"))
    self.assertTrue(is_loopback("::ffff:127.0.0.1"))
    self.assertFalse(is_loopback("192.168.1.20"))

def test_quit_is_rejected_for_non_loopback_clients(self):
    with patch("monitor.server.is_loopback", return_value=False):
        code, payload = self._post("/api/quit", {})
    self.assertEqual(code, 403)
    self.assertFalse(payload["ok"])
    self.assertTrue(self.thread.is_alive())

def test_quit_stops_the_server(self):
    code, payload = self._post("/api/quit", {})
    self.assertEqual(code, 200)
    self.assertTrue(payload["ok"])
    self.thread.join(2)
    self.assertFalse(self.thread.is_alive())
```

Change `tearDown` so it only shuts down a live thread:

```python
if self.thread.is_alive():
    self.httpd.shutdown()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_monitor.py" -v -k quit`
Expected: FAIL with `ImportError: cannot import name 'is_loopback'` and a 404 for `/api/quit`.

- [ ] **Step 3: Implement `is_loopback` and the quit route**

In `monitor/server.py` add `import threading`, then:

```python
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}

def is_loopback(host: str) -> bool:
    return host in _LOOPBACK_HOSTS
```

In `_handle_post`, after the JSON payload is read:

```python
if path == "/api/quit":
    if not is_loopback(self.client_address[0]):
        self._json(403, {"error": "Quit is only allowed from this machine."})
        return
    self._json(200, {"ok": True})
    self.server.engine.stop_event.set()
    threading.Thread(target=self.server.shutdown, daemon=True).start()
    return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_monitor.py" -v -k quit`
Expected: PASS.

- [ ] **Step 5: Run the full monitor suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add monitor/server.py tests/test_monitor.py
git commit -m "feat: add loopback-only quit endpoint"
```

---

### Task 2: Desktop settings and startup registration

**Files:**
- Create: `desktop/__init__.py`
- Create: `desktop/settings.py`
- Create: `desktop/startup.py`
- Test: `tests/test_desktop_settings.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `DesktopSettings`, `settings_path(root)`, `load_settings(root)`, `save_settings(root, settings)`, `clamp_position(...)`, `update_config_value(config_path, key, value)`.
- Produces: `startup_command(root, frozen=False)`, `is_startup_enabled()`, `set_startup(enabled, command)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_desktop_settings.py` with tests for:

```python
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from desktop.settings import DesktopSettings, clamp_position, load_settings, save_settings, settings_path, update_config_value
from desktop.startup import set_startup, startup_command

def test_settings_round_trip_and_corrupt_fallback(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_settings(root, DesktopSettings(show_pill=True, pill_x=40, pill_y=80, start_with_windows=True))
        self.assertEqual(load_settings(root), DesktopSettings(True, 40, 80, True))
        settings_path(root).write_text("{not json", encoding="utf-8")
        self.assertEqual(load_settings(root), DesktopSettings())

def test_clamp_position_keeps_the_pill_on_screen(self):
    screens = [(0, 0, 1920, 1080)]
    self.assertEqual(clamp_position(2500, 1300, 140, 40, screens), (1780, 1040))
    self.assertEqual(clamp_position(-50, -20, 140, 40, screens), (0, 0))

def test_update_config_value_preserves_other_lines(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text('host = "127.0.0.1"\nsource_mode = "external"\nport = 8765\n', encoding="utf-8")
        update_config_value(path, "source_mode", "system")
        text = path.read_text(encoding="utf-8")
        self.assertIn('source_mode = "system"', text)
        self.assertIn('host = "127.0.0.1"', text)

def test_startup_command_uses_pythonw_and_autostart(self):
    root = Path(r"C:\Apps\Audio Monitor")
    expected = subprocess.list2cmdline([str(root / ".venv" / "Scripts" / "pythonw.exe"), "-m", "desktop", "--autostart"])
    self.assertEqual(startup_command(root), expected)

def test_startup_command_uses_the_frozen_executable(self):
    with patch("desktop.startup.sys.executable", r"C:\Apps\AudioMonitor.exe"):
        expected = subprocess.list2cmdline([r"C:\Apps\AudioMonitor.exe", "--autostart"])
        self.assertEqual(startup_command(Path("."), frozen=True), expected)

def test_set_startup_writes_and_deletes(self):
    with patch("desktop.startup._set_value") as set_value, patch("desktop.startup._delete_value") as delete_value:
        set_startup(True, "cmd")
        set_value.assert_called_once_with("cmd")
        set_startup(False, "cmd")
        delete_value.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_settings.py" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'desktop'`.

- [ ] **Step 3: Implement `desktop/settings.py`**

```python
@dataclass
class DesktopSettings:
    show_pill: bool = False
    pill_x: int | None = None
    pill_y: int | None = None
    start_with_windows: bool = False

def settings_path(root: Path) -> Path: return Path(root) / "desktop.json"
def load_settings(root: Path) -> DesktopSettings: ...
def save_settings(root: Path, settings: DesktopSettings) -> None: ...
def clamp_position(x: int, y: int, width: int, height: int, screens: list[tuple[int, int, int, int]]) -> tuple[int, int]: ...
def update_config_value(config_path: Path, key: str, value: str) -> None: ...
```

Rules:
- `load_settings` accepts only bool for `show_pill`/`start_with_windows`; only int or None for `pill_x`/`pill_y`; otherwise defaults.
- `save_settings` writes with `indent=2`, a trailing newline, and `Path.replace` from a `.tmp` sibling.
- `clamp_position` chooses the screen with the largest overlap with the pill rectangle, then clamps into that screen. If no screen overlaps, clamp to the nearest screen edge.
- `update_config_value` allows only `source_mode` and `task`; replaces the matching `key = ...` line with a JSON-quoted string and preserves everything else.

- [ ] **Step 4: Implement `desktop/startup.py`**

```python
VALUE_NAME = "AgenticAudioMonitor"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def startup_command(root: Path, frozen: bool = False) -> str: ...
def is_startup_enabled() -> bool: ...
def set_startup(enabled: bool, command: str) -> None: ...
```

- `startup_command`: frozen uses `sys.executable`; otherwise `root\.venv\Scripts\pythonw.exe`. Use `subprocess.list2cmdline([...])`.
- Use `winreg` only when `sys.platform == "win32"`; otherwise return `False`/no-op.
- Keep `_read_value`, `_set_value`, `_delete_value` as separate functions so tests can patch them.

- [ ] **Step 5: Add `desktop.json` and `desktop.pid` to `.gitignore`**

Add:

```
desktop.json
desktop.pid
desktop.log
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_settings.py" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add desktop tests/test_desktop_settings.py .gitignore
git commit -m "feat: add desktop settings and startup helpers"
```

---

### Task 3: Monitor address and companion URL helpers

**Files:**
- Create: `desktop/runner.py`
- Test: `tests/test_desktop_runner.py`

**Interfaces:**
- Produces: `Address`, `read_address(config_path)`, `watch_host(host)`, `write_port(config_path, port)`, `ensure_companion_url(root, address)`, `read_state(address, timeout=1.5)`, `post_json(url, payload, timeout=5.0)`, `is_loopback(host)`.
- Produces: `Address.state_url`, `Address.cc_url`, `Address.quit_url`, `Address.settings_url`.
- Consumes: `config.toml` and `cc\config.json` formats from the existing project.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_desktop_runner.py` with tests for:

```python
import json
import tempfile
from pathlib import Path

from desktop.runner import Address, ensure_companion_url, is_loopback, read_address, watch_host, write_port

def test_read_address_uses_config_host_and_port(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text('host = "127.0.0.1"\nport = 9001\n', encoding="utf-8")
        address = read_address(path)
        self.assertEqual((address.host, address.port), ("127.0.0.1", 9001))
        self.assertEqual(address.state_url, "http://127.0.0.1:9001/api/state")

def test_wildcard_bind_is_watched_on_loopback(self):
    self.assertEqual(watch_host("0.0.0.0"), "127.0.0.1")
    self.assertEqual(watch_host("::"), "127.0.0.1")
    self.assertEqual(watch_host("127.0.0.1"), "127.0.0.1")

def test_write_port_preserves_other_config_lines(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text('host = "127.0.0.1"\nport = 8765\nmodel = "small"\n', encoding="utf-8")
        write_port(path, 9010)
        self.assertIn("port = 9010", path.read_text(encoding="utf-8"))
        self.assertIn('model = "small"', path.read_text(encoding="utf-8"))

def test_ensure_companion_url_rewrites_only_the_url(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "cc").mkdir()
        (root / "cc" / "config.json").write_text('{"enabled": true, "font_size": 34}', encoding="utf-8")
        ensure_companion_url(root, Address("127.0.0.1", 9010))
        data = json.loads((root / "cc" / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(data["enabled"])
        self.assertEqual(data["font_size"], 34)
        self.assertEqual(data["monitor_url"], "http://127.0.0.1:9010/api/state")

def test_loopback_detection(self):
    self.assertTrue(is_loopback("127.0.0.1"))
    self.assertTrue(is_loopback("::1"))
    self.assertFalse(is_loopback("10.0.0.5"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_runner.py" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'desktop.runner'`.

- [ ] **Step 3: Implement the address and URL helpers**

In `desktop/runner.py`:

```python
@dataclass(frozen=True)
class Address:
    host: str
    port: int

    @property
    def base_url(self) -> str: return f"http://{self.host}:{self.port}"
    @property
    def state_url(self) -> str: return f"{self.base_url}/api/state"
    @property
    def cc_url(self) -> str: return f"{self.base_url}/api/cc"
    @property
    def settings_url(self) -> str: return f"{self.base_url}/api/settings"
    @property
    def quit_url(self) -> str: return f"{self.base_url}/api/quit"

def read_address(config_path: Path) -> Address: ...
def watch_host(host: str) -> str: ...
def write_port(config_path: Path, port: int) -> None: ...
def ensure_companion_url(root: Path, address: Address) -> None: ...
def read_state(address: Address, timeout: float = 1.5) -> dict | None: ...
def post_json(url: str, payload: dict, timeout: float = 5.0) -> dict | None: ...
def is_loopback(host: str) -> bool: ...
```

Rules:
- `read_address` uses `tomllib`, defaults `("127.0.0.1", 8765)`, validates port range 1..65535.
- `watch_host` maps `0.0.0.0` and `::` to `127.0.0.1`; leave other hosts.
- `write_port` uses a regex replacing the `port = ...` line; do not rewrite the file from `tomllib`.
- `ensure_companion_url` preserves every existing key and writes indent 2 plus newline.
- `post_json` sends `Content-Type: application/json`, catches `OSError`, `ValueError`, and `urllib.error.URLError`, and returns a dict or None.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_runner.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/runner.py tests/test_desktop_runner.py
git commit -m "feat: add monitor address and companion URL helpers"
```

---

### Task 4: Monitor runner: start, adopt, stop, restart

**Files:**
- Modify: `desktop/runner.py`
- Test: `tests/test_desktop_runner.py`

**Interfaces:**
- Produces:

```python
class MonitorRunner:
    def __init__(self, root: Path, popen=subprocess.Popen, state_reader=read_state, sleep=time.sleep): ...
    @property
    def address(self) -> Address: ...
    @property
    def running(self) -> bool: ...
    def start(self, timeout: float = 30.0) -> tuple[bool, str]: ...
    def stop(self, timeout: float = 5.0) -> tuple[bool, str]: ...
    def restart(self, timeout: float = 30.0) -> tuple[bool, str]: ...

def pid_alive(pid: int) -> bool: ...
def process_matches(pid: int, root: Path) -> bool: ...
def companion_pids(root: Path) -> list[int]: ...
```

- [ ] **Step 1: Write the failing tests**

Add tests using a fake `popen`, a scripted `state_reader`, and no-op `sleep`:

```python
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from desktop.runner import MonitorRunner, companion_pids, process_matches

class FakeChild:
    def __init__(self, pid=1234, poll_value=None):
        self.pid = pid
        self.poll_value = poll_value
        self.terminated = False
    def poll(self): return self.poll_value
    def terminate(self): self.terminated = True
    def wait(self, timeout=None): return self.poll_value

def test_start_adopts_an_existing_monitor(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.toml").write_text('host = "127.0.0.1"\nport = 8765\n', encoding="utf-8")
        (root / "monitor.pid").write_text("4242", encoding="utf-8")
        calls = []
        runner = MonitorRunner(root, popen=lambda *a, **k: calls.append(a), state_reader=lambda address, timeout=1.5: {"capturing": True}, sleep=lambda _: None)
        with patch("desktop.runner.pid_alive", return_value=True), patch("desktop.runner.process_matches", return_value=True):
            ok, message = runner.start()
        self.assertTrue(ok)
        self.assertTrue(runner.adopted)
        self.assertEqual(calls, [])

def test_start_refuses_a_foreign_service(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.toml").write_text('host = "127.0.0.1"\nport = 8765\n', encoding="utf-8")
        (root / "monitor.pid").write_text("4242", encoding="utf-8")
        runner = MonitorRunner(root, popen=lambda *a, **k: None, state_reader=lambda address, timeout=1.5: {"capturing": True}, sleep=lambda _: None)
        with patch("desktop.runner.process_matches", return_value=False):
            ok, message = runner.start()
        self.assertFalse(ok)
        self.assertIn("port", message.lower())

def test_start_launches_hidden_child(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.toml").write_text('host = "127.0.0.1"\nport = 8765\n', encoding="utf-8")
        (root / ".venv" / "Scripts").mkdir(parents=True)
        (root / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
        for name in ("cublas", "cudnn"):
            (root / ".venv" / "Lib" / "site-packages" / "nvidia" / name / "bin").mkdir(parents=True)
        child = FakeChild(pid=1234)
        calls = []
        states = iter([None, {"capturing": True}])
        runner = MonitorRunner(
            root,
            popen=lambda command, **kwargs: calls.append((command, kwargs)) or child,
            state_reader=lambda address, timeout=1.5: next(states, {"capturing": True}),
            sleep=lambda _: None,
        )
        with patch("desktop.runner.companion_pids", return_value=[]):
            ok, message = runner.start()
        self.assertTrue(ok, message)
        self.assertEqual(runner.pid, 1234)
        command, kwargs = calls[0]
        self.assertEqual(command[1:4], ["-m", "monitor", "run"])
        self.assertIn("cublas", kwargs["env"]["PATH"])
        self.assertIsNotNone(kwargs["stdout"])

def test_start_reports_a_child_that_exits(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.toml").write_text('host = "127.0.0.1"\nport = 8765\n', encoding="utf-8")
        (root / ".venv" / "Scripts").mkdir(parents=True)
        (root / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
        child = FakeChild(pid=1234, poll_value=1)
        runner = MonitorRunner(root, popen=lambda *a, **k: child, state_reader=lambda address, timeout=1.5: None, sleep=lambda _: None)
        with patch("desktop.runner.companion_pids", return_value=[]):
            ok, message = runner.start()
        self.assertFalse(ok)
        self.assertTrue("1" in message or "log" in message.lower())

def test_process_matches_reads_the_command_line(self):
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=r"C:\Apps\Audio Monitor\.venv\Scripts\python.exe -m monitor run")
    with patch("desktop.runner.subprocess.run", return_value=completed):
        self.assertTrue(process_matches(4242, Path(r"C:\Apps\Audio Monitor")))
        self.assertFalse(process_matches(4242, Path(r"C:\Other")))

def test_companion_pids_parses_powershell_output(self):
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="111\n222\n")
    with patch("desktop.runner.subprocess.run", return_value=completed), patch("desktop.runner.sys.platform", "win32"):
        self.assertEqual(companion_pids(Path(r"C:\Apps\Audio Monitor")), [111, 222])

def test_stop_posts_quit_and_removes_pid(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.toml").write_text('host = "127.0.0.1"\nport = 8765\n', encoding="utf-8")
        (root / "monitor.pid").write_text("1234", encoding="utf-8")
        child = FakeChild(pid=1234, poll_value=0)
        runner = MonitorRunner(root, popen=lambda *a, **k: child, state_reader=lambda address, timeout=1.5: None, sleep=lambda _: None)
        runner.child = child
        runner.pid = 1234
        runner.adopted = True
        with patch("desktop.runner.post_json", return_value={"ok": True}) as post, patch.object(runner, "_terminate_tree") as kill:
            ok, message = runner.stop()
        self.assertTrue(ok)
        post.assert_called_once_with(runner.address.quit_url, {})
        kill.assert_not_called()
        self.assertFalse((root / "monitor.pid").exists())

def test_stop_falls_back_to_tree_kill(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.toml").write_text('host = "127.0.0.1"\nport = 8765\n', encoding="utf-8")
        (root / "monitor.pid").write_text("4242", encoding="utf-8")
        runner = MonitorRunner(root, popen=lambda *a, **k: None, state_reader=lambda address, timeout=1.5: None, sleep=lambda _: None)
        with patch("desktop.runner.post_json", return_value=None), patch("desktop.runner.pid_alive", return_value=True), patch("desktop.runner.process_matches", return_value=True), patch.object(runner, "_terminate_tree") as kill:
            ok, message = runner.stop(timeout=0.1)
        self.assertTrue(ok)
        kill.assert_called_once_with(4242)

def test_terminate_tree_uses_taskkill_on_windows(self):
    with patch("desktop.runner.sys.platform", "win32"), patch("desktop.runner.subprocess.run") as run:
        MonitorRunner(Path("."))._terminate_tree(4242)
    run.assert_called_once()
    args = run.call_args.args[0]
    self.assertEqual(args[:5], ["taskkill", "/PID", "4242", "/T", "/F"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_runner.py" -v -k start`
Expected: FAIL because `MonitorRunner` is not defined.

- [ ] **Step 3: Implement `MonitorRunner`**

Rules:
- `address` property: `return read_address(self.root / "config.toml")`, so a port change is picked up on the next start/restart.
- `start`:
  - `address = read_address(root / "config.toml")`; `ensure_companion_url(root, address)`.
  - If `state_reader(address)` returns a dict:
    - Read `monitor.pid`. If it is a positive int, `pid_alive(pid)` is true, and `process_matches(pid, root)` is true, adopt: set `pid`, `adopted=True`, return `True, "Already running."`.
    - Otherwise return `False, "Another service is using port <port>."`.
  - If `pythonw.exe` is missing, return `False, "Nothing is installed yet. Run setup.bat."`.
  - Open `desktop.log` in append, start `[pythonw, "-m", "monitor", "run", "--config", str(config)]` with `cwd=root`, the child environment, `stdout=log`, `stderr=STDOUT`, and `CREATE_NO_WINDOW` on Windows.
  - Poll `state_reader` and `child.poll()` until timeout. Return `True, "started"` when the state answers; return `False` with the child's exit code or a timeout message.
- `_child_env`: copy `os.environ`; prepend `root\.venv\Lib\site-packages\nvidia\cublas\bin` and `...\cudnn\bin` when they exist.
- `stop`:
  - `post_json(address.quit_url, {})`; wait up to `timeout` for the state to disappear and the child to exit.
  - If the HTTP call fails, read `monitor.pid`; if `pid_alive(pid)` and `process_matches(pid, root)`, call `_terminate_tree(pid)`.
  - Clear `child`, `adopted`, `pid`; remove `monitor.pid`.
- `_terminate_tree(pid)`: Windows `subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], ...)`; otherwise `os.kill(pid, signal.SIGTERM)`.
- `pid_alive(pid)`: Windows `OpenProcess`/`CloseHandle` via `ctypes`; otherwise `os.kill(pid, 0)`.
- `process_matches(pid, root)`: run `powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId = <pid>').CommandLine"` with a 5 s timeout; return True only when the escaped root appears in the output. Return False on any error or non-Windows platform.
- `companion_pids(root)`: query `Win32_Process` for `python.exe`/`pythonw.exe` whose command line matches `companion.py`, `--managed`, and the escaped root; parse the integer lines; return `[]` on error or non-Windows. Standalone `cc\run.bat` companions lack `--managed` and are left alone.
- `start` sweeps `companion_pids(root)` with `_terminate_tree` before launching the monitor, so a crashed previous run cannot leave an orphan overlay.
- `restart`: `stop()` then `start()`.

- [ ] **Step 4: Run the runner tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_runner.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/runner.py tests/test_desktop_runner.py
git commit -m "feat: add monitor start, adopt, and stop runner"
```

---

### Task 5: Tray state, waveform math, and first-run policy

**Files:**
- Create: `desktop/state.py`
- Create: `desktop/waveform.py`
- Create: `desktop/policy.py`
- Test: `tests/test_desktop_ui.py`

**Interfaces:**
- Produces: `MonitorState`, `state_from_payload(payload, *, starting, process_alive)`, `state_text(state)`, `state_color(state)`.
- Produces: `level_fraction(db, capturing)`, `bar_heights(db, capturing, count=5)`, `smooth(previous, target, attack=0.65, release=0.2)`.
- Produces: `first_run_needed(root)`, `first_run_action(autostart)`, `caption_action(state)`, `menu_enabled(state)`, `is_port_error(message)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_desktop_ui.py` with:

```python
import tempfile
from pathlib import Path

from desktop.policy import caption_action, first_run_action, first_run_needed, is_port_error, menu_enabled
from desktop.state import MonitorState, state_color, state_from_payload, state_text
from desktop.waveform import bar_heights, level_fraction, smooth

def test_state_mapping(self):
    self.assertEqual(state_from_payload(None, starting=True, process_alive=True), MonitorState.STARTING)
    self.assertEqual(state_from_payload(None, starting=False, process_alive=False), MonitorState.STOPPED)
    self.assertEqual(state_from_payload({"model_state": "loading", "capturing": True}, starting=False, process_alive=True), MonitorState.LOADING)
    self.assertEqual(state_from_payload({"model_state": "ready", "capturing": True}, starting=False, process_alive=True), MonitorState.RUNNING)
    self.assertEqual(state_from_payload({"model_state": "ready", "capturing": False, "capture_error": "no device"}, starting=False, process_alive=True), MonitorState.ERROR)

def test_state_text_and_color_are_distinct(self):
    self.assertEqual(state_text(MonitorState.RUNNING), "Running")
    self.assertNotEqual(state_color(MonitorState.RUNNING), state_color(MonitorState.ERROR))

def test_waveform_is_flat_at_silence_and_stopped(self):
    self.assertEqual(level_fraction(-90, True), 0.0)
    self.assertEqual(level_fraction(-30, True), 0.5)
    self.assertEqual(level_fraction(0, True), 1.0)
    self.assertEqual(level_fraction(0, False), 0.0)
    self.assertEqual(len(bar_heights(-30, True)), 5)

def test_smooth_uses_attack_and_release(self):
    self.assertGreater(smooth(0.0, 1.0, attack=0.5), 0.0)
    self.assertLess(smooth(1.0, 0.0, release=0.5), 1.0)

def test_first_run_opens_for_missing_config_or_device(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        self.assertTrue(first_run_needed(root))
        (root / "config.toml").write_text('device_name = ""\nmodel = "small"\n', encoding="utf-8")
        self.assertTrue(first_run_needed(root))
        (root / "config.toml").write_text('device_name = "Mic"\nmodel = "small"\n', encoding="utf-8")
        snap = root / "models" / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
        snap.mkdir(parents=True)
        (snap / "model.bin").write_bytes(b"x")
        self.assertFalse(first_run_needed(root))

def test_first_run_action_respects_autostart(self):
    self.assertEqual(first_run_action(autostart=False), "open")
    self.assertEqual(first_run_action(autostart=True), "notify")

def test_caption_action_and_menu_state(self):
    self.assertEqual(caption_action({"cc": {"enabled": True, "running": False}}), "start")
    self.assertEqual(caption_action({"cc": {"enabled": True, "running": True}}), "none")
    self.assertTrue(menu_enabled(MonitorState.RUNNING)["stop"])
    self.assertFalse(menu_enabled(MonitorState.STOPPED)["stop"])

def test_port_error_detection(self):
    self.assertTrue(is_port_error("Another service is using port 8765."))
    self.assertTrue(is_port_error("Could not listen on 127.0.0.1:8765: address in use"))
    self.assertFalse(is_port_error("Nothing is installed yet."))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_ui.py" -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `desktop/state.py`**

Rules:
- `MonitorState` is a `str` enum with `STOPPED`, `STARTING`, `LOADING`, `RUNNING`, `ERROR`.
- `state_from_payload`: see tests. `capture_error` or `model_state == "error"` means ERROR. `ready` + `capturing` means RUNNING. `loading`/`not_loaded` means LOADING. No payload + process alive means STARTING; no payload + no process means STOPPED.
- `state_text`: `Stopped`, `Starting`, `Loading model`, `Running`, `Error`.
- `state_color`: grey `#7a7a7a`, amber `#d9a441`, green `#35b56b`, red `#d64b4b`.

- [ ] **Step 4: Implement `desktop/waveform.py`**

Rules:
- `level_fraction`: 0 when not capturing or db is None/non-finite/<=-60; 1 at >=0; linear in between.
- `bar_heights`: multiply the fraction by `(0.45, 0.75, 1.0, 0.75, 0.45)` for five bars; repeat/trim for other counts.
- `smooth`: `previous + (target - previous) * (attack if target > previous else release)`.

- [ ] **Step 5: Implement `desktop/policy.py`**

Rules:
- `first_run_needed(root)`: True if `config.toml` is missing or has no non-empty `device_name`; also True if `model_path` is empty and the configured model's weights are not in `root/models/models--Systran--faster-whisper-<model>/snapshots/*/model.bin`.
- `first_run_action(autostart)`: `"notify"` when autostart, else `"open"`.
- `caption_action(state)`: `"start"` when `cc.enabled` and not `cc.running`; `"none"` otherwise.
- `menu_enabled(state)`: dict with `start`, `stop`, `restart`, `open` booleans. Start enabled for STOPPED/ERROR; stop enabled for any non-STOPPED state.
- `is_port_error(message)`: True when the lowercased message contains `port` and either `use` or `listen`; False otherwise.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_ui.py" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add desktop/state.py desktop/waveform.py desktop/policy.py tests/test_desktop_ui.py
git commit -m "feat: add tray state, waveform, and first-run policy"
```

---

### Task 6: Tray icons and floating waveform pill

**Files:**
- Create: `desktop/tray_icon.py`
- Create: `desktop/pill.py`
- Test: manual + import smoke check

**Interfaces:**
- Produces: `make_icon(state: MonitorState) -> QIcon`.
- Produces: `WaveformPill` with signals `open_requested`, `stop_requested`, `captions_requested`, `start_requested`, `moved(int, int)` and method `update_state(state, db, capturing, captions)`.

- [ ] **Step 1: Write the import smoke check**

Run: `.venv\Scripts\python.exe -c "import desktop.tray_icon, desktop.pill"`
Expected: FAIL because the modules do not exist.

- [ ] **Step 2: Implement `desktop/tray_icon.py`**

Rules:
- Import Qt only inside `make_icon`.
- Draw a 32×32 transparent pixmap with QPainter: grey ring, amber diamond, green circle, red square.
- Return a `QIcon` from the pixmap.

- [ ] **Step 3: Implement `desktop/pill.py`**

Rules:
- `WaveformPill` is a frameless, always-on-top, tool window with `WA_TranslucentBackground` and no focus.
- Size 140×40 collapsed, 220×40 hovered. Draw a rounded dark pill, the state shape on the left, and five bars from `bar_heights`.
- `update_state` stores `state`, `db`, `capturing`, `captions`; update the tooltip and repaint.
- `enterEvent` expands; `leaveEvent` collapses unless a child button has focus.
- Hover buttons: `Open`, `CC`, `Stop` as small `QPushButton`s. `CC` text is `CC on`/`CC off`. Hide `Stop` when stopped; show `Open` always.
- Double-click when stopped emits `start_requested`.
- Drag with left mouse; emit `moved(x, y)` on release.
- A 50 ms `QTimer` smooths each bar toward `bar_heights(db, capturing)` with `smooth`.

- [ ] **Step 4: Run the import smoke check and a static lint**

Run: `.venv\Scripts\python.exe -c "import desktop.tray_icon, desktop.pill"`
Expected: PASS.

Run: `uvx ruff check desktop`
Expected: PASS.

- [ ] **Step 5: Manual visual check**

Run: `.venv\Scripts\python.exe -c "from PySide6.QtWidgets import QApplication; from desktop.pill import WaveformPill; from desktop.state import MonitorState; app=QApplication([]); p=WaveformPill(); p.update_state(MonitorState.RUNNING, -20.0, True, True); p.show(); app.exec()"`
Expected: a small pill with a green dot and moving bars; hover shows Open/CC/Stop; dragging moves it. Close with Ctrl+C in the terminal.

- [ ] **Step 6: Commit**

```bash
git add desktop/tray_icon.py desktop/pill.py
git commit -m "feat: add tray icons and floating waveform pill"
```

---

### Task 7: Caption hover X and managed companion mode

**Files:**
- Modify: `cc/companion.py`
- Modify: `monitor/captions.py`
- Test: `cc/test_cc.py`
- Test: `tests/test_captions.py`

**Interfaces:**
- Produces: `cc_url_from_state_url(state_url)`, `disable_captions(state_url, timeout=3.0) -> bool`, `managed_mode(argv) -> bool`.
- Produces: `--managed` command-line flag on the companion.
- Consumes: `POST /api/cc` with `{"enabled": false}`.

- [ ] **Step 1: Write the failing companion tests**

Add to `cc/test_cc.py`:

```python
import json

from companion import cc_url_from_state_url, disable_captions, managed_mode

def test_cc_url_is_derived_from_state_url(self):
    self.assertEqual(cc_url_from_state_url("http://127.0.0.1:8765/api/state"), "http://127.0.0.1:8765/api/cc")

def test_managed_mode_reads_the_flag(self):
    self.assertTrue(managed_mode(["companion.py", "--managed"]))
    self.assertFalse(managed_mode(["companion.py"]))

def test_disable_captions_posts_enabled_false(self):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        body = b""
        def do_POST(self):
            Handler.body = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/state"
        self.assertTrue(disable_captions(url))
        self.assertEqual(json.loads(Handler.body.decode("utf-8")), {"enabled": False})
    finally:
        server.shutdown()
        server.server_close()
```

Add to `tests/test_captions.py`:

```python
def test_companion_is_started_in_managed_mode(self):
    with tempfile.TemporaryDirectory() as tmp:
        commands = []
        def factory(command, **kwargs):
            commands.append(command)
            return FakeProcess()
        controller = CCController(Path(tmp), process_factory=factory)
        ok, message = controller.apply({"enabled": True})
        self.assertTrue(ok, message)
        self.assertEqual(commands[0][-1], "--managed")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s cc -p "test_*.py" -v -k disable_captions`
Expected: FAIL with `ImportError`.

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_captions.py" -v -k managed`
Expected: FAIL because the command lacks `--managed`.

- [ ] **Step 3: Implement the helpers and managed flag**

In `cc/companion.py`:

```python
def cc_url_from_state_url(state_url: str) -> str:
    suffix = "/api/state"
    return state_url[: -len(suffix)] + "/api/cc" if state_url.endswith(suffix) else state_url

def disable_captions(state_url: str, timeout: float = 3.0) -> bool:
    request = urllib.request.Request(
        cc_url_from_state_url(state_url),
        data=b'{"enabled": false}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, ValueError, urllib.error.URLError):
        return False

def managed_mode(argv: list[str]) -> bool:
    return "--managed" in argv
```

In `Companion.__init__`, accept `managed: bool = False`; skip creating/showing `self.tray` when managed. In `run_app`, pass `managed=managed_mode(sys.argv)`.

In `monitor/captions.py` `_start`, append `"--managed"` to the command.

- [ ] **Step 4: Implement the hover X button**

Add `CaptionCloseButton(QWidget)`:

- Frameless, always-on-top, tool, no focus, translucent, 24×24.
- A 120 ms `QTimer` checks `QCursor.pos()` against `window.frameGeometry().adjusted(-12, -12, 12, 12)`.
- When inside, position at `window.x() + window.width() - 30`, `window.y() + 6`, show and raise; otherwise hide.
- `paintEvent` draws two white lines forming an X on a dark circle.
- `mousePressEvent` left-click calls `disable_captions(window.config["monitor_url"])`; on success `QApplication.quit()`; on failure hide the button and leave the overlay.
- Create it in `Companion.__init__` and keep a reference.

- [ ] **Step 5: Run the companion and monitor caption tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s cc -p "test_*.py" -v`
Expected: PASS.

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_captions.py" -v`
Expected: PASS.

- [ ] **Step 6: Manual check**

Start the monitor and enable captions. Hover the caption text; the X appears at the top-right. Click it; captions disappear and `cc\config.json` has `"enabled": false`. The monitor stays running.

- [ ] **Step 7: Commit**

```bash
git add cc/companion.py monitor/captions.py cc/test_cc.py tests/test_captions.py
git commit -m "feat: add caption hover close and managed companion mode"
```

---

### Task 8: Caption config and reconciliation helpers

**Files:**
- Create: `desktop/captions.py`
- Test: `tests/test_desktop_ui.py`

**Interfaces:**
- Produces: `read_cc_config(root) -> dict`, `set_cc_enabled(root, enabled) -> None`.
- Consumes: `cc\config.json` format.

- [ ] **Step 1: Write the failing tests**

```python
from desktop.captions import read_cc_config, set_cc_enabled

def test_set_cc_enabled_preserves_other_settings(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "cc").mkdir()
        (root / "cc" / "config.json").write_text('{"enabled": false, "font_size": 34}', encoding="utf-8")
        set_cc_enabled(root, True)
        data = read_cc_config(root)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["font_size"], 34)

def test_set_cc_enabled_rejects_non_boolean(self):
    with tempfile.TemporaryDirectory() as tmp:
        with self.assertRaises(ValueError):
            set_cc_enabled(Path(tmp), "yes")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_ui.py" -v -k cc`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `desktop/captions.py`**

Rules:
- `read_cc_config` returns the raw dict, or `{}` on missing/invalid JSON.
- `set_cc_enabled` requires a real `bool`; creates `cc\config.json` if missing; preserves other keys; writes indent 2 plus newline.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_ui.py" -v -k cc`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/captions.py tests/test_desktop_ui.py
git commit -m "feat: add caption config helpers"
```

---

### Task 9: Desktop controller and entry point

**Files:**
- Create: `desktop/controller.py`
- Create: `desktop/__main__.py`
- Test: `tests/test_desktop_ui.py` (pure helpers)
- Manual: tray app

**Interfaces:**
- Consumes: `MonitorRunner`, `DesktopSettings`, `WaveformPill`, `make_icon`, `policy`, `captions`, `startup`.
- Produces: `DesktopController(root, app, autostart=False, runner=None)` with `start()`.

- [ ] **Step 1: Implement `desktop/controller.py`**

Rules:
- Initialize `self.first_run_handled = False`, `self.settings = load_settings(root)`, and `self.pill = WaveformPill(self.settings)`.
- Build `QSystemTrayIcon` with `make_icon(MonitorState.STOPPED)` and the menu from the spec.
- Poll every 200 ms: `runner.address` state, update icon/tooltip/pill, update menu enabled states, reconcile captions once per state transition.
- `Start`: `runner.start()`, then if successful and `first_run_needed`, open UI or notify using `first_run_action(self.autostart)`. Set `self.first_run_handled = True` after the first successful start so the UI is not reopened on every poll.
- After the first successful start, show a tray notification: `Audio Monitor is running in the tray. Pin it to keep it visible.` This also covers Windows 11 tray overflow.
- `Stop`: `runner.stop()`.
- `Restart`: `runner.restart()`.
- `Open UI`: if stopped, start; then `webbrowser.open(address.base_url + "/")`.
- Source/Task menu: if running, `post_json(address.settings_url, {"source_mode": mode})` or `{"task": task}`; if stopped, `update_config_value`.
- Captions: if running, `post_json(address.cc_url, {"enabled": not enabled})`; if stopped, `set_cc_enabled`.
- Show waveform: toggle `settings.show_pill`, save, show/hide the pill.
- Start with Windows: toggle `settings.start_with_windows`, save, `set_startup(..., startup_command(root, frozen=...))`.
- Open log: `QDesktopServices.openUrl(QUrl.fromLocalFile(...))` for `monitor.log` or `desktop.log`; notify if missing.
- Port collision: if start fails and `is_port_error(message)`, show a `QMessageBox` with `Change port`; on accept, `QInputDialog.getInt`, `write_port`, `ensure_companion_url`, retry. For other start failures, notify with the message.
- `Quit`: `runner.stop()`, remove `desktop.pid`, `app.quit()`.
- Write `desktop.pid` on start; remove on quit.
- Reconcile: on a running state, if `caption_action(state) == "start"`, POST `{"enabled": true}` once per transition.

- [ ] **Step 2: Implement `desktop/__main__.py`**

Rules:
- `app_root()`: `Path(sys.executable).resolve().parent` when `sys.frozen`, else `Path(__file__).resolve().parents[1]`.
- Parse `--autostart`.
- Single instance with `QSharedMemory("AgenticAudioMonitor")`: if attach succeeds, open the UI if possible and exit 0; otherwise create.
- Create `QApplication`, `setQuitOnLastWindowClosed(False)`, controller, start, `app.exec()`.

- [ ] **Step 3: Run the import and pure tests**

Run: `.venv\Scripts\python.exe -c "import desktop.controller, desktop.__main__"`
Expected: PASS.

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_desktop_ui.py" -v`
Expected: PASS.

- [ ] **Step 4: Manual tray check**

Run: `.venv\Scripts\pythonw.exe -m desktop` from the repo root.
Expected: a tray icon, no console, no browser. Menu Start opens the monitor; Stop ends it and captions. Open UI starts if needed.

- [ ] **Step 5: Commit**

```bash
git add desktop/controller.py desktop/__main__.py tests/test_desktop_ui.py
git commit -m "feat: add desktop tray controller"
```

---

### Task 10: Launchers and scripts

**Files:**
- Modify: `start.ps1`
- Modify: `stop.ps1`
- Modify: `shortcut.ps1`
- Modify: `agentic-audio-monitor.bat`
- Modify: `.gitignore`
- Test: `tests/test_release.py`

**Interfaces:**
- Consumes: `desktop/__main__.py`, `desktop.pid`.
- Produces: hidden controller launch, controller-aware stop, shortcut to `pythonw -m desktop`.

- [ ] **Step 1: Write the failing contract tests**

Add to `tests/test_release.py`:

```python
def test_desktop_launchers_use_the_controller(self):
    self.assertTrue((ROOT / "desktop" / "__main__.py").is_file())
    self.assertIn("pythonw.exe", (ROOT / "start.ps1").read_text(encoding="utf-8"))
    self.assertIn("-m desktop", (ROOT / "start.ps1").read_text(encoding="utf-8"))
    self.assertIn("-m desktop", (ROOT / "stop.ps1").read_text(encoding="utf-8"))
    self.assertIn("AudioMonitor.exe", (ROOT / "stop.ps1").read_text(encoding="utf-8"))
    self.assertIn("-m desktop", (ROOT / "shortcut.ps1").read_text(encoding="utf-8"))
    self.assertIn("AudioMonitor.exe", (ROOT / "shortcut.ps1").read_text(encoding="utf-8"))
def test_desktop_runtime_files_are_ignored(self):
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in ("desktop.json", "desktop.pid", "desktop.log"):
        self.assertIn(name, text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_release.py" -v -k desktop`
Expected: FAIL because the scripts still target the old launcher.

- [ ] **Step 3: Rewrite `start.ps1`**

- If `AudioMonitor.exe` exists in the root, start it with no arguments.
- Otherwise start `.venv\Scripts\pythonw.exe -m desktop`.
- Error if neither exists.
- `Start-Process` with `-WorkingDirectory $Root -WindowStyle Hidden`.
- Do not open a console or browser.
- Write `Audio Monitor tray controller started.` and exit 0.

- [ ] **Step 4: Update `stop.ps1`**

- Add `-m desktop` to the Python process match, and match both `python.exe` and `pythonw.exe`.
- Also stop `AudioMonitor.exe` whose `ExecutablePath` is under `$Root`.
- Add a `desktop.pid` scoped kill like `monitor.pid`.
- Remove `desktop.pid`.
- Keep the existing monitor, companion, supervisor, and console cleanup.

- [ ] **Step 5: Update `shortcut.ps1`**

- If `AudioMonitor.exe` exists in the root, target it with no arguments.
- Otherwise target `$Root\.venv\Scripts\pythonw.exe` with arguments `-m desktop`.
- Working directory `$Root`.
- Window style 7 (minimized) or 1.
- Keep the same desktop and Start-menu names.

- [ ] **Step 6: Update `agentic-audio-monitor.bat`**

- `start` calls `start.bat` (controller) and prints the tray message.
- `stop` calls `stop.bat`.
- `restart` stops then starts.
- `status` checks `desktop.pid` first, then `monitor.pid`.

- [ ] **Step 7: Run the contract tests and parse the scripts**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_release.py" -v -k desktop`
Expected: PASS.

Run:

```powershell
foreach ($f in "start.ps1","stop.ps1","shortcut.ps1") {
  $errors = $null
  [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) $f), [ref]$null, [ref]$errors) | Out-Null
  if ($errors) { throw "$f has parse errors" }
}
```

Expected: no output, no errors.

- [ ] **Step 8: Manual check**

Run `.\stop.bat`, then `.\start.bat`. Expected: no console left open; the tray icon appears; `stop.bat` removes it and the monitor.

- [ ] **Step 9: Commit**

```bash
git add start.ps1 stop.ps1 shortcut.ps1 agentic-audio-monitor.bat .gitignore tests/test_release.py
git commit -m "feat: launch and stop through the desktop controller"
```

---

### Task 11: Controller executable and installer

**Files:**
- Create: `build-desktop.ps1`
- Create: `install-desktop.ps1`
- Create: `uninstall-desktop.ps1`
- Create: `installer.iss`
- Modify: `pyproject.toml`
- Test: `tests/test_release.py`

**Interfaces:**
- Produces: `dist\AudioMonitor.exe` from PyInstaller.
- Produces: an installer that copies the app, installs Python if needed, runs the existing setup, creates shortcuts, and optionally enables startup.

- [ ] **Step 1: Write the failing release tests**

```python
def test_packaging_files_exist(self):
    for name in ("build-desktop.ps1", "install-desktop.ps1", "uninstall-desktop.ps1", "installer.iss"):
        self.assertTrue((ROOT / name).is_file(), name)
    packages = pyproject()["tool"]["setuptools"]["packages"]
    self.assertIn("desktop", packages)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_release.py" -v -k packaging`
Expected: FAIL because the files do not exist.

- [ ] **Step 3: Add the build extra and package**

In `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["ruff>=0.6"]
build = ["pyinstaller>=6"]

[tool.setuptools]
packages = ["monitor", "desktop"]
```

- [ ] **Step 4: Create `build-desktop.ps1`**

Rules:
- Use `$Root\.venv\Scripts\python.exe`.
- Ensure PyInstaller is present; if not, run `& $Py -m pip install pyinstaller`.
- Run:

```powershell
& $Py -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name AudioMonitor --distpath (Join-Path $Root "dist") `
  --workpath (Join-Path $Root "build") `
  (Join-Path $Root "desktop\__main__.py")
```

- Fail if `dist\AudioMonitor.exe` is missing.
- Do not add URLs.

- [ ] **Step 5: Create `install-desktop.ps1`**

Rules:
- Parameters: `-Root` (default `$env:LOCALAPPDATA\AgenticAudioMonitor`), `-Yes`, `-NoStartup`.
- Check `py -3.12`, `py -3.11`, `py -3.13`; if none, try `winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements`; if that fails, print a clear message and exit 1.
- Copy `monitor`, `cc`, `desktop`, `docs`, `tests`, `evals`, `config.example.toml`, `requirements.txt`, `pyproject.toml`, `README.md`, `INSTALL.md`, `LICENSE`, and the PowerShell/bat launchers to `$Root`.
- Copy `dist\AudioMonitor.exe` to `$Root`.
- Run `preflight.ps1 -Install` in `$Root`.
- Run `shortcut.ps1 -Desktop -StartMenu`.
- If not `-NoStartup`, call the controller once with `--autostart`? No: startup is a setting. Print how to enable it from the tray; the installer must not silently enable autostart.
- Do not download models.

- [ ] **Step 6: Create `uninstall-desktop.ps1`**

Rules:
- Parameters: `-Yes`, `-DeleteData`, `-DeleteModels`.
- Remove the `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value `AgenticAudioMonitor`.
- Remove desktop and Start-menu `Audio Monitor.lnk`.
- Stop the controller and monitor via `stop.ps1`.
- Remove `AudioMonitor.exe`, `.venv`, and the controller files.
- With `-DeleteData`, remove logs, clips, `config.toml`, `cc\config.json`, `desktop.json`, `monitor.log`, `desktop.log`.
- With `-DeleteModels`, remove `models`.
- Print what it will remove; require `-Yes` to act.

- [ ] **Step 7: Create `installer.iss`**

Rules:
- Inno Setup script that copies `dist\AudioMonitor.exe` and the install payload to `{localappdata}\AgenticAudioMonitor`.
- `[Run]` executes `powershell -NoProfile -ExecutionPolicy Bypass -File "{app}\install-desktop.ps1" -Yes`.
- `[UninstallRun]` executes `uninstall-desktop.ps1 -Yes`.
- Create the desktop and Start-menu shortcuts.
- No URLs.

- [ ] **Step 8: Run the release tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_release.py" -v`
Expected: PASS.

- [ ] **Step 9: Build and verify the executable**

Run:

```powershell
.\build-desktop.ps1
Test-Path .\dist\AudioMonitor.exe
```

Expected: `True`. Launch the exe; a tray icon appears with no console.

- [ ] **Step 10: Build the installer**

If Inno Setup is installed:

```powershell
iscc .\installer.iss
```

Expected: an installer in `dist`. If `iscc` is not available, install Inno Setup with `winget install --id JRSoftware.InnoSetup -e --silent` and rerun. If the machine policy blocks it, stop and report; the exe and PowerShell installer still work.

- [ ] **Step 11: Commit**

```bash
git add build-desktop.ps1 install-desktop.ps1 uninstall-desktop.ps1 installer.iss pyproject.toml tests/test_release.py
git commit -m "build: add controller executable and installer"
```

---

### Task 12: Version, documentation, and full verification

**Files:**
- Modify: `monitor/__init__.py`
- Modify: `monitor/web/index.html`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `INSTALL.md`
- Modify: `docs/PROJECT_LAYOUT.md`
- Test: `tests/test_release.py` (version contract already exists)

**Interfaces:**
- Produces: version `0.3.0` consistent in code, page, metadata, and changelog.

- [ ] **Step 1: Bump the version**

Set `__version__ = "0.3.0"` in `monitor/__init__.py`, `version = "0.3.0"` in `pyproject.toml`, and `Version 0.3.0` in `monitor/web/index.html`.

- [ ] **Step 2: Add the changelog section**

```markdown
## 0.3.0

- Add a system tray controller with Start, Stop, Restart, source/task shortcuts, captions, and Start with Windows.
- Start hidden with the saved configuration; open the dashboard only on request or first run.
- Add an optional floating status pill with a live waveform.
- Add a hover X to the caption overlay.
- Add a loopback-only `/api/quit` and clean monitor/caption shutdown.
- Add a controller executable build and installer.
```

- [ ] **Step 3: Update the user docs**

- README: replace the `.bat` start/stop instructions with the tray icon, the pill, the caption X, and the autostart setting.
- INSTALL: add the installer path and the "start from the tray" first-run flow.
- PROJECT_LAYOUT: add `desktop\`, `build-desktop.ps1`, `install-desktop.ps1`, `installer.iss`, `desktop.json`.
- Keep the existing troubleshooting and privacy sections.

- [ ] **Step 4: Run the full suites**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
Expected: all monitor tests pass.

Run: `.venv\Scripts\python.exe -m unittest discover -s cc -p "test_*.py" -v`
Expected: all companion tests pass.

Run: `uvx ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Run the manual acceptance checklist**

- Start from the tray: no console, no dashboard, captions follow saved state.
- Open UI while stopped: the monitor starts, then the page opens.
- Stop from the tray: monitor and captions both end; no orphan overlay.
- Restart after a device change: one click.
- Source and Task tray submenus change behavior without opening the dashboard.
- Optional pill: drag, restart, position restored; waveform reacts to audio; hover buttons work.
- Caption hover X disables captions; the monitor stays running.
- Start with Windows: enable, reboot or sign out/in, confirm the tray icon and listening start; disable and confirm it stops.
- Port collision: occupy 8765, start, use the change-port dialog, confirm the page and captions use the new port.
- Uninstall: removes the startup entry, shortcuts, controller, and optionally data/models.

- [ ] **Step 6: Commit**

```bash
git add monitor/__init__.py monitor/web/index.html CHANGELOG.md README.md INSTALL.md docs/PROJECT_LAYOUT.md
git commit -m "docs: release 0.3.0 desktop controller"
```

---

## Self-Review

**Spec coverage:** Every section of the spec maps to a task: tray states/menu (Tasks 5, 9), start/stop/restart (Task 4, 9), first run (Task 5, 9), pill (Tasks 5, 6), caption X (Task 7), captions reconciliation (Tasks 7, 8, 9), source/task (Tasks 3, 9), autostart (Tasks 2, 9), port collision (Tasks 3, 9), tray overflow (Task 9), quit endpoint (Task 1), packaging (Task 11), docs/version (Task 12).

**Type consistency:** `Address.state_url`/`cc_url`/`quit_url`, `MonitorState`, `DesktopSettings`, `MonitorRunner.start/stop/restart`, `WaveformPill.update_state`, `state_from_payload`, and `caption_action` are defined once and reused by name.

**Review Focus coverage:** Adoption/foreign port in Task 4; host/port and companion URL in Task 3; click-through X in Task 7; first run in Task 5/9; autostart/overflow in Tasks 2/9/10.

**Proportion:** The plan is longer than the spec because it spans a new GUI package, process lifecycle, two existing processes, packaging, and installer work. Code bodies are limited to signatures, rules, and failing-test assertions.
