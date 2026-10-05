"""Baseline controller adapters used to validate the tracking pipeline."""

from __future__ import annotations

from typing import Any, Mapping

from control.pid_controller import TaskSpacePIDController
from control.tracking_contracts import (
    ControllerContext,
    ControllerOutput,
    TaskSpaceGoalCommand,
    TrackingObservation,
    TrajectoryReference,
)


class ReferenceGoalController:
    """Forward each trajectory reference as a task-space goal command."""

    def __init__(self) -> None:
        self._ready = False
        self._dt_s = 0.0

    def reset(self, context: ControllerContext) -> None:
        if "task_space_goal" not in context.supported_command_kinds:
            raise ValueError("backend does not support task-space goal commands")
        self._dt_s = context.dt_s
        self._ready = True

    def compute(
        self,
        observation: TrackingObservation,
        reference: TrajectoryReference,
        dt_s: float,
    ) -> ControllerOutput:
        if not self._ready:
            raise RuntimeError("controller must be reset before compute")
        if abs(dt_s - self._dt_s) > 1e-9:
            raise ValueError("controller and experiment dt must match")
        return ControllerOutput(
            command=TaskSpaceGoalCommand(reference.position_mm),
            diagnostics={"reference_lead_s": reference.time_s - observation.time_s},
        )

    def finalize(self) -> None:
        self._ready = False
        self._dt_s = 0.0


def controller_from_mapping(
    values: Mapping[str, Any],
) -> ReferenceGoalController | TaskSpacePIDController:
    controller_type = values.get("type")
    if controller_type == "reference_goal":
        return ReferenceGoalController()
    if controller_type == "task_space_pid":
        return TaskSpacePIDController.from_mapping(values)
    raise ValueError(f"unsupported tracking controller type: {controller_type!r}")
