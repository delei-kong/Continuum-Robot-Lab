"""Pure-Python cyclic displacement signal used by SOFA scenes."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, pi
from typing import Any, Mapping


@dataclass(frozen=True)
class CyclicControlSample:
    time_s: float
    displacement_mm: float
    phase: str
    cycle_index: int | None


@dataclass(frozen=True)
class CyclicControlConfig:
    amplitude_mm: float
    period_s: float
    settle_duration_s: float
    cycles: int
    release_duration_s: float
    max_displacement_mm: float

    def __post_init__(self) -> None:
        values = (
            self.amplitude_mm,
            self.period_s,
            self.settle_duration_s,
            self.release_duration_s,
            self.max_displacement_mm,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("control configuration must contain finite values")
        if self.amplitude_mm < 0.0:
            raise ValueError("amplitude_mm must be non-negative")
        if self.period_s <= 0.0:
            raise ValueError("period_s must be positive")
        if self.settle_duration_s < 0.0 or self.release_duration_s < 0.0:
            raise ValueError("settle and release durations must be non-negative")
        if isinstance(self.cycles, bool) or not isinstance(self.cycles, int) or self.cycles < 1:
            raise ValueError("cycles must be a positive integer")
        if self.max_displacement_mm <= 0.0:
            raise ValueError("max_displacement_mm must be positive")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "CyclicControlConfig":
        return cls(
            amplitude_mm=float(values["amplitude_mm"]),
            period_s=float(values["period_s"]),
            settle_duration_s=float(values["settle_duration_s"]),
            cycles=int(values["cycles"]),
            release_duration_s=float(values["release_duration_s"]),
            max_displacement_mm=float(values["max_displacement_mm"]),
        )

    @property
    def total_duration_s(self) -> float:
        return self.settle_duration_s + self.cycles * self.period_s + self.release_duration_s


class CyclicControlSignal:
    """A settle/cycle/release command using a non-negative cosine wave."""

    def __init__(self, config: CyclicControlConfig) -> None:
        self.config = config

    def sample(self, time_s: float) -> CyclicControlSample:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("time_s must be finite and non-negative")

        config = self.config
        cyclic_end = config.settle_duration_s + config.cycles * config.period_s
        if time_s < config.settle_duration_s:
            return CyclicControlSample(time_s, 0.0, "settle", None)
        if time_s >= cyclic_end:
            return CyclicControlSample(time_s, 0.0, "release", None)

        cyclic_time = time_s - config.settle_duration_s
        cycle_index = min(int(cyclic_time / config.period_s), config.cycles - 1)
        phase_time = cyclic_time - cycle_index * config.period_s
        raw_value = config.amplitude_mm / 2.0 * (
            1.0 - cos(2.0 * pi * phase_time / config.period_s)
        )
        value = min(max(raw_value, 0.0), config.max_displacement_mm)
        return CyclicControlSample(time_s, value, "cycle", cycle_index)

    def sample_step(self, step: int, dt: float) -> CyclicControlSample:
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise ValueError("step must be a non-negative integer")
        if not isfinite(dt) or dt <= 0.0:
            raise ValueError("dt must be finite and positive")
        return self.sample(step * dt)

    def total_steps(self, dt: float) -> int:
        if not isfinite(dt) or dt <= 0.0:
            raise ValueError("dt must be finite and positive")
        steps = round(self.config.total_duration_s / dt)
        if abs(steps * dt - self.config.total_duration_s) > 1e-9:
            raise ValueError("total duration must be an integer multiple of dt")
        return steps
