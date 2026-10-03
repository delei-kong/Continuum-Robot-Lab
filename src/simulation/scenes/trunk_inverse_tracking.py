"""25 Hz fixed-target tracking with the official SoftRobots inverse solver."""

from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import Sofa.Core


PROJECT_ROOT = Path(__file__).resolve().parents[3]
from simulation.inverse_tracking import (  # noqa: E402
    InverseTargetSignal,
    InverseTrackingConfig,
    PeriodicRandomTargetSignal,
    PeriodicRandomTrackingConfig,
    Point3,
    generate_random_waypoints,
    summarize_step_times,
)
from simulation.scenes.trunk_inverse_common import (  # noqa: E402
    CABLE_NAMES,
    MarkerSpec,
    create_inverse_trunk,
    scalar_data,
)


TrackingConfig = InverseTrackingConfig | PeriodicRandomTrackingConfig
TargetSignal = InverseTargetSignal | PeriodicRandomTargetSignal


def _load_config() -> tuple[dict[str, Any], Path]:
    default_path = PROJECT_ROOT / "configs" / "trunk_inverse_tracking.json"
    config_path = Path(os.environ.get("TRUNK_INVERSE_CONFIG", default_path)).resolve()
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle), config_path


class TrunkInverseTrackingController(Sofa.Core.Controller):
    """Update the task-space goal and retain measurements in memory until completion."""

    BASE_FIELDS = [
        "step",
        "time_s",
        "phase",
        "cycle_index",
        "waypoint_index",
        "target_x_mm",
        "target_y_mm",
        "target_z_mm",
        "tip_x_mm",
        "tip_y_mm",
        "tip_z_mm",
        "error_norm_mm",
        "solve_wall_ms",
        "control_period_wall_ms",
        "solve_deadline_met",
        "control_period_deadline_met",
        "non_finite",
    ]
    CABLE_FIELDS = [
        field
        for cable_name in CABLE_NAMES
        for field in (f"{cable_name}_displacement_mm", f"{cable_name}_force")
    ]

    def __init__(
        self,
        *,
        trunk: Any,
        target_dofs: Any,
        effector_dofs: Any,
        config: TrackingConfig,
        signal: TargetSignal,
        waypoints: tuple[Point3, ...],
        run_dir: Path,
    ) -> None:
        Sofa.Core.Controller.__init__(self)
        self.trunk = trunk
        self.target_dofs = target_dofs
        self.effector_dofs = effector_dofs
        self.config = config
        self.signal = signal
        self.waypoints = waypoints
        self.total_steps = self.signal.total_steps()
        self.run_dir = run_dir
        self.step = 0
        self.sample = None
        self.step_started_at = 0.0
        self.previous_step_started_at: float | None = None
        self.rows: list[dict[str, Any]] = []
        self.solve_times_ms: list[float] = []
        self.control_periods_ms: list[float] = []
        self.finalized = False
        self.last_phase_key: tuple[str, int, int] | None = None
        mode = (
            "periodic_random_waypoints"
            if isinstance(config, PeriodicRandomTrackingConfig)
            else "single_target"
        )
        print(
            "[TrunkInverse] initialized "
            f"rate={config.control_rate_hz:.1f}Hz dt={config.dt:.3f}s "
            f"steps={self.total_steps} mode={mode} waypoints={len(waypoints)}"
        )

    def onAnimateBeginEvent(self, _event: Any) -> None:
        if self.step >= self.total_steps:
            return
        now = time.perf_counter()
        if self.previous_step_started_at is not None and self.rows:
            control_period_ms = (now - self.previous_step_started_at) * 1000.0
            self.rows[-1]["control_period_wall_ms"] = control_period_ms
            self.rows[-1]["control_period_deadline_met"] = int(
                control_period_ms <= self.config.deadline_ms
            )
            self.control_periods_ms.append(control_period_ms)
        self.previous_step_started_at = now
        self.step_started_at = now
        self.sample = self.signal.sample_step(self.step)
        self.target_dofs.position.value = [list(self.sample.position_mm)]
        phase_key = (
            self.sample.phase,
            self.sample.cycle_index,
            self.sample.waypoint_index,
        )
        if phase_key != self.last_phase_key:
            self.last_phase_key = phase_key
            print(
                f"[TrunkInverse] phase={self.sample.phase} step={self.step} "
                f"cycle={self.sample.cycle_index} waypoint={self.sample.waypoint_index} "
                f"target={list(self.sample.position_mm)}"
            )

    def onAnimateEndEvent(self, _event: Any) -> None:
        if self.step >= self.total_steps or self.sample is None:
            return
        solve_wall_ms = (time.perf_counter() - self.step_started_at) * 1000.0
        target = self.sample.position_mm
        tip = tuple(float(axis) for axis in self.effector_dofs.position.value[0])
        error_norm = math.sqrt(sum((goal - actual) ** 2 for goal, actual in zip(target, tip)))
        finite = all(
            math.isfinite(value) for value in (*target, *tip, error_norm, solve_wall_ms)
        )
        row: dict[str, Any] = {
            "step": self.step,
            "time_s": (self.step + 1) * self.config.dt,
            "phase": self.sample.phase,
            "cycle_index": self.sample.cycle_index,
            "waypoint_index": self.sample.waypoint_index,
            "target_x_mm": target[0],
            "target_y_mm": target[1],
            "target_z_mm": target[2],
            "tip_x_mm": tip[0],
            "tip_y_mm": tip[1],
            "tip_z_mm": tip[2],
            "error_norm_mm": error_norm,
            "solve_wall_ms": solve_wall_ms,
            "control_period_wall_ms": "",
            "solve_deadline_met": int(solve_wall_ms <= self.config.deadline_ms),
            "control_period_deadline_met": "",
            "non_finite": int(not finite),
        }
        for cable_name in CABLE_NAMES:
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            row[f"{cable_name}_displacement_mm"] = scalar_data(cable.displacement)
            row[f"{cable_name}_force"] = scalar_data(cable.force)
        self.rows.append(row)
        self.solve_times_ms.append(solve_wall_ms)
        if not finite:
            print(f"[TrunkInverse][ERROR] non-finite state at step {self.step}")
        self.step += 1
        if self.step == self.total_steps:
            self._finalize()

    def onCleanupEvent(self, _event: Any) -> None:
        self._finalize()

    def _finalize(self) -> None:
        if self.finalized or not self.rows:
            return
        self.finalized = True
        fieldnames = self.BASE_FIELDS + self.CABLE_FIELDS
        with (self.run_dir / "trajectory.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.rows)

        warmup_steps = min(self.config.benchmark_warmup_steps, len(self.rows) - 1)
        solve_timing = summarize_step_times(
            self.solve_times_ms, self.config.deadline_ms, warmup_steps
        )
        period_warmup = min(self.config.benchmark_warmup_steps, len(self.control_periods_ms) - 1)
        control_period_timing = summarize_step_times(
            self.control_periods_ms, self.config.deadline_ms, period_warmup
        )
        hold_errors = [row["error_norm_mm"] for row in self.rows if row["phase"] == "hold"]
        tracking_summary: dict[str, Any] = {
            "mode": (
                "periodic_random_waypoints"
                if isinstance(self.config, PeriodicRandomTrackingConfig)
                else "single_target"
            ),
            "final_tip_mm": [self.rows[-1][f"tip_{axis}_mm"] for axis in "xyz"],
            "final_error_norm_mm": self.rows[-1]["error_norm_mm"],
            "hold_mean_error_norm_mm": sum(hold_errors) / len(hold_errors),
            "hold_max_error_norm_mm": max(hold_errors),
        }
        if isinstance(self.config, PeriodicRandomTrackingConfig):
            waypoint_holds = []
            for cycle_index in range(self.config.cycle_count):
                for waypoint_index, target in enumerate(self.waypoints):
                    errors = [
                        row["error_norm_mm"]
                        for row in self.rows
                        if row["phase"] == "hold"
                        and row["cycle_index"] == cycle_index
                        and row["waypoint_index"] == waypoint_index
                    ]
                    waypoint_holds.append(
                        {
                            "cycle_index": cycle_index,
                            "waypoint_index": waypoint_index,
                            "target_mm": list(target),
                            "samples": len(errors),
                            "mean_error_norm_mm": sum(errors) / len(errors),
                            "max_error_norm_mm": max(errors),
                        }
                    )
            tracking_summary.update(
                {
                    "random_seed": self.config.random_seed,
                    "cycle_count": self.config.cycle_count,
                    "waypoints_mm": [list(point) for point in self.waypoints],
                    "waypoint_holds": waypoint_holds,
                }
            )
        else:
            tracking_summary["target_mm"] = list(self.config.target_mm)
        summary = {
            "control_rate_hz": self.config.control_rate_hz,
            "dt_s": self.config.dt,
            "completed_steps": len(self.rows),
            "solve_timing": solve_timing,
            "control_period_timing": control_period_timing,
            "tracking": tracking_summary,
        }
        with (self.run_dir / "performance.json").open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(
            "[TrunkInverse] completed "
            f"rows={len(self.rows)} period_p99={control_period_timing['p99_ms']:.3f}ms "
            f"deadline_met={control_period_timing['p99_deadline_met']} "
            f"final_error={summary['tracking']['final_error_norm_mm']:.3f}mm"
        )


def createScene(root_node: Any) -> Any:
    raw_config, config_path = _load_config()
    if raw_config.get("tracking_mode") == "periodic_random_waypoints":
        config: TrackingConfig = PeriodicRandomTrackingConfig.from_mapping(raw_config)
        waypoints = generate_random_waypoints(config)
        signal: TargetSignal = PeriodicRandomTargetSignal(config, waypoints)
        palette = raw_config["target_marker_palette_rgba"]
        if len(palette) < len(waypoints):
            raise ValueError("target marker palette must cover every generated waypoint")
        marker_specs = tuple(
            (
                waypoint,
                [float(value) for value in palette[index]],
                [float(value) for value in palette[index][:3]] + [1.0],
            )
            for index, waypoint in enumerate(waypoints)
        )
    else:
        config = InverseTrackingConfig.from_mapping(raw_config)
        waypoints = (config.target_mm,)
        signal = InverseTargetSignal(config)
        marker_specs = (
            (
                config.target_mm,
                [float(value) for value in raw_config["target_marker_color_rgba"]],
                [float(value) for value in raw_config["target_crosshair_color_rgba"]],
            ),
        )
    root_node.dt = config.dt
    root_node.gravity = [0.0, -9810.0, 0.0]
    run_dir = Path(
        os.environ.get(
            "TRUNK_RUN_DIR", PROJECT_ROOT / "outputs" / "trunk_inverse_tracking_manual"
        )
    ).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(raw_config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    if isinstance(config, PeriodicRandomTrackingConfig):
        with (run_dir / "generated_waypoints.json").open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "random_seed": config.random_seed,
                    "waypoints_mm": [list(point) for point in waypoints],
                },
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.write("\n")

    trunk, target_dofs, effector_dofs = create_inverse_trunk(
        root_node, raw_config, marker_specs
    )
    root_node.addObject(
        TrunkInverseTrackingController(
            trunk=trunk,
            target_dofs=target_dofs,
            effector_dofs=effector_dofs,
            config=config,
            signal=signal,
            waypoints=waypoints,
            run_dir=run_dir,
        )
    )
    print(f"[TrunkInverse] scene ready config={config_path} output={run_dir}")
    return root_node
