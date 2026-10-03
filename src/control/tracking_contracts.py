"""Controller-facing contracts for trajectory-tracking experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping, Protocol, Union


Vec3 = tuple[float, float, float]


def finite_vec3(value: object, name: str) -> Vec3:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError(f"{name} must be a three-value tuple")
    vector = tuple(float(axis) for axis in value)
    if not all(isfinite(axis) for axis in vector):
        raise ValueError(f"{name} must contain finite values")
    return vector  # type: ignore[return-value]


@dataclass(frozen=True)
class TrajectoryReference:
    time_s: float
    position_mm: Vec3
    velocity_mm_s: Vec3 | None = None
    acceleration_mm_s2: Vec3 | None = None
    phase: str = "tracking"
    cycle_index: int = -1

    def __post_init__(self) -> None:
        if not isfinite(self.time_s) or self.time_s < 0.0:
            raise ValueError("reference time must be finite and non-negative")
        finite_vec3(self.position_mm, "reference position")
        if self.velocity_mm_s is not None:
            finite_vec3(self.velocity_mm_s, "reference velocity")
        if self.acceleration_mm_s2 is not None:
            finite_vec3(self.acceleration_mm_s2, "reference acceleration")
        if not self.phase:
            raise ValueError("reference phase must not be empty")


@dataclass(frozen=True)
class TrackingObservation:
    time_s: float
    tip_position_mm: Vec3
    cable_displacements_mm: tuple[float, ...] = ()
    cable_forces_mn: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not isfinite(self.time_s) or self.time_s < 0.0:
            raise ValueError("observation time must be finite and non-negative")
        finite_vec3(self.tip_position_mm, "tip position")
        telemetry = self.cable_displacements_mm + self.cable_forces_mn
        if not all(isfinite(float(value)) for value in telemetry):
            raise ValueError("cable telemetry must contain finite values")
        if self.cable_forces_mn and (
            len(self.cable_forces_mn) != len(self.cable_displacements_mm)
        ):
            raise ValueError("cable force and displacement counts must match")


@dataclass(frozen=True)
class TaskSpaceGoalCommand:
    position_mm: Vec3
    kind: str = field(default="task_space_goal", init=False)

    def __post_init__(self) -> None:
        finite_vec3(self.position_mm, "task-space goal")


@dataclass(frozen=True)
class CableDisplacementCommand:
    displacements_mm: tuple[float, ...]
    kind: str = field(default="cable_displacement", init=False)

    def __post_init__(self) -> None:
        if not self.displacements_mm:
            raise ValueError("cable displacement command must not be empty")
        if not all(isfinite(float(value)) for value in self.displacements_mm):
            raise ValueError("cable displacement command must contain finite values")


ControlCommand = Union[TaskSpaceGoalCommand, CableDisplacementCommand]


@dataclass(frozen=True)
class ControllerOutput:
    command: ControlCommand
    diagnostics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(isfinite(float(value)) for value in self.diagnostics.values()):
            raise ValueError("controller diagnostics must contain finite values")


@dataclass(frozen=True)
class ControllerContext:
    dt_s: float
    cable_count: int
    supported_command_kinds: frozenset[str]

    def __post_init__(self) -> None:
        if not isfinite(self.dt_s) or self.dt_s <= 0.0:
            raise ValueError("controller dt must be finite and positive")
        if self.cable_count < 0:
            raise ValueError("cable count must be non-negative")
        if not self.supported_command_kinds:
            raise ValueError("backend must support at least one command kind")


class TrackingController(Protocol):
    """Stable lifecycle implemented by every trajectory-tracking controller."""

    def reset(self, context: ControllerContext) -> None: ...

    def compute(
        self,
        observation: TrackingObservation,
        reference: TrajectoryReference,
        dt_s: float,
    ) -> ControllerOutput: ...

    def finalize(self) -> None: ...
