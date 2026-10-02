"""Pure-Python target schedule and timing statistics for inverse Trunk control."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence


Point3 = tuple[float, float, float]


def _point3(value: Any, name: str) -> Point3:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    point = tuple(float(axis) for axis in value)
    if not all(isfinite(axis) for axis in point):
        raise ValueError(f"{name} must contain finite values")
    return point  # type: ignore[return-value]


@dataclass(frozen=True)
class InverseTargetSample:
    time_s: float
    position_mm: Point3
    phase: str


@dataclass(frozen=True)
class InverseTrackingConfig:
    dt: float
    control_rate_hz: float
    start_target_mm: Point3
    target_mm: Point3
    settle_duration_s: float
    transition_duration_s: float
    hold_duration_s: float
    deadline_ms: float
    benchmark_warmup_steps: int

    def __post_init__(self) -> None:
        scalar_values = (
            self.dt,
            self.control_rate_hz,
            self.settle_duration_s,
            self.transition_duration_s,
            self.hold_duration_s,
            self.deadline_ms,
        )
        if not all(isfinite(value) for value in scalar_values):
            raise ValueError("inverse tracking configuration must contain finite values")
        if self.dt <= 0.0 or self.control_rate_hz <= 0.0:
            raise ValueError("dt and control_rate_hz must be positive")
        if abs(self.dt * self.control_rate_hz - 1.0) > 1e-9:
            raise ValueError("one simulation step must equal one control period")
        if self.settle_duration_s < 0.0:
            raise ValueError("settle duration must be non-negative")
        if self.transition_duration_s <= 0.0 or self.hold_duration_s <= 0.0:
            raise ValueError("transition and hold durations must be positive")
        if self.deadline_ms <= 0.0:
            raise ValueError("deadline_ms must be positive")
        if isinstance(self.benchmark_warmup_steps, bool) or self.benchmark_warmup_steps < 0:
            raise ValueError("benchmark_warmup_steps must be a non-negative integer")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "InverseTrackingConfig":
        return cls(
            dt=float(values["dt"]),
            control_rate_hz=float(values["control_rate_hz"]),
            start_target_mm=_point3(values["start_target_mm"], "start_target_mm"),
            target_mm=_point3(values["target_mm"], "target_mm"),
            settle_duration_s=float(values["settle_duration_s"]),
            transition_duration_s=float(values["transition_duration_s"]),
            hold_duration_s=float(values["hold_duration_s"]),
            deadline_ms=float(values["deadline_ms"]),
            benchmark_warmup_steps=int(values["benchmark_warmup_steps"]),
        )

    @property
    def total_duration_s(self) -> float:
        return self.settle_duration_s + self.transition_duration_s + self.hold_duration_s


class InverseTargetSignal:
    """Hold the initial goal, move linearly, then hold one fixed goal."""

    def __init__(self, config: InverseTrackingConfig) -> None:
        self.config = config

    def sample(self, time_s: float) -> InverseTargetSample:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("time_s must be finite and non-negative")
        config = self.config
        if time_s < config.settle_duration_s:
            return InverseTargetSample(time_s, config.start_target_mm, "settle")

        transition_time = time_s - config.settle_duration_s
        if transition_time < config.transition_duration_s:
            alpha = transition_time / config.transition_duration_s
            position = tuple(
                start + alpha * (target - start)
                for start, target in zip(config.start_target_mm, config.target_mm)
            )
            return InverseTargetSample(time_s, position, "transition")  # type: ignore[arg-type]
        return InverseTargetSample(time_s, config.target_mm, "hold")

    def sample_step(self, step: int) -> InverseTargetSample:
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise ValueError("step must be a non-negative integer")
        return self.sample(step * self.config.dt)

    def total_steps(self) -> int:
        steps = round(self.config.total_duration_s / self.config.dt)
        if abs(steps * self.config.dt - self.config.total_duration_s) > 1e-9:
            raise ValueError("total duration must be an integer multiple of dt")
        return steps


def percentile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated percentile without external dependencies."""

    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between zero and one")
    ordered = sorted(float(value) for value in values)
    if not all(isfinite(value) for value in ordered):
        raise ValueError("values must be finite")
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def summarize_step_times(
    step_times_ms: Sequence[float], deadline_ms: float, warmup_steps: int
) -> dict[str, float | int | bool]:
    if not isfinite(deadline_ms) or deadline_ms <= 0.0:
        raise ValueError("deadline_ms must be finite and positive")
    if isinstance(warmup_steps, bool) or not isinstance(warmup_steps, int) or warmup_steps < 0:
        raise ValueError("warmup_steps must be a non-negative integer")
    measured = [float(value) for value in step_times_ms[warmup_steps:]]
    if not measured:
        raise ValueError("no timing samples remain after warmup")
    missed = sum(value > deadline_ms for value in measured)
    p99_ms = percentile(measured, 0.99)
    return {
        "warmup_steps": warmup_steps,
        "measured_steps": len(measured),
        "mean_ms": sum(measured) / len(measured),
        "p50_ms": percentile(measured, 0.50),
        "p95_ms": percentile(measured, 0.95),
        "p99_ms": p99_ms,
        "max_ms": max(measured),
        "deadline_ms": deadline_ms,
        "deadline_misses": missed,
        "deadline_success_ratio": (len(measured) - missed) / len(measured),
        "p99_deadline_met": p99_ms <= deadline_ms,
    }
