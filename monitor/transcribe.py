"""Local faster-whisper plan. Weights download only when a load is requested and files are missing."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class Plan:
    action: str
    local_files_only: bool
    model_arg: str
    device: str
    compute_type: str
    message: str


def model_folder(models_dir: Path, model_name: str) -> Path:
    return models_dir / f"models--Systran--faster-whisper-{model_name}"


def weights_present(models_dir: Path, model_name: str) -> bool:
    snaps = model_folder(models_dir, model_name) / "snapshots"
    if not snaps.is_dir():
        return False
    for snap in snaps.iterdir():
        if snap.is_dir() and (snap / "model.bin").is_file():
            return True
    return False


def explicit_weights(path: str) -> bool:
    if not path:
        return False
    folder = Path(path)
    return folder.is_dir() and (folder / "model.bin").is_file()


def plan_load(cfg: Config, models_dir: Path, *, cuda_count: int | None, cuda_error: str | None) -> Plan:
    if cfg.model_path:
        if not explicit_weights(cfg.model_path):
            return Plan(
                "error",
                True,
                cfg.model_path,
                cfg.compute_device,
                cfg.compute_type,
                "model_path does not contain model.bin. Nothing was downloaded.",
            )
        model_arg = cfg.model_path
        present = True
    else:
        present = weights_present(models_dir, cfg.model)
        model_arg = cfg.model
    if cfg.compute_device == "cpu":
        if not cfg.allow_cpu:
            return Plan("error", True, model_arg, "cpu", cfg.compute_type, "CPU transcription is disabled.")
        if not present and cfg.offline:
            return Plan(
                "error",
                True,
                model_arg,
                "cpu",
                cfg.compute_type,
                "Offline is set and the speech-model weights are not on disk. Nothing was downloaded.",
            )
        if not present:
            return Plan(
                "needs_download",
                False,
                model_arg,
                "cpu",
                cfg.compute_type,
                "Speech-model weights are not on disk. Load the model to download them once into the models folder.",
            )
        return Plan("load", True, model_arg, "cpu", cfg.compute_type, "Loading the speech model from disk.")
    if cfg.compute_device != "cuda":
        return Plan("error", True, model_arg, cfg.compute_device, cfg.compute_type, "compute_device is not cuda or cpu.")
    if cuda_error:
        return Plan("error", True, model_arg, "cuda", cfg.compute_type, cuda_error)
    if cuda_count is None or cuda_count < 1:
        return Plan(
            "error",
            True,
            model_arg,
            "cuda",
            cfg.compute_type,
            "No CUDA device is visible. Transcription was not started.",
        )
    if not present and cfg.offline:
        return Plan(
            "error",
            True,
            model_arg,
            "cuda",
            cfg.compute_type,
            "Offline is set and the speech-model weights are not on disk. Nothing was downloaded.",
        )
    if not present:
        return Plan(
            "needs_download",
            False,
            model_arg,
            "cuda",
            cfg.compute_type,
            "Speech-model weights are not on disk. Load the model to download them once into the models folder.",
        )
    return Plan("load", True, model_arg, "cuda", cfg.compute_type, "Loading the speech model from disk.")


def apply_privacy_env(offline: bool) -> None:
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)


def probe_cuda() -> tuple[int | None, str | None]:
    try:
        import ctranslate2
    except Exception as exc:
        return None, f"CUDA library is not installed: {exc}"
    try:
        count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        return None, f"CUDA is not available in this install: {exc}"
    return count, None


def load_whisper(plan: Plan, models_dir: Path, offline: bool):
    apply_privacy_env(offline or plan.local_files_only)
    from faster_whisper import WhisperModel

    kwargs = {
        "device": plan.device,
        "compute_type": plan.compute_type,
        "local_files_only": plan.local_files_only,
        "num_workers": 1,
    }
    if not plan.model_arg or Path(plan.model_arg).is_dir():
        return WhisperModel(plan.model_arg, **kwargs)
    return WhisperModel(plan.model_arg, download_root=str(models_dir), **kwargs)


def run_model(model, samples, language: str, task: str = "transcribe") -> tuple[str, float | None, float | None]:
    if len(samples) < 160:
        return "", None, None
    import numpy as np

    audio = np.asarray(samples, dtype=np.float32)
    if not np.isfinite(audio).all():
        raise ValueError("audio contained a non-finite sample")
    segments, _info = model.transcribe(
        audio,
        language=language or None,
        task=task,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        vad_filter=False,
        without_timestamps=True,
        condition_on_previous_text=False,
    )
    texts: list[str] = []
    logprobs: list[float] = []
    nospeech: list[float] = []
    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if text:
            texts.append(text)
        logprob = getattr(segment, "avg_logprob", None)
        if logprob is not None:
            logprobs.append(float(logprob))
        score = getattr(segment, "no_speech_prob", None)
        if score is not None:
            nospeech.append(float(score))
    joined = " ".join(" ".join(texts).split())
    confidence = None
    if logprobs:
        confidence = sum(math.exp(min(0.0, value)) for value in logprobs) / len(logprobs)
        confidence = max(0.0, min(1.0, confidence))
    mean_no_speech = sum(nospeech) / len(nospeech) if nospeech else None
    return joined, confidence, mean_no_speech
