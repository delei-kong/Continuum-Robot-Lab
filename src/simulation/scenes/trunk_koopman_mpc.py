"""Direct-cable SOFA tracking scene driven by a frozen Koopman-MPC controller."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, NamedTuple

import Sofa.Core


PROJECT_ROOT = Path(__file__).resolve().parents[3]
from control.koopman_mpc_controller import (  # noqa: E402
    KoopmanMpcConfig,
    KoopmanMpcController,
    koopman_state_from_observation,
)
from control.tracking_contracts import (  # noqa: E402
    CableDisplacementCommand,
    ControllerOutput,
    TrackingObservation,
)
from evaluation.recording import InMemoryTrackingRecorder, TrackingStepRecord  # noqa: E402
from evaluation.tracking_metrics import write_tracking_artifacts  # noqa: E402
from modeling.koopman_dataset import CENTERLINE_POINT_COUNT  # noqa: E402
from modeling.koopman_model import load_finalized_koopman_model  # noqa: E402
from simulation.forward_data import CABLE_NAMES, CableActionSafetyLayer  # noqa: E402
from simulation.scenes.trunk_common import create_forward_observed_trunk  # noqa: E402
from simulation.tracking_pipeline import TrackingExperimentConfig  # noqa: E402
from simulation.trajectory import (  # noqa: E402
    Trajectory,
    polyline_tube_geometry,
    sample_trajectory_polyline,
    trajectory_from_mapping,
)


def _scalar_data(data: Any) -> float:
    value = data.value
    while isinstance(value, (list, tuple)):
        if not value:
            return math.nan
        value = value[0]
    return float(value)


class _PendingStep(NamedTuple):
    step: int
    time_s: float
    reference: Any
    observation: TrackingObservation
    output: ControllerOutput
    error_norm_mm: float
    controller_wall_ms: float
    backend_wall_ms: float


def _load_config() -> tuple[dict[str, Any], Path]:
    default_path = PROJECT_ROOT / "configs" / "trunk_koopman_mpc_line.json"
    config_path = Path(os.environ.get("TRUNK_KOOPMAN_MPC_CONFIG", default_path)).resolve()
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("tracking_mode") != "koopman_mpc_tracking":
        raise ValueError("K-MPC scene requires tracking_mode=koopman_mpc_tracking")
    return payload, config_path


def _mpc_config(raw: dict[str, Any]) -> KoopmanMpcConfig:
    controller = raw.get("controller")
    safety = raw.get("action_safety")
    if not isinstance(controller, dict) or not isinstance(safety, dict):
        raise ValueError("K-MPC controller and action_safety configurations are required")
    if controller.get("type") != "koopman_mpc":
        raise ValueError("K-MPC scene requires controller.type=koopman_mpc")
    weights = controller.get("tip_position_weights")
    maxima = safety.get("maximum_displacements_mm")
    if not isinstance(weights, list) or not isinstance(maxima, list):
        raise ValueError("K-MPC weights and cable limits must be lists")
    return KoopmanMpcConfig(
        horizon_steps=int(controller["horizon_steps"]),
        tip_position_weights=tuple(float(value) for value in weights),  # type: ignore[arg-type]
        terminal_weight_scale=float(controller["terminal_weight_scale"]),
        action_weight=float(controller["action_weight"]),
        action_delta_weight=float(controller["action_delta_weight"]),
        projected_gradient_iterations=int(controller["projected_gradient_iterations"]),
        maximum_displacements_mm=tuple(float(value) for value in maxima),
        max_command_delta_mm=float(safety["max_command_delta_mm"]),
    )


class TrunkKoopmanMpcController(Sofa.Core.Controller):
    """Synchronize direct SOFA state feedback, K-MPC optimization and recording."""

    def __init__(
        self,
        *,
        trunk: Any,
        tip_dofs: Any,
        centerline_dofs: Any,
        reference_dofs: Any,
        tip_monitor: Any,
        start_marker: Any,
        trajectory: Trajectory,
        experiment: TrackingExperimentConfig,
        controller: KoopmanMpcController,
        safety: CableActionSafetyLayer,
        run_dir: Path,
        deadline_ms: float,
        warmup_steps: int,
        plant_settle_steps: int,
    ) -> None:
        Sofa.Core.Controller.__init__(self)
        self.trunk = trunk
        self.tip_dofs = tip_dofs
        self.centerline_dofs = centerline_dofs
        self.reference_dofs = reference_dofs
        self.tip_monitor = tip_monitor
        self.start_marker = start_marker
        self.trajectory = trajectory
        self.experiment = experiment
        self.controller = controller
        self.safety = safety
        self.run_dir = run_dir
        self.deadline_ms = deadline_ms
        self.warmup_steps = warmup_steps
        self.plant_settle_steps = plant_settle_steps
        self.trajectory_visualization_started = False
        self.recorder = InMemoryTrackingRecorder()
        self.step = 0
        self.previous_step_started_at: float | None = None
        self.backend_started_at = 0.0
        self.pending: _PendingStep | None = None
        self.active_reference: Any | None = None
        self.active_output: ControllerOutput | None = None
        self.controller_wall_ms = 0.0
        self.finalized = False
        self.trajectory.reset(experiment.seed)
        initial_action = self._cable_measurements()[0]
        self.controller.reset(initial_action)
        self.recorder.reset()
        print(
            "[KoopmanMPC] initialized "
            f"model={self.controller.model.name} dt={experiment.dt_s:.3f}s "
            f"steps={experiment.total_steps} settle_steps={plant_settle_steps} "
            f"horizon={self.controller.config.horizon_steps}"
        )

    def _cable_measurements(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        displacements: list[float] = []
        forces: list[float] = []
        for cable_name in CABLE_NAMES:
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            displacements.append(_scalar_data(cable.displacement))
            forces.append(_scalar_data(cable.force))
        return tuple(displacements), tuple(forces)

    def _state_and_observation(self, time_s: float) -> tuple[tuple[float, ...], TrackingObservation]:
        cable_displacements, cable_forces = self._cable_measurements()
        tip = tuple(float(axis) for axis in self.tip_dofs.position.value[0])
        positions = self.centerline_dofs.position.value
        velocities = self.centerline_dofs.velocity.value
        if len(positions) != CENTERLINE_POINT_COUNT or len(velocities) != CENTERLINE_POINT_COUNT:
            raise RuntimeError("K-MPC centerline observation does not match the Koopman state contract")
        try:
            state = koopman_state_from_observation(
                cable_displacements,
                cable_forces,
                tip,
                positions,
                velocities,
            )
        except ValueError as error:
            raise RuntimeError("K-MPC observed a non-finite or malformed Koopman state") from error
        return state, TrackingObservation(
            time_s=time_s,
            tip_position_mm=tip,  # type: ignore[arg-type]
            cable_displacements_mm=cable_displacements,
            cable_forces_mn=cable_forces,
        )

    def _apply_action(self, action_mm: tuple[float, ...]) -> None:
        for cable_name, command in zip(CABLE_NAMES, action_mm):
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            cable.value = [command]

    def _start_actual_trajectory_visualization(
        self, tip_position_mm: tuple[float, float, float]
    ) -> None:
        """Enable the validated SofaValidation Monitor after physical settling."""

        if self.trajectory_visualization_started or self.step + 1 != self.plant_settle_steps:
            return
        self.start_marker.position.value = [list(tip_position_mm)]
        self.start_marker.showObject.value = True
        self.tip_monitor.listening.value = True
        self.trajectory_visualization_started = True
        print(
            "[KoopmanMPC] actual trajectory visualization started "
            f"at t={(self.step + 1) * self.experiment.dt_s:.2f}s tip={tip_position_mm}"
        )

    def _append_pending(self, control_period_wall_ms: float | None) -> None:
        if self.pending is None:
            return
        pending = self.pending
        self.recorder.append(
            TrackingStepRecord(
                step=pending.step,
                time_s=pending.time_s,
                reference=pending.reference,
                observation=pending.observation,
                controller_output=pending.output,
                tracking_error_norm_mm=pending.error_norm_mm,
                controller_wall_ms=pending.controller_wall_ms,
                backend_wall_ms=pending.backend_wall_ms,
                control_period_wall_ms=control_period_wall_ms,
            )
        )
        self.pending = None

    def onAnimateBeginEvent(self, _event: Any) -> None:
        if self.step >= self.experiment.total_steps:
            return
        started_at = time.perf_counter()
        if self.previous_step_started_at is not None:
            self._append_pending((started_at - self.previous_step_started_at) * 1000.0)
        self.previous_step_started_at = started_at
        sample_time_s = (self.step + 1) * self.experiment.dt_s
        self.active_reference = self.trajectory.sample(sample_time_s)
        self.reference_dofs.position.value = [list(self.active_reference.position_mm)]
        controller_started_at = time.perf_counter()
        if self.step < self.plant_settle_steps:
            projection = self.safety.project((0.0,) * len(CABLE_NAMES))
            diagnostics = {
                "mpc_warmup": 1.0,
                "mpc_objective": 0.0,
                "mpc_projected_gradient_norm": 0.0,
                "mpc_predicted_initial_error_mm": 0.0,
                "mpc_predicted_terminal_error_mm": 0.0,
                "mpc_iterations": 0.0,
                "mpc_command_limited": float(projection.limited),
            }
        else:
            state, _observation = self._state_and_observation(self.step * self.experiment.dt_s)
            future_references = tuple(
                self.trajectory.sample(sample_time_s + offset * self.experiment.dt_s).position_mm
                for offset in range(self.controller.config.horizon_steps)
            )
            result = self.controller.compute(state, future_references)
            projection = self.safety.project(result.action_mm)
            diagnostics = {
                "mpc_warmup": 0.0,
                "mpc_objective": result.objective,
                "mpc_projected_gradient_norm": result.projected_gradient_norm,
                "mpc_predicted_initial_error_mm": result.predicted_initial_error_mm,
                "mpc_predicted_terminal_error_mm": result.predicted_terminal_error_mm,
                "mpc_iterations": float(result.iterations),
                "mpc_command_limited": float(projection.limited),
            }
        self.controller.commit_applied_action(projection.applied_mm)
        self.controller_wall_ms = (time.perf_counter() - controller_started_at) * 1000.0
        self.active_output = ControllerOutput(
            command=CableDisplacementCommand(projection.applied_mm),
            diagnostics=diagnostics,
        )
        self._apply_action(projection.applied_mm)
        self.backend_started_at = time.perf_counter()

    def onAnimateEndEvent(self, _event: Any) -> None:
        if self.step >= self.experiment.total_steps or self.active_reference is None or self.active_output is None:
            return
        backend_wall_ms = (time.perf_counter() - self.backend_started_at) * 1000.0
        _state, observation = self._state_and_observation(self.active_reference.time_s)
        self._start_actual_trajectory_visualization(observation.tip_position_mm)
        error_norm_mm = math.dist(self.active_reference.position_mm, observation.tip_position_mm)
        self.pending = _PendingStep(
            step=self.step,
            time_s=self.active_reference.time_s,
            reference=self.active_reference,
            observation=observation,
            output=self.active_output,
            error_norm_mm=error_norm_mm,
            controller_wall_ms=self.controller_wall_ms,
            backend_wall_ms=backend_wall_ms,
        )
        self.step += 1
        if self.step == self.experiment.total_steps:
            self._finalize()

    def onCleanupEvent(self, _event: Any) -> None:
        self._finalize()

    def _finalize(self) -> None:
        if self.finalized:
            return
        self.finalized = True
        self._append_pending(None)
        self._apply_action((0.0,) * len(CABLE_NAMES))
        records = self.recorder.finalize()
        if not records:
            return
        summary = write_tracking_artifacts(
            self.run_dir,
            records,
            deadline_ms=self.deadline_ms,
            warmup_steps=self.warmup_steps,
        )
        print(
            "[KoopmanMPC] completed "
            f"rows={len(records)} rmse={summary['tracking']['rmse_norm_mm']:.3f}mm "
            f"period_p99={summary['timing']['control_period']['p99_ms']:.3f}ms"
        )


def createScene(root_node: Any) -> Any:
    raw_config, config_path = _load_config()
    dt_s = float(raw_config["dt"])
    if abs(dt_s * float(raw_config["control_rate_hz"]) - 1.0) > 1e-9:
        raise ValueError("one simulation step must equal one K-MPC control period")
    experiment = TrackingExperimentConfig(
        dt_s=dt_s,
        duration_s=float(raw_config["duration_s"]),
        seed=int(raw_config["seed"]),
    )
    trajectory_config = raw_config.get("trajectory")
    model_config = raw_config.get("model")
    if not isinstance(trajectory_config, dict) or not isinstance(model_config, dict):
        raise ValueError("K-MPC trajectory and model configurations are required")
    if trajectory_config.get("type") not in {
        "timed_linear",
        "periodic_ellipse",
        "periodic_catmull_rom",
    }:
        raise ValueError("K-MPC trajectory type is unsupported")
    trajectory = trajectory_from_mapping(trajectory_config)
    if abs(trajectory.duration_s - experiment.duration_s) > 1e-9:
        raise ValueError("K-MPC trajectory and experiment duration must match")
    plant_settle_steps = int(raw_config["plant_settle_steps"])
    if (
        plant_settle_steps < 1
        or plant_settle_steps >= experiment.total_steps
        or abs(plant_settle_steps * dt_s - float(trajectory_config["settle_duration_s"])) > 1e-9
    ):
        raise ValueError("K-MPC physical settle steps must match the trajectory settle duration")
    mpc = KoopmanMpcController(
        load_finalized_koopman_model(PROJECT_ROOT, str(model_config.get("final_output_id", ""))),
        _mpc_config(raw_config),
    )
    safety = CableActionSafetyLayer(
        mpc.config.maximum_displacements_mm, mpc.config.max_command_delta_mm
    )
    if len(raw_config.get("centerline_z_mm", ())) != CENTERLINE_POINT_COUNT:
        raise ValueError("K-MPC centerline probes must match the Koopman state contract")
    run_dir = Path(
        os.environ.get("TRUNK_RUN_DIR", PROJECT_ROOT / "outputs" / "trunk_koopman_mpc_manual")
    ).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(raw_config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    with (run_dir / "model_provenance.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "final_output_id": model_config["final_output_id"],
                "selected_model": mpc.model.name,
                "lift": mpc.model.lift.kind,
                "lift_dimension": mpc.model.lift.feature_dimension,
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )
        handle.write("\n")

    observed = create_forward_observed_trunk(root_node, raw_config)
    reference_node = root_node.addChild("ReferencePoint")
    reference_dofs = reference_node.addObject(
        "MechanicalObject",
        name="dofs",
        position=[list(trajectory.start_mm)],
        showObject=True,
        showObjectScale=float(raw_config["reference_marker_scale_mm"]),
        showColor=[0.15, 1.0, 0.3, 1.0],
    )
    reference_positions, _reference_edges = sample_trajectory_polyline(
        trajectory, int(raw_config["reference_path_samples"])
    )
    reference_vertices, reference_quads = polyline_tube_geometry(
        reference_positions,
        float(raw_config["reference_path_radius_mm"]),
        int(raw_config["reference_path_radial_segments"]),
    )
    reference_visual = root_node.addChild("ReferenceTrajectoryVisual")
    reference_visual.addObject(
        "OglModel",
        name="referencePath",
        position=reference_vertices,
        quads=reference_quads,
        color=raw_config["reference_path_color_rgba"],
        updateNormals=False,
    )
    root_node.addObject(
        TrunkKoopmanMpcController(
            trunk=observed.trunk,
            tip_dofs=observed.tip_dofs,
            centerline_dofs=observed.centerline_dofs,
            reference_dofs=reference_dofs,
            tip_monitor=observed.tip_monitor,
            start_marker=observed.start_marker,
            trajectory=trajectory,
            experiment=experiment,
            controller=mpc,
            safety=safety,
            run_dir=run_dir,
            deadline_ms=float(raw_config["deadline_ms"]),
            warmup_steps=int(raw_config["benchmark_warmup_steps"]),
            plant_settle_steps=plant_settle_steps,
        )
    )
    print(
        "[KoopmanMPC] scene ready "
        f"config={config_path} model={mpc.model.name} output={run_dir}"
    )
    return root_node
