"""Controller- and trajectory-agnostic experiment orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from math import dist, isfinite
from time import perf_counter
from typing import Protocol

from control.tracking_contracts import (
    ControlCommand,
    ControllerContext,
    TrackingController,
    TrackingObservation,
)
from evaluation.recording import TrackingRecorder, TrackingStepRecord
from simulation.trajectory import Trajectory


class TrackingBackend(Protocol):
    @property
    def controller_context(self) -> ControllerContext: ...

    def reset(self, seed: int) -> TrackingObservation: ...

    def step(self, command: ControlCommand, dt_s: float) -> TrackingObservation: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class TrackingExperimentConfig:
    dt_s: float
    duration_s: float
    seed: int

    def __post_init__(self) -> None:
        if not isfinite(self.dt_s) or self.dt_s <= 0.0:
            raise ValueError("experiment dt must be finite and positive")
        if not isfinite(self.duration_s) or self.duration_s <= 0.0:
            raise ValueError("experiment duration must be finite and positive")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("experiment seed must be an integer")

    @property
    def total_steps(self) -> int:
        steps = round(self.duration_s / self.dt_s)
        if abs(steps * self.dt_s - self.duration_s) > 1e-9:
            raise ValueError("experiment duration must be an integer multiple of dt")
        return steps


class TrackingExperimentRunner:
    """Compose one trajectory, controller, backend, and recorder."""

    def __init__(
        self,
        *,
        trajectory: Trajectory,
        controller: TrackingController,
        backend: TrackingBackend,
        recorder: TrackingRecorder,
    ) -> None:
        self.trajectory = trajectory
        self.controller = controller
        self.backend = backend
        self.recorder = recorder

    def run(self, config: TrackingExperimentConfig) -> tuple[TrackingStepRecord, ...]:
        if abs(self.backend.controller_context.dt_s - config.dt_s) > 1e-9:
            raise ValueError("backend and experiment dt must match")
        if config.duration_s > self.trajectory.duration_s + 1e-9:
            raise ValueError("experiment duration exceeds trajectory duration")

        self.recorder.reset()
        self.trajectory.reset(config.seed)
        observation = self.backend.reset(config.seed)
        self.controller.reset(self.backend.controller_context)
        try:
            for step in range(config.total_steps):
                sample_time_s = (step + 1) * config.dt_s
                reference = self.trajectory.sample(sample_time_s)
                period_started_at = perf_counter()
                controller_started_at = period_started_at
                output = self.controller.compute(observation, reference, config.dt_s)
                controller_wall_ms = (perf_counter() - controller_started_at) * 1000.0
                backend_started_at = perf_counter()
                observation = self.backend.step(output.command, config.dt_s)
                backend_wall_ms = (perf_counter() - backend_started_at) * 1000.0
                control_period_wall_ms = (perf_counter() - period_started_at) * 1000.0
                error_norm_mm = dist(reference.position_mm, observation.tip_position_mm)
                self.recorder.append(
                    TrackingStepRecord(
                        step=step,
                        time_s=sample_time_s,
                        reference=reference,
                        observation=observation,
                        controller_output=output,
                        tracking_error_norm_mm=error_norm_mm,
                        controller_wall_ms=controller_wall_ms,
                        backend_wall_ms=backend_wall_ms,
                        control_period_wall_ms=control_period_wall_ms,
                    )
                )
        finally:
            self.controller.finalize()
            self.backend.close()
        return self.recorder.finalize()
