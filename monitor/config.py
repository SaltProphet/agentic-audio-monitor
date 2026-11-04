"""One local config file. Unknown flag names are rejected."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FLAG_KEYS = ("echo", "idle_speech", "loopback")
MODELS = (
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v3",
)
SOURCE_MODES = ("external", "system", "both")
COMPUTE_TYPES = ("float16", "int8_float16", "int8", "float32")
HEADER = (
    "# Audio Monitor config. The local page rewrites this file when you save.\n"
    "# echo and idle_speech are stored but are not acted on in this build.\n\n"
)


def _flags() -> dict[str, bool]:
    return {key: False for key in FLAG_KEYS}


@dataclass
class Config:
    device_name: str = ""
    device_hostapi: str = ""
    device_index: int | None = None
    sensitivity: float = 0.55
    save_clips: bool = False
    retention_days: int = 7
    model: str = "small"
    model_path: str = ""
    language: str = "en"
    task: str = "transcribe"
    compute_device: str = "cuda"
    compute_type: str = "float16"
    allow_cpu: bool = False
    offline: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    source_mode: str = "external"
    flags: dict[str, bool] = field(default_factory=_flags)

    def validate(self) -> None:
        if not isinstance(self.device_name, str) or not isinstance(self.device_hostapi, str):
            raise ValueError("device name and host API must be text")
        if self.device_index is not None and (
            not isinstance(self.device_index, int) or self.device_index < 0
        ):
            raise ValueError("device_index must be a non-negative integer or empty")
        if not isinstance(self.sensitivity, (int, float)) or not (0.0 <= float(self.sensitivity) <= 1.0):
            raise ValueError("sensitivity must be between 0 and 1")
        self.sensitivity = float(self.sensitivity)
        if not isinstance(self.save_clips, bool):
            raise ValueError("save_clips must be true or false")
        if not isinstance(self.retention_days, int) or not (1 <= self.retention_days <= 3650):
            raise ValueError("retention_days must be a whole number from 1 to 3650")
        if self.model not in MODELS:
            raise ValueError("model must be one of: " + ", ".join(MODELS))
        if not isinstance(self.model_path, str):
            raise ValueError("model_path must be text")
        if self.language and (
            not isinstance(self.language, str)
            or not self.language.replace("-", "").isalpha()
            or not (2 <= len(self.language) <= 8)
        ):
            raise ValueError("language must be empty or a short language code such as en")
        if self.task not in ("transcribe", "translate"):
            raise ValueError("task must be transcribe or translate")
        if self.compute_device not in ("cuda", "cpu"):
            raise ValueError("compute_device must be cuda or cpu")
        if self.compute_type not in COMPUTE_TYPES:
            raise ValueError("compute_type is not supported")
        if not isinstance(self.allow_cpu, bool) or not isinstance(self.offline, bool):
            raise ValueError("allow_cpu and offline must be true or false")
        if self.compute_device == "cpu" and not self.allow_cpu:
            raise ValueError(
                "CPU transcription is off. Set allow_cpu = true only if you mean to leave the GPU."
            )
        if self.compute_device == "cpu" and self.compute_type == "float16":
            raise ValueError("float16 is for the GPU. Use int8 with compute_device = cpu.")
        if not isinstance(self.host, str) or not self.host.strip() or any(ch.isspace() for ch in self.host):
            raise ValueError("host must be a hostname or address without spaces")
        if not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            raise ValueError("port must be from 1 to 65535")
        if self.source_mode not in SOURCE_MODES:
            raise ValueError("source_mode must be external, system, or both")
        if not isinstance(self.flags, dict):
            raise ValueError("flags must be a table")
        unknown = set(self.flags) - set(FLAG_KEYS)
        if unknown:
            raise ValueError("unknown flag: " + ", ".join(sorted(unknown)))
        for key in FLAG_KEYS:
            value = self.flags.get(key, False)
            if not isinstance(value, bool):
                raise ValueError(f"flag {key} must be true or false")
            self.flags[key] = value
        self.flags["loopback"] = self.source_mode == "system"

    def ignored_flags(self) -> list[str]:
        return [key for key in FLAG_KEYS if key != "loopback" and self.flags.get(key)]

    def bind_warning(self) -> str | None:
        if self.host in ("127.0.0.1", "localhost", "::1"):
            return None
        return "Bound beyond this machine. Prefer host = 127.0.0.1 so the page is not reachable from elsewhere."


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_toml(cfg: Config) -> str:
    cfg.validate()
    index = -1 if cfg.device_index is None else cfg.device_index
    lines = [
        HEADER.rstrip("\n"),
        "",
        f"device_name = {_toml_string(cfg.device_name)}",
        f"device_hostapi = {_toml_string(cfg.device_hostapi)}",
        f"device_index = {index}",
        f"sensitivity = {round(float(cfg.sensitivity), 4)}",
        f"save_clips = {'true' if cfg.save_clips else 'false'}",
        f"retention_days = {cfg.retention_days}",
        f"model = {_toml_string(cfg.model)}",
        f"model_path = {_toml_string(cfg.model_path)}",
        f"language = {_toml_string(cfg.language)}",
        f"task = {_toml_string(cfg.task)}",
        f"compute_device = {_toml_string(cfg.compute_device)}",
        f"compute_type = {_toml_string(cfg.compute_type)}",
        f"allow_cpu = {'true' if cfg.allow_cpu else 'false'}",
        f"offline = {'true' if cfg.offline else 'false'}",
        f"host = {_toml_string(cfg.host)}",
        f"port = {cfg.port}",
        f"source_mode = {_toml_string(cfg.source_mode)}",
        "",
        "[flags]",
        f"echo = {'true' if cfg.flags['echo'] else 'false'}",
        f"idle_speech = {'true' if cfg.flags['idle_speech'] else 'false'}",
        f"loopback = {'true' if cfg.flags['loopback'] else 'false'}",
        "",
    ]
    return "\n".join(lines)


def load_config(path: Path) -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config must be a table")
    flags_raw = raw.get("flags") or {}
    if not isinstance(flags_raw, dict):
        raise ValueError("flags must be a table")
    index = raw.get("device_index", -1)
    if index is None or index == -1 or index == "":
        index = None
    cfg = Config(
        device_name=raw.get("device_name", ""),
        device_hostapi=raw.get("device_hostapi", ""),
        device_index=index,
        sensitivity=raw.get("sensitivity", 0.55),
        save_clips=raw.get("save_clips", False),
        retention_days=raw.get("retention_days", 7),
        model=raw.get("model", "small"),
        model_path=raw.get("model_path", ""),
        language=raw.get("language", "en"),
        task=raw.get("task", "transcribe"),
        compute_device=raw.get("compute_device", "cuda"),
        compute_type=raw.get("compute_type", "float16"),
        allow_cpu=raw.get("allow_cpu", False),
        offline=raw.get("offline", False),
        host=raw.get("host", "127.0.0.1"),
        port=raw.get("port", 8765),
        source_mode=raw.get("source_mode", "system" if flags_raw.get("loopback", False) else "external"),
        flags={key: bool(flags_raw.get(key, False)) for key in FLAG_KEYS},
    )
    # Reject unknown flag keys instead of hiding them in the bool cast above.
    unknown = set(flags_raw) - set(FLAG_KEYS)
    if unknown:
        raise ValueError("unknown flag: " + ", ".join(sorted(str(item) for item in unknown)))
    for key in FLAG_KEYS:
        if key in flags_raw and not isinstance(flags_raw[key], bool):
            raise ValueError(f"flag {key} must be true or false")
        cfg.flags[key] = flags_raw.get(key, False) if isinstance(flags_raw.get(key, False), bool) else False
    cfg.validate()
    return cfg


def save_config(path: Path, cfg: Config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_toml(cfg)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def ensure_config(path: Path) -> Config:
    if not path.exists():
        save_config(path, Config())
    return load_config(path)
