"""Run the monitor, or print the real input-device list."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .config import ensure_config
from .devices import list_inputs
from .engine import Engine
from .server import serve
from .transcribe import apply_privacy_env


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(prog="monitor")
    sub = parser.add_subparsers(dest="cmd", required=True)
    devices = sub.add_parser("devices", help="print input devices and exit")
    run = sub.add_parser("run", help="listen, transcribe, and serve the local page")
    for item in (devices, run):
        item.add_argument("--config", default="config.toml")
    run.add_argument("--host", default=None)
    run.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    if args.cmd == "devices":
        return cmd_devices()
    return cmd_run(args)


def cmd_devices() -> int:
    try:
        rows = list_inputs()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not rows:
        print("No input devices reported.")
        return 0
    for row in rows:
        mark = " default" if row["is_default"] else ""
        print(
            f"{row['index']}\t{row['name']}\t{row['hostapi']}\t{row['default_samplerate']:.0f} Hz{mark}"
        )
    return 0


def cmd_run(args) -> int:
    path = Path(args.config).resolve()
    cfg = ensure_config(path)
    apply_privacy_env(cfg.offline)
    bind_host = args.host or cfg.host
    bind_port = cfg.port if args.port is None else args.port
    if args.host or args.port is not None:
        # CLI bind is for this process only. It is not written back to the config file.
        check = type(cfg)(**{**cfg.__dict__})
        check.flags = dict(cfg.flags)
        check.host = bind_host
        check.port = bind_port
        try:
            check.validate()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    _setup_log(path.parent)
    pid_path = path.parent / "monitor.pid"
    try:
        _acquire_pid(pid_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    engine = Engine(cfg, path)
    httpd = None
    try:
        engine.start()
        httpd = serve(engine, bind_host, bind_port)
        url_host = "127.0.0.1" if bind_host in ("0.0.0.0", "::") else bind_host
        scheme = "http" + "://"
        url = scheme + url_host + ":" + str(httpd.server_address[1]) + "/"
        print(f"Audio Monitor is at {url}", flush=True)
        if cfg.bind_warning():
            print(cfg.bind_warning(), flush=True)
        _maybe_open(url)
        _install_stop(httpd, engine)
        httpd.serve_forever()
    except OSError as exc:
        print(f"Could not listen on {bind_host}:{bind_port}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if engine is not None:
            engine.stop()
        if httpd is not None:
            threading.Thread(target=httpd.shutdown, daemon=True).start()
            httpd.server_close()
        _release_pid(pid_path)
    return 0


def _setup_log(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "monitor.log"
    if path.exists() and path.stat().st_size > 1_000_000:
        backup = folder / "monitor.log.1"
        if backup.exists():
            backup.unlink()
        path.replace(backup)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _acquire_pid(path: Path) -> None:
    if path.exists():
        try:
            old = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            old = None
        if old and _pid_alive(old) and old != os.getpid():
            raise RuntimeError(f"Already running (pid {old}). Stop that process first.")
    path.write_text(str(os.getpid()), encoding="utf-8")


def _release_pid(path: Path) -> None:
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        return


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _maybe_open(url: str) -> None:
    if os.environ.get("AUDIO_MONITOR_NO_BROWSER") == "1" or sys.platform != "win32":
        return
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        return


def _install_stop(httpd, engine) -> None:
    def handle(signum, frame):
        engine.stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, handle)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle)


if __name__ == "__main__":
    raise SystemExit(main())
