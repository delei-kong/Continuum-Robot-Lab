"""Pure-Python contracts for collecting direct Trunk dynamics episodes.

The module deliberately has no SOFA dependency so that action safety, timing,
and deterministic excitation can be tested locally before a remote simulation
is launched.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import isfinite, pi, sin
from typing import Any, Mapping, Sequence


CABLE_NAMES = tuple(f"cableL{index}" for index in range(4)) + tuple(
    f"cableS{index}" for index in range(4)
)
CABLE_COUNT = len(CABLE_NAMES)


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_sequence(value: Any, name: str, count: int) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must contain {count} values")
    if len(value) != count:
        raise ValueError(f"{name} must contain {count} values")
    return tuple(_finite_float(item, name) for item in value)


@dataclass(frozen=True)
class ForwardDataConfig:
    """Validated, code-owned configuration for one direct dynamics episode."""

    dt_s: float
    duration_s: float
    settle_duration_s: float
    seed: int
    cable_max_displacements_mm: tuple[float, ...]
    max_command_delta_mm: float
    excitation_amplitudes_mm: tuple[float, ...]
    base_frequency_hz: float
    frequency_step_hz: float
    centerline_z_mm: tuple[float, ...]
    csv_flush_interval_steps: int

    def __post_init__(self) -> None:
        scalars = (
            self.dt_s,
            self.duration_s,
            self.settle_duration_s,
            self.max_command_delta_mm,
            self.base_frequency_hz,
            self.frequency_step_hz,
        )
        if not all(isfinite(value) for value in scalars):
            raise ValueError("forward data configuration must contain finite values")
        if self.dt_s <= 0.0 or self.duration_s <= 0.0:
            raise ValueError("dt and duration must be positive")
        if self.settle_duration_s < 0.0 or self.settle_duration_s >= self.duration_s:
            raise ValueError("settle duration must be non-negative and shorter than duration")
        if self.max_command_delta_mm <= 0.0:
            raise ValueError("max command delta must be positive")
        if self.base_frequency_hz <= 0.0 or self.frequency_step_hz < 0.0:
            raise ValueError("excitation frequencies must be positive/non-negative")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if isinstance(self.csv_flush_interval_steps, bool) or self.csv_flush_interval_steps < 1:
            raise ValueError("csv flush interval must be a positive integer")
        if len(self.cable_max_displacements_mm) != CABLE_COUNT:
            raise ValueError("cable maxima must match the Trunk cable count")
        if len(self.excitation_amplitudes_mm) != CABLE_COUNT:
            raise ValueError("excitation amplitudes must match the Trunk cable count")
        if any(value <= 0.0 for value in self.cable_max_displacements_mm):
            raise ValueError("cable maxima must be positive")
        if any(value < 0.0 for value in self.excitation_amplitudes_mm):
            raise ValueError("excitation amplitudes must be non-negative")
        if any(
            amplitude > maximum
            for amplitude, maximum in zip(
                self.excitation_amplitudes_mm, self.cable_max_displacements_mm
            )
        ):
            raise ValueError("excitation amplitude cannot exceed the cable maximum")
        if len(self.centerline_z_mm) < 2 or any(
            upper <= lower
            for lower, upper in zip(self.centerline_z_mm, self.centerline_z_mm[1:])
        ):
            raise ValueError("centerline sample positions must be strictly increasing")
        steps = round(self.duration_s / self.dt_s)
        if abs(steps * self.dt_s - self.duration_s) > 1e-9:
            raise ValueError("duration must be an integer multiple of dt")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ForwardDataConfig":
        return cls(
            dt_s=_finite_float(values["dt"], "dt"),
            duration_s=_finite_float(values["duration_s"], "duration_s"),
            settle_duration_s=_finite_float(
                values["settle_duration_s"], "settle_duration_s"
            ),
            seed=int(values["seed"]),
            cable_max_displacements_mm=_finite_sequence(
                values["cable_max_displacements_mm"],
                "cable_max_displacements_mm",
                CABLE_COUNT,
            ),
            max_command_delta_mm=_finite_float(
                values["max_command_delta_mm"], "max_command_delta_mm"
            ),
            excitation_amplitudes_mm=_finite_sequence(
                values["excitation_amplitudes_mm"],
                "excitation_amplitudes_mm",
                CABLE_COUNT,
            ),
            base_frequency_hz=_finite_float(
                values["base_frequency_hz"], "base_frequency_hz"
            ),
            frequency_step_hz=_finite_float(
                values["frequency_step_hz"], "frequency_step_hz"
            ),
            centerline_z_mm=tuple(
                _finite_float(value, "centerline_z_mm")
                for value in values["centerline_z_mm"]
            ),
            csv_flush_interval_steps=int(values["csv_flush_interval_steps"]),
        )

    @property
    def total_steps(self) -> int:
        return round(self.duration_s / self.dt_s)


@dataclass(frozen=True)
class ActionProjection:
    """Actual cable command after hard physical command limits are applied."""

    desired_mm: tuple[float, ...]
    applied_mm: tuple[float, ...]
    limited: bool


class CableActionSafetyLayer:
    """Limit direct cable commands to non-negative, smooth feasible values."""

    def __init__(
        self,
        maximum_displacements_mm: Sequence[float],
        max_delta_mm: float,
    ) -> None:
        self._maximum = _finite_sequence(
            maximum_displacements_mm,
            "maximum_displacements_mm",
            CABLE_COUNT,
        )
        if any(value <= 0.0 for value in self._maximum):
            raise ValueError("maximum cable displacements must be positive")
        self._max_delta = _finite_float(max_delta_mm, "max_delta_mm")
        if self._max_delta <= 0.0:
            raise ValueError("max_delta_mm must be positive")
        self._current = (0.0,) * CABLE_COUNT

    @property
    def current_mm(self) -> tuple[float, ...]:
        return self._current

    def reset(self) -> None:
        self._current = (0.0,) * CABLE_COUNT

    def project(self, desired_mm: Sequence[float]) -> ActionProjection:
        desired = _finite_sequence(desired_mm, "desired cable command", CABLE_COUNT)
        applied: list[float] = []
        for requested, current, maximum in zip(desired, self._current, self._maximum):
            bounded = min(max(requested, 0.0), maximum)
            rate_limited = min(max(bounded, current - self._max_delta), current + self._max_delta)
            applied.append(rate_limited)
        self._current = tuple(applied)
        return ActionProjection(
            desired_mm=desired,
            applied_mm=self._current,
            limited=any(abs(left - right) > 1e-12 for left, right in zip(desired, applied)),
        )


class MultiSineExcitation:
    """Seeded multi-cable excitation with distinct frequencies and phases."""

    def __init__(self, config: ForwardDataConfig) -> None:
        self.config = config
        generator = random.Random(config.seed)
        self._phases = tuple(generator.uniform(0.0, 2.0 * pi) for _ in CABLE_NAMES)

    def sample(self, time_s: float) -> tuple[str, tuple[float, ...]]:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("sample time must be finite and non-negative")
        if time_s < self.config.settle_duration_s:
            return "settle", (0.0,) * CABLE_COUNT
        excitation_time = time_s - self.config.settle_duration_s
        commands = tuple(
            amplitude
            * 0.5
            * (
                1.0
                + sin(
                    2.0
                    * pi
                    * (self.config.base_frequency_hz + index * self.config.frequency_step_hz)
                    * excitation_time
                    + phase
                )
            )
            for index, (amplitude, phase) in enumerate(
                zip(self.config.excitation_amplitudes_mm, self._phases)
            )
        )
        return "excitation", commands
