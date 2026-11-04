"""Input-device listing. Names come from the audio host, never from a fixed list."""

from __future__ import annotations


def list_inputs() -> list[dict]:
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    devices = sd.query_devices()
    default_in = _default_input(sd)
    rows = []
    for index, dev in enumerate(devices):
        channels = int(dev["max_input_channels"])
        if channels < 1:
            continue
        host = hostapis[int(dev["hostapi"])]["name"]
        rows.append(
            {
                "index": index,
                "name": str(dev["name"]),
                "hostapi": str(host),
                "channels": channels,
                "default_samplerate": float(dev["default_samplerate"]),
                "is_default": default_in is not None and index == default_in,
            }
        )
    return rows


def _default_input(sd) -> int | None:
    try:
        raw = sd.default.device
    except Exception:
        return None
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        raw = raw[0]
    try:
        index = int(raw)
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return index


def resolve(rows: list[dict], *, index: int | None, name: str, hostapi: str) -> dict | None:
    if index is not None:
        for row in rows:
            if row["index"] == index and row["name"] == name and (not hostapi or row["hostapi"] == hostapi):
                return row
    matches = [
        row
        for row in rows
        if row["name"] == name and (not hostapi or row["hostapi"] == hostapi)
    ]
    if len(matches) == 1:
        return matches[0]
    return None
