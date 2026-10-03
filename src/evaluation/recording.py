"""In-memory recording contract for trajectory-tracking experiments."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from control.tracking_contracts import (
    ControllerOutput,
    TrackingObservation,
    TrajectoryReference,
)


@dataclass(frozen=True)
class TrackingStepRecord:
    step: int
    time_s: float
    reference: TrajectoryReference
    observation: TrackingObservation
    controller_output: ControllerOutput
    tracking_error_norm_mm: float
    controller_wall_ms: float
    backend_wall_ms: float
    control_period_wall_ms: float | None

    def __post_init__(self) -> None:
        values = (
            self.time_s,
            self.tracking_error_norm_mm,
            self.controller_wall_ms,
            self.backend_wall_ms,
        )
        if self.step < 0 or not all(isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("tracking record indices and measurements must be non-negative")
        if abs(self.reference.time_s - self.time_s) > 1e-9:
            raise ValueError("reference and record timestamps must match")
        if abs(self.observation.time_s - self.time_s) > 1e-9:
            raise ValueError("observation and record timestamps must match")
        if self.control_period_wall_ms is not None and (
            not isfinite(self.control_period_wall_ms) or self.control_period_wall_ms < 0.0
        ):
            raise ValueError("control period must be finite and non-negative when present")


class TrackingRecorder(Protocol):
    def reset(self) -> None: ...

    def append(self, record: TrackingStepRecord) -> None: ...

    def finalize(self) -> tuple[TrackingStepRecord, ...]: ...


class InMemoryTrackingRecorder:
    """Retain step records without putting file I/O in the control loop."""

    def __init__(self) -> None:
        self._records: list[TrackingStepRecord] = []

    def reset(self) -> None:
        self._records.clear()

    def append(self, record: TrackingStepRecord) -> None:
        if self._records and record.step != self._records[-1].step + 1:
            raise ValueError("tracking records must have consecutive step indices")
        if not self._records and record.step != 0:
            raise ValueError("the first tracking record must use step zero")
        self._records.append(record)

    def finalize(self) -> tuple[TrackingStepRecord, ...]:
        return tuple(self._records)
