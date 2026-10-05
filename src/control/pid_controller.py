"""Conservative task-space PID controller for the inverse-QP tracking backend."""

from __future__ import annotations

from math import isfinite, sqrt
from typing import Mapping

from control.tracking_contracts import (
    ControllerContext,
    ControllerOutput,
    TaskSpaceGoalCommand,
    TrackingObservation,
    TrajectoryReference,
    Vec3,
    finite_vec3,
)


def _scaled_sum(left: Vec3, right: Vec3, scale: float) -> Vec3:
    return tuple(a + scale * b for a, b in zip(left, right))  # type: ignore[return-value]


def _norm(value: Vec3) -> float:
    return sqrt(sum(axis * axis for axis in value))


class TaskSpacePIDController:
    """Apply PID error feedback to a task-space reference goal.

    The controller is intentionally an outer loop: the resulting task-space goal
    is still solved by the official SOFA inverse-QP backend. Integral state and
    derivative state are reset at trajectory phase boundaries to avoid carrying
    the settle transient into the tracking phase.
    """

    def __init__(
        self,
        *,
        kp: Vec3 = (0.02, 0.02, 0.02),
        ki: Vec3 = (0.0, 0.0, 0.0),
        kd: Vec3 = (0.0, 0.0, 0.0),
        integral_limit_mm_s: Vec3 = (20.0, 20.0, 20.0),
        max_correction_mm: float = 2.0,
    ) -> None:
        self.kp = finite_vec3(kp, "PID proportional gain")
        self.ki = finite_vec3(ki, "PID integral gain")
        self.kd = finite_vec3(kd, "PID derivative gain")
        self.integral_limit_mm_s = finite_vec3(
            integral_limit_mm_s, "PID integral limit"
        )
        if any(gain < 0.0 for gain in (*self.kp, *self.ki, *self.kd)):
            raise ValueError("PID gains must be non-negative")
        if any(limit <= 0.0 for limit in self.integral_limit_mm_s):
            raise ValueError("PID integral limits must be positive")
        if not isfinite(max_correction_mm) or max_correction_mm <= 0.0:
            raise ValueError("PID maximum correction must be finite and positive")
        self.max_correction_mm = float(max_correction_mm)
        self._ready = False
        self._dt_s = 0.0
        self._integral_error: Vec3 = (0.0, 0.0, 0.0)
        self._previous_error: Vec3 | None = None
        self._previous_phase: str | None = None

    def reset(self, context: ControllerContext) -> None:
        if "task_space_goal" not in context.supported_command_kinds:
            raise ValueError("backend does not support task-space goal commands")
        self._dt_s = context.dt_s
        self._integral_error = (0.0, 0.0, 0.0)
        self._previous_error = None
        self._previous_phase = None
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

        error = tuple(
            target - actual
            for target, actual in zip(reference.position_mm, observation.tip_position_mm)
        )  # type: ignore[assignment]
        phase_changed = reference.phase != self._previous_phase
        if phase_changed:
            self._integral_error = (0.0, 0.0, 0.0)
            derivative = (0.0, 0.0, 0.0)
        else:
            self._integral_error = tuple(
                max(
                    -limit,
                    min(limit, integral + error_axis * dt_s),
                )
                for integral, error_axis, limit in zip(
                    self._integral_error, error, self.integral_limit_mm_s
                )
            )  # type: ignore[assignment]
            previous_error = self._previous_error
            if previous_error is None:
                derivative = (0.0, 0.0, 0.0)
            else:
                derivative = tuple(
                    (current - previous) / dt_s
                    for current, previous in zip(error, previous_error)
                )  # type: ignore[assignment]

        correction = tuple(
            kp * error_axis + ki * integral + kd * derivative_axis
            for kp, ki, kd, error_axis, integral, derivative_axis in zip(
                self.kp, self.ki, self.kd, error, self._integral_error, derivative
            )
        )  # type: ignore[assignment]
        correction_norm = _norm(correction)
        if correction_norm > self.max_correction_mm:
            scale = self.max_correction_mm / correction_norm
            correction = tuple(scale * axis for axis in correction)  # type: ignore[assignment]
            correction_norm = self.max_correction_mm

        goal = _scaled_sum(reference.position_mm, correction, 1.0)
        self._previous_error = error
        self._previous_phase = reference.phase
        diagnostics = {
            "reference_lead_s": reference.time_s - observation.time_s,
            "pid_error_norm_mm": _norm(error),
            "pid_integral_norm_mm_s": _norm(self._integral_error),
            "pid_derivative_norm_mm_s": _norm(derivative),
            "pid_correction_norm_mm": correction_norm,
            "pid_correction_x_mm": correction[0],
            "pid_correction_y_mm": correction[1],
            "pid_correction_z_mm": correction[2],
        }
        return ControllerOutput(
            command=TaskSpaceGoalCommand(goal), diagnostics=diagnostics
        )

    def finalize(self) -> None:
        self._ready = False
        self._dt_s = 0.0
        self._integral_error = (0.0, 0.0, 0.0)
        self._previous_error = None
        self._previous_phase = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "TaskSpacePIDController":
        return cls(
            kp=_mapping_vec3(values, "kp", (0.02, 0.02, 0.02)),
            ki=_mapping_vec3(values, "ki", (0.0, 0.0, 0.0)),
            kd=_mapping_vec3(values, "kd", (0.0, 0.0, 0.0)),
            integral_limit_mm_s=_mapping_vec3(
                values, "integral_limit_mm_s", (20.0, 20.0, 20.0)
            ),
            max_correction_mm=float(values.get("max_correction_mm", 2.0)),
        )


def _mapping_vec3(values: Mapping[str, object], name: str, default: Vec3) -> Vec3:
    raw = values.get(name, default)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return finite_vec3((float(raw), float(raw), float(raw)), f"PID {name}")
    if isinstance(raw, (list, tuple)):
        return finite_vec3(tuple(raw), f"PID {name}")
    raise ValueError(f"PID {name} must be a scalar or three-value sequence")
