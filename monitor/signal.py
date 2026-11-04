"""Level, resample, and voice-activity math on real sample sequences."""

from __future__ import annotations

import math
import time


def rms(samples) -> float:
    count = 0
    total = 0.0
    for value in samples:
        number = float(value)
        total += number * number
        count += 1
    if count == 0:
        return 0.0
    return math.sqrt(total / count)


def peak(samples) -> float:
    highest = 0.0
    for value in samples:
        number = abs(float(value))
        if number > highest:
            highest = number
    return highest


def dbfs(rms_value: float) -> float:
    if rms_value <= 1e-9 or not math.isfinite(rms_value):
        return -90.0
    return 20.0 * math.log10(rms_value)


def resample(samples, src_rate: int, dst_rate: int) -> list[float]:
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("sample rate must be positive")
    data = [float(value) for value in samples]
    if not data or src_rate == dst_rate:
        return data
    if src_rate > dst_rate:
        step = src_rate / dst_rate
        out_len = int(len(data) / step)
        out: list[float] = []
        for index in range(out_len):
            start = int(index * step)
            end = min(len(data), int((index + 1) * step))
            if end <= start:
                end = min(len(data), start + 1)
            acc = 0.0
            for cursor in range(start, end):
                acc += data[cursor]
            out.append(acc / (end - start))
        return out
    step = src_rate / dst_rate
    out_len = int(round(len(data) * dst_rate / src_rate))
    if out_len <= 0:
        return []
    last = len(data) - 1
    out = []
    for index in range(out_len):
        pos = index * step
        left = int(pos)
        if left >= last:
            out.append(data[last])
            continue
        frac = pos - left
        out.append(data[left] * (1.0 - frac) + data[left + 1] * frac)
    return out


class Utterance:
    def __init__(self, samples: list[float], level: float, started_at: float):
        self.samples = samples
        self.level = level
        self.started_at = started_at

    @property
    def duration_ms(self) -> int:
        return int(round(len(self.samples) / 16000 * 1000))


class Segmenter:
    """Energy voice activity. Not a neural model and not a random flag."""

    def __init__(self, sample_rate: int = 16000, sensitivity: float = 0.55):
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        self.sample_rate = sample_rate
        self.sensitivity = 0.55
        self.set_sensitivity(sensitivity)
        self.noise = 0.008
        self.in_speech = False
        self.below = 0
        self.buffer: list[float] = []
        self.voiced = 0
        self.pre: list[float] = []
        self.pre_max = int(0.30 * sample_rate)
        self.hangover = int(0.70 * sample_rate)
        self.min_len = int(0.45 * sample_rate)
        self.max_len = int(20 * sample_rate)
        self.started_at: float | None = None

    def set_max_duration(self, seconds: float) -> None:
        self.max_len = max(self.min_len, int(float(seconds) * self.sample_rate))

    def set_sensitivity(self, value: float) -> None:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("sensitivity must be a finite number")
        self.sensitivity = min(1.0, max(0.0, number))

    def threshold(self) -> float:
        mult = 8.0 - 6.2 * self.sensitivity
        floor = 0.02 * (1.0 - 0.85 * self.sensitivity)
        return max(floor, self.noise * mult)

    def state(self) -> str:
        return "speech" if self.in_speech else "silence"

    def push(self, samples) -> list[Utterance]:
        data = samples if isinstance(samples, list) else [float(value) for value in samples]
        if not data:
            return []
        frame = max(1, int(self.sample_rate * 0.02))
        emitted: list[Utterance] = []
        index = 0
        while index < len(data):
            chunk = data[index : index + frame]
            index += len(chunk)
            emitted.extend(self._frame(chunk))
        return emitted

    def flush(self) -> list[Utterance]:
        if self.in_speech:
            return self._close()
        return []

    def _frame(self, chunk: list[float]) -> list[Utterance]:
        level = rms(chunk)
        if not math.isfinite(level):
            return []
        hot = level >= self.threshold()
        if not self.in_speech:
            if hot:
                self.in_speech = True
                self.started_at = time.time()
                self.buffer = list(self.pre)
                self.below = 0
                self.voiced = 0
                self._append_hot(chunk)
            else:
                self.noise = max(1e-4, 0.95 * self.noise + 0.05 * level)
                self._remember(chunk)
            return []
        self.buffer.extend(chunk)
        if hot:
            self.below = 0
            self.voiced += len(chunk)
        else:
            self.below += len(chunk)
        if self.below >= self.hangover or len(self.buffer) >= self.max_len:
            return self._close()
        return []

    def _append_hot(self, chunk: list[float]) -> None:
        self.buffer.extend(chunk)
        self.voiced += len(chunk)

    def _remember(self, chunk: list[float]) -> None:
        self.pre.extend(chunk)
        extra = len(self.pre) - self.pre_max
        if extra > 0:
            del self.pre[:extra]

    def _close(self) -> list[Utterance]:
        tail = int(0.15 * self.sample_rate)
        trim = max(0, self.below - tail)
        samples = self.buffer[:-trim] if trim else list(self.buffer)
        started = self.started_at or time.time()
        voiced = self.voiced
        self.in_speech = False
        self.buffer = []
        self.below = 0
        self.voiced = 0
        self.pre = []
        self.started_at = None
        if voiced < self.min_len:
            return []
        return [Utterance(samples, rms(samples), started)]
