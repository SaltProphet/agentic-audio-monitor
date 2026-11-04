"""Append-only event log and optional WAV clips. Both stay in the data folder."""

from __future__ import annotations

import json
import os
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.log_path = root / "logs" / "events.jsonl"
        self.clips_dir = root / "clips"
        self._lock = Lock()

    def append(self, record: dict) -> dict:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if "\n" in line or "\r" in line:
            raise ValueError("event record must be one line")
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return record

    def tail(self, limit: int = 40) -> list[dict]:
        if limit < 1 or not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        rows.reverse()
        return rows

    def write_clip(self, samples: list[float], sample_rate: int, started_at: float) -> str:
        stamp = datetime.fromtimestamp(started_at, timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"utt-{stamp}.wav"
        path = self.clips_dir / name
        with self._lock:
            self.clips_dir.mkdir(parents=True, exist_ok=True)
            _write_wav(path, samples, sample_rate)
        return f"clips/{name}"

    def prune(self, retention_days: int) -> dict:
        cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
        kept = 0
        removed = 0
        with self._lock:
            if self.log_path.exists():
                kept_lines = []
                for line in self.log_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        when = datetime.fromisoformat(record["ts"])
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        kept_lines.append(line)
                        kept += 1
                        continue
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=cutoff.tzinfo)
                    if when >= cutoff:
                        kept_lines.append(line)
                        kept += 1
                    else:
                        removed += 1
                text = ("\n".join(kept_lines) + "\n") if kept_lines else ""
                tmp = self.log_path.with_suffix(".jsonl.tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(self.log_path)
            clips_removed = 0
            if self.clips_dir.exists():
                deadline = time_cutoff(retention_days)
                for path in self.clips_dir.glob("*.wav"):
                    if path.stat().st_mtime < deadline:
                        path.unlink()
                        clips_removed += 1
        return {"events_kept": kept, "events_removed": removed, "clips_removed": clips_removed}

    def clip_file(self, name: str) -> Path | None:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        if not name.endswith(".wav"):
            return None
        root = self.clips_dir.resolve()
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            return None
        return path


def time_cutoff(retention_days: int) -> float:
    return datetime.now().timestamp() - retention_days * 86400


def _write_wav(path: Path, samples: list[float], sample_rate: int) -> None:
    frames = bytearray()
    for value in samples:
        number = float(value)
        if number > 1.0:
            number = 1.0
        elif number < -1.0:
            number = -1.0
        integer = int(round(number * 32767.0))
        frames += int(integer).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)


def touch_old(path: Path, days_ago: float) -> None:
    when = datetime.now().timestamp() - days_ago * 86400
    os.utime(path, (when, when))
