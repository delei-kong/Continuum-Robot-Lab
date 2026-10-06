"""Constrained receding-horizon control over a persisted Koopman model.

This module has no SOFA dependency.  It optimizes direct cable-displacement
commands in millimetres, while the persisted EDMDc model evolves its lifted,
normalized state.  The only tracked output is the measured tip position; the
full 79-dimensional state remains the model input at every receding-horizon
step.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np

from modeling.koopman_dataset import ACTION_COLUMNS, CENTERLINE_POINT_COUNT, STATE_COLUMNS
from modeling.koopman_model import TrainedDynamicsModel


_TIP_INDICES = np.asarray(
    [STATE_COLUMNS.index(column) for column in ("tip_x_mm", "tip_y_mm", "tip_z_mm")],
    dtype=int,
)


def _finite_positive(value: float, label: str) -> float:
    result = float(value)
    if not isfinite(result) or result <= 0.0:
        raise ValueError(f"{label} must be finite and positive")
    return result


def _finite_nonnegative(value: float, label: str) -> float:
    result = float(value)
    if not isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _finite_vector(
    values: Sequence[float], *, count: int, label: str, positive: bool | None
) -> np.ndarray:
    if len(values) != count:
        raise ValueError(f"{label} must contain {count} values")
    result = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{label} must contain finite values")
    if positive is True and np.any(result <= 0.0):
        raise ValueError(f"{label} must contain positive values")
    if positive is False and np.any(result < 0.0):
        raise ValueError(f"{label} must contain non-negative values")
    return result


def koopman_state_from_observation(
    cable_displacements_mm: Sequence[float],
    cable_forces: Sequence[float],
    tip_position_mm: Sequence[float],
    centerline_positions_mm: Sequence[Sequence[float]],
    centerline_velocities_mm_s: Sequence[Sequence[float]],
) -> tuple[float, ...]:
    """Assemble a live state using exactly the dataset's persisted column order."""

    cable_displacements = _finite_vector(
        cable_displacements_mm,
        count=len(ACTION_COLUMNS),
        label="cable displacements",
        positive=None,
    )
    cable_force_values = _finite_vector(
        cable_forces,
        count=len(ACTION_COLUMNS),
        label="cable forces",
        positive=None,
    )
    tip = _finite_vector(tip_position_mm, count=3, label="tip position", positive=None)
    if (
        len(centerline_positions_mm) != CENTERLINE_POINT_COUNT
        or len(centerline_velocities_mm_s) != CENTERLINE_POINT_COUNT
    ):
        raise ValueError(
            "centerline observations must contain the configured position and velocity points"
        )
    state: list[float] = []
    for displacement, force in zip(cable_displacements, cable_force_values):
        state.extend((float(displacement), float(force)))
    state.extend(float(value) for value in tip)
    for position, velocity in zip(centerline_positions_mm, centerline_velocities_mm_s):
        # STATE_COLUMNS stores all Cartesian position axes before all velocity axes.
        state.extend(_finite_vector(position, count=3, label="centerline position", positive=None))
        state.extend(_finite_vector(velocity, count=3, label="centerline velocity", positive=None))
    if len(state) != len(STATE_COLUMNS):
        raise ValueError("assembled Koopman state does not match the dataset dimension")
    return tuple(state)


@dataclass(frozen=True)
class KoopmanMpcConfig:
    """Fixed, registered parameters for one physical-unit K-MPC controller."""

    horizon_steps: int
    tip_position_weights: tuple[float, float, float]
    terminal_weight_scale: float
    action_weight: float
    action_delta_weight: float
    projected_gradient_iterations: int
    maximum_displacements_mm: tuple[float, ...]
    max_command_delta_mm: float

    def __post_init__(self) -> None:
        if isinstance(self.horizon_steps, bool) or self.horizon_steps < 1:
            raise ValueError("MPC horizon_steps must be a positive integer")
        _finite_vector(
            self.tip_position_weights,
            count=3,
            label="MPC tip_position_weights",
            positive=True,
        )
        _finite_positive(self.terminal_weight_scale, "MPC terminal_weight_scale")
        _finite_nonnegative(self.action_weight, "MPC action_weight")
        _finite_nonnegative(self.action_delta_weight, "MPC action_delta_weight")
        if self.action_weight == 0.0 and self.action_delta_weight == 0.0:
            raise ValueError("MPC needs a positive action or action-delta weight")
        if (
            isinstance(self.projected_gradient_iterations, bool)
            or self.projected_gradient_iterations < 1
        ):
            raise ValueError("MPC projected_gradient_iterations must be a positive integer")
        maxima = _finite_vector(
            self.maximum_displacements_mm,
            count=len(ACTION_COLUMNS),
            label="MPC maximum_displacements_mm",
            positive=True,
        )
        if np.any(maxima <= 0.0):  # Kept explicit for a clearer future error if validation changes.
            raise ValueError("MPC cable maxima must be positive")
        _finite_positive(self.max_command_delta_mm, "MPC max_command_delta_mm")

    @property
    def action_dimension(self) -> int:
        return len(ACTION_COLUMNS)


@dataclass(frozen=True)
class KoopmanMpcResult:
    """First feasible action and solver diagnostics for one receding-horizon step."""

    action_mm: tuple[float, ...]
    objective: float
    projected_gradient_norm: float
    predicted_initial_error_mm: float
    predicted_terminal_error_mm: float
    iterations: int


class KoopmanMpcController:
    """Projected-gradient QP solver for fixed-lift Koopman dynamics.

    The lifted model is linear once the current physical state has been lifted:

    ``z[k+1] = A z[k] + B u[k] + c``.

    The decision variable remains the physical cable command in millimetres.
    Box and inter-step slew constraints are enforced by a sequential projection,
    including the link from the first horizon action to the actually applied
    previous command.
    """

    def __init__(self, model: TrainedDynamicsModel, config: KoopmanMpcConfig) -> None:
        if model.lift.state_dimension != len(STATE_COLUMNS):
            raise ValueError("Koopman model state dimension does not match the dataset contract")
        if model.action_transition.shape != (len(ACTION_COLUMNS), model.lift.feature_dimension):
            raise ValueError("Koopman model action dimension does not match the dataset contract")
        self.model = model
        self.config = config
        self._horizon = config.horizon_steps
        self._state_dimension = len(STATE_COLUMNS)
        self._lift_dimension = model.lift.feature_dimension
        self._action_dimension = len(ACTION_COLUMNS)
        self._maxima = np.asarray(config.maximum_displacements_mm, dtype=np.float64)
        self._weights = np.asarray(config.tip_position_weights, dtype=np.float64)
        self._previous_action = np.zeros(self._action_dimension, dtype=np.float64)
        self._warm_start: np.ndarray | None = None
        self._dynamics_a, self._dynamics_b, self._dynamics_bias = self._column_dynamics()
        self._prediction_matrix = self._build_prediction_matrix()
        self._tip_output = self._build_tip_output_matrix()
        self._tip_selector = self._build_tip_selector()
        self._output_map = self._tip_selector @ self._prediction_matrix
        self._tip_offset = np.tile(
            self.model.normalization.state_mean[_TIP_INDICES], self._horizon
        )
        self._tracking_weights = np.tile(self._weights, self._horizon)
        self._tracking_weights[-3:] *= self.config.terminal_weight_scale
        self._difference = self._build_difference_operator()
        identity = np.eye(self._horizon * self._action_dimension)
        self._hessian = 2.0 * (
            self._output_map.T @ (self._output_map * self._tracking_weights[:, np.newaxis])
            + self.config.action_weight * identity
            + self.config.action_delta_weight * (self._difference.T @ self._difference)
        )
        self._gradient_step = self._projected_gradient_step(self._hessian)

    def _column_dynamics(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Convert persisted row-vector normalized dynamics to physical-action columns."""

        action_scale = self.model.normalization.action_scale
        action_mean = self.model.normalization.action_mean
        a = np.asarray(self.model.lift_transition, dtype=np.float64).T
        b_normalized = np.asarray(self.model.action_transition, dtype=np.float64).T
        b = b_normalized / action_scale[np.newaxis, :]
        bias = np.asarray(self.model.bias, dtype=np.float64) - b_normalized @ (
            action_mean / action_scale
        )
        if not all(np.all(np.isfinite(values)) for values in (a, b, bias)):
            raise ValueError("Koopman model contains non-finite dynamics coefficients")
        return a, b, bias

    def _build_prediction_matrix(self) -> np.ndarray:
        """Map stacked physical actions to stacked lifted future states."""

        result = np.zeros(
            (self._horizon * self._lift_dimension, self._horizon * self._action_dimension),
            dtype=np.float64,
        )
        powers = [np.eye(self._lift_dimension, dtype=np.float64)]
        for _ in range(self._horizon):
            powers.append(powers[-1] @ self._dynamics_a)
        for future_step in range(self._horizon):
            output_rows = slice(
                future_step * self._lift_dimension, (future_step + 1) * self._lift_dimension
            )
            for command_step in range(future_step + 1):
                input_cols = slice(
                    command_step * self._action_dimension,
                    (command_step + 1) * self._action_dimension,
                )
                result[output_rows, input_cols] = powers[future_step - command_step] @ self._dynamics_b
        return result

    def _build_tip_output_matrix(self) -> np.ndarray:
        result = np.zeros((3, self._lift_dimension), dtype=np.float64)
        result[np.arange(3), _TIP_INDICES] = self.model.normalization.state_scale[_TIP_INDICES]
        return result

    def _build_tip_selector(self) -> np.ndarray:
        selector = np.zeros((self._horizon * 3, self._horizon * self._lift_dimension))
        for index in range(self._horizon):
            selector[
                index * 3 : (index + 1) * 3,
                index * self._lift_dimension : (index + 1) * self._lift_dimension,
            ] = self._tip_output
        return selector

    def reset(self, previous_action_mm: Sequence[float] | None = None) -> None:
        """Clear warm-start state and declare the applied action before step zero."""

        if previous_action_mm is None:
            action = np.zeros(self._action_dimension, dtype=np.float64)
        else:
            action = _finite_vector(
                previous_action_mm,
                count=self._action_dimension,
                label="previous MPC action",
                positive=False,
            )
        if np.any(action > self._maxima):
            raise ValueError("previous MPC action exceeds configured cable bounds")
        self._previous_action = action
        self._warm_start = None

    def commit_applied_action(self, action_mm: Sequence[float]) -> None:
        """Record the command that actually reached the plant after safety projection."""

        action = _finite_vector(
            action_mm,
            count=self._action_dimension,
            label="applied MPC action",
            positive=False,
        )
        if np.any(action > self._maxima):
            raise ValueError("applied MPC action exceeds configured cable bounds")
        if np.any(np.abs(action - self._previous_action) > self.config.max_command_delta_mm + 1e-9):
            raise ValueError("applied MPC action exceeds configured slew bounds")
        self._previous_action = action

    def compute(
        self,
        state: Sequence[float],
        future_tip_references_mm: Sequence[Sequence[float]],
    ) -> KoopmanMpcResult:
        """Optimize one feasible action and retain a shifted feasible warm start."""

        current_state = _finite_vector(
            state, count=self._state_dimension, label="MPC state", positive=None
        )
        if len(future_tip_references_mm) != self._horizon:
            raise ValueError("MPC reference sequence length must equal its horizon")
        references = np.asarray(future_tip_references_mm, dtype=np.float64)
        if references.shape != (self._horizon, 3) or not np.all(np.isfinite(references)):
            raise ValueError("MPC references must be finite 3-D points")

        initial_lift = self.model.lift.lift(
            self.model.normalization.normalize_state(current_state)
        )[0]
        base_prediction = self._base_prediction(initial_lift)
        output_offset = self._tip_selector @ base_prediction + self._tip_offset
        stacked_reference = references.reshape(-1)
        decision = self._initial_decision()
        linear = self._linear_term(output_offset, stacked_reference)
        gradient_norm = 0.0
        for _ in range(self.config.projected_gradient_iterations):
            gradient = self._hessian @ decision + linear
            gradient_norm = float(np.linalg.norm(gradient))
            decision = self._project_actions(decision - self._gradient_step * gradient)
        predicted_tips = (self._output_map @ decision + output_offset).reshape(self._horizon, 3)
        objective = self._objective(
            decision, output_offset, stacked_reference
        )
        self._warm_start = np.concatenate(
            (decision[self._action_dimension :], decision[-self._action_dimension :])
        )
        first_action = decision[: self._action_dimension]
        return KoopmanMpcResult(
            action_mm=tuple(float(value) for value in first_action),
            objective=objective,
            projected_gradient_norm=gradient_norm,
            predicted_initial_error_mm=float(np.linalg.norm(predicted_tips[0] - references[0])),
            predicted_terminal_error_mm=float(np.linalg.norm(predicted_tips[-1] - references[-1])),
            iterations=self.config.projected_gradient_iterations,
        )

    def _base_prediction(self, initial_lift: np.ndarray) -> np.ndarray:
        states: list[np.ndarray] = []
        current = initial_lift
        for _ in range(self._horizon):
            current = self._dynamics_a @ current + self._dynamics_bias
            states.append(current)
        return np.concatenate(states)

    def _linear_term(self, output_offset: np.ndarray, reference: np.ndarray) -> np.ndarray:
        linear = 2.0 * self._output_map.T @ (
            self._tracking_weights * (output_offset - reference)
        )
        previous = np.zeros(self._horizon * self._action_dimension, dtype=np.float64)
        previous[: self._action_dimension] = self._previous_action
        return linear - 2.0 * self.config.action_delta_weight * (self._difference.T @ previous)

    def _build_difference_operator(self) -> np.ndarray:
        dimension = self._horizon * self._action_dimension
        difference = np.eye(dimension, dtype=np.float64)
        for step in range(1, self._horizon):
            row = slice(step * self._action_dimension, (step + 1) * self._action_dimension)
            previous = slice((step - 1) * self._action_dimension, step * self._action_dimension)
            difference[row, previous] = -np.eye(self._action_dimension)
        return difference

    def _projected_gradient_step(self, hessian: np.ndarray) -> float:
        largest = float(np.linalg.eigvalsh(hessian)[-1])
        if not isfinite(largest) or largest <= 0.0:
            raise ValueError("MPC objective does not have a finite positive Lipschitz constant")
        return 1.0 / largest

    def _initial_decision(self) -> np.ndarray:
        if self._warm_start is None:
            candidate = np.tile(self._previous_action, self._horizon)
        else:
            candidate = self._warm_start.copy()
        return self._project_actions(candidate)

    def _project_actions(self, decision: np.ndarray) -> np.ndarray:
        projected = np.asarray(decision, dtype=np.float64).reshape(
            self._horizon, self._action_dimension
        ).copy()
        previous = self._previous_action
        for step in range(self._horizon):
            lower = np.maximum(0.0, previous - self.config.max_command_delta_mm)
            upper = np.minimum(self._maxima, previous + self.config.max_command_delta_mm)
            projected[step] = np.minimum(np.maximum(projected[step], lower), upper)
            previous = projected[step]
        return projected.reshape(-1)

    def _objective(
        self,
        decision: np.ndarray,
        output_offset: np.ndarray,
        reference: np.ndarray,
    ) -> float:
        error = self._output_map @ decision + output_offset - reference
        previous = np.zeros(self._horizon * self._action_dimension, dtype=np.float64)
        previous[: self._action_dimension] = self._previous_action
        delta = self._difference @ decision - previous
        value = (
            float(np.dot(self._tracking_weights * error, error))
            + self.config.action_weight * float(np.dot(decision, decision))
            + self.config.action_delta_weight * float(np.dot(delta, delta))
        )
        if not isfinite(value):
            raise ValueError("MPC objective became non-finite")
        return value
