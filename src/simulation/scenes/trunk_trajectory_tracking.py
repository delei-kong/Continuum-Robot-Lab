"""Generic trajectory/controller benchmark on the inverse SoftRobots Trunk."""

from __future__ import annotations

import json
import os
import time
from math import dist
from pathlib import Path
from typing import Any, NamedTuple

import Sofa.Core


PROJECT_ROOT = Path(__file__).resolve().parents[3]
from control.reference_controller import controller_from_mapping  # noqa: E402
from control.tracking_contracts import ControllerOutput, TrackingObservation  # noqa: E402
from evaluation.recording import (  # noqa: E402
    InMemoryTrackingRecorder,
    TrackingStepRecord,
)
from evaluation.tracking_metrics import write_tracking_artifacts  # noqa: E402
from simulation.scenes.trunk_inverse_common import (  # noqa: E402
    MarkerSpec,
    create_inverse_trunk,
)
from simulation.sofa_tracking_backend import SofaInverseTaskSpacePlant  # noqa: E402
from simulation.tracking_pipeline import TrackingExperimentConfig  # noqa: E402
from simulation.trajectory import (  # noqa: E402
    Trajectory,
    polyline_tube_geometry,
    sample_trajectory_polyline,
    trajectory_from_mapping,
)


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
    default_path = PROJECT_ROOT / "configs" / "trunk_trajectory_tracking_line.json"
    config_path = Path(os.environ.get("TRUNK_INVERSE_CONFIG", default_path)).resolve()
    with config_path.open(encoding="utf-8") as handle:
        values = json.load(handle)
    if values.get("tracking_mode") != "trajectory_benchmark":
        raise ValueError("trajectory scene requires tracking_mode=trajectory_benchmark")
    return values, config_path


class SofaTrajectoryTrackingController(Sofa.Core.Controller):
    """Bridge runSofa animation events to the common tracking contracts."""

    def __init__(
        self,
        *,
        plant: SofaInverseTaskSpacePlant,
        trajectory: Trajectory,
        experiment: TrackingExperimentConfig,
        controller: Any,
        run_dir: Path,
        deadline_ms: float,
        warmup_steps: int,
        trajectory_name: str,
        controller_name: str,
        backend_name: str,
    ) -> None:
        Sofa.Core.Controller.__init__(self)
        self.plant = plant
        self.trajectory = trajectory
        self.experiment = experiment
        self.controller = controller
        self.run_dir = run_dir
        self.deadline_ms = deadline_ms
        self.warmup_steps = warmup_steps
        self.trajectory_name = trajectory_name
        self.controller_name = controller_name
        self.backend_name = backend_name
        self.recorder = InMemoryTrackingRecorder()
        self.step = 0
        self.previous_step_started_at: float | None = None
        self.backend_started_at = 0.0
        self.pending: _PendingStep | None = None
        self.active_reference = None
        self.active_output = None
        self.controller_wall_ms = 0.0
        self.finalized = False
        self.observation = self.plant.observe(0.0)
        self.recorder.reset()
        self.trajectory.reset(experiment.seed)
        self.controller.reset(plant.controller_context)
        print(
            "[TrajectoryPipeline] initialized "
            f"dt={experiment.dt_s:.3f}s steps={experiment.total_steps} "
            f"trajectory={trajectory_name} controller={controller_name} "
            f"backend={backend_name}"
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
        now = time.perf_counter()
        if self.previous_step_started_at is not None:
            self._append_pending((now - self.previous_step_started_at) * 1000.0)
        self.previous_step_started_at = now
        sample_time_s = (self.step + 1) * self.experiment.dt_s
        self.active_reference = self.trajectory.sample(sample_time_s)
        controller_started_at = time.perf_counter()
        self.active_output = self.controller.compute(
            self.observation,
            self.active_reference,
            self.experiment.dt_s,
        )
        self.controller_wall_ms = (time.perf_counter() - controller_started_at) * 1000.0
        self.plant.apply(self.active_output.command)
        self.backend_started_at = time.perf_counter()

    def onAnimateEndEvent(self, _event: Any) -> None:
        if (
            self.step >= self.experiment.total_steps
            or self.active_reference is None
            or self.active_output is None
        ):
            return
        backend_wall_ms = (time.perf_counter() - self.backend_started_at) * 1000.0
        self.observation = self.plant.observe(self.active_reference.time_s)
        error_norm_mm = dist(
            self.active_reference.position_mm,
            self.observation.tip_position_mm,
        )
        self.pending = _PendingStep(
            step=self.step,
            time_s=self.active_reference.time_s,
            reference=self.active_reference,
            observation=self.observation,
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
        self.controller.finalize()
        self.plant.close()
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
            "[TrajectoryPipeline] completed "
            f"rows={len(records)} rmse={summary['tracking']['rmse_norm_mm']:.3f}mm "
            f"period_p99={summary['timing']['control_period']['p99_ms']:.3f}ms"
        )


def createScene(root_node: Any) -> Any:
    raw_config, config_path = _load_config()
    dt_s = float(raw_config["dt"])
    if abs(dt_s * float(raw_config["control_rate_hz"]) - 1.0) > 1e-9:
        raise ValueError("one simulation step must equal one control period")
    experiment = TrackingExperimentConfig(
        dt_s=dt_s,
        duration_s=float(raw_config["duration_s"]),
        seed=int(raw_config["seed"]),
    )
    trajectory = trajectory_from_mapping(raw_config["trajectory"])
    if abs(trajectory.duration_s - experiment.duration_s) > 1e-9:
        raise ValueError("trajectory and experiment durations must match")
    trajectory_config = raw_config["trajectory"]
    if list(trajectory.start_mm) != list(raw_config["start_target_mm"]):
        raise ValueError("trajectory start and SOFA target start must match")
    controller_config = raw_config["controller"]
    controller = controller_from_mapping(controller_config)
    backend_config = raw_config["backend"]
    if backend_config.get("type") != "sofa_inverse_qp":
        raise ValueError(f"unsupported tracking backend type: {backend_config.get('type')!r}")

    run_dir = Path(
        os.environ.get(
            "TRUNK_RUN_DIR", PROJECT_ROOT / "outputs" / "trunk_trajectory_tracking_manual"
        )
    ).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(raw_config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    marker_spec: MarkerSpec = (
        tuple(raw_config.get("target_marker_mm", trajectory.end_mm)),
        [float(value) for value in raw_config["target_marker_color_rgba"]],
        [float(value) for value in raw_config["target_crosshair_color_rgba"]],
    )
    root_node.dt = dt_s
    root_node.gravity = [0.0, -9810.0, 0.0]
    trunk, target_dofs, effector_dofs = create_inverse_trunk(
        root_node, raw_config, (marker_spec,)
    )
    reference_positions, _reference_edges = sample_trajectory_polyline(
        trajectory, int(raw_config["reference_path_samples"])
    )
    reference_vertices, reference_quads = polyline_tube_geometry(
        reference_positions,
        float(raw_config["reference_path_radius_mm"]),
        int(raw_config.get("reference_path_radial_segments", 8)),
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
    plant = SofaInverseTaskSpacePlant(
        trunk=trunk,
        target_dofs=target_dofs,
        effector_dofs=effector_dofs,
        dt_s=dt_s,
    )
    root_node.addObject(
        SofaTrajectoryTrackingController(
            plant=plant,
            trajectory=trajectory,
            experiment=experiment,
            controller=controller,
            run_dir=run_dir,
            deadline_ms=float(raw_config["deadline_ms"]),
            warmup_steps=int(raw_config["benchmark_warmup_steps"]),
            trajectory_name=str(trajectory_config["type"]),
            controller_name=str(controller_config["type"]),
            backend_name=str(backend_config["type"]),
        )
    )
    print(f"[TrajectoryPipeline] scene ready config={config_path} output={run_dir}")
    return root_node
