"""Minimal direct-control Trunk scene for the first cyclic experiment."""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import Sofa.Core


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
TRUNK_ROOT = SRC_ROOT / "simulation" / "examples" / "softrobots_trunk"
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(TRUNK_ROOT))

from simulation.cyclic_control import CyclicControlConfig, CyclicControlSignal  # noqa: E402
from trunk import Trunk  # noqa: E402


def _load_config() -> tuple[dict[str, Any], Path]:
    default_path = PROJECT_ROOT / "configs" / "trunk_cycle_single.json"
    config_path = Path(os.environ.get("TRUNK_CYCLE_CONFIG", default_path)).resolve()
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle), config_path


class TrunkCyclicController(Sofa.Core.Controller):
    """Write cable input before each step and sample the mapped tip afterwards."""

    FIELDNAMES = [
        "step",
        "time_s",
        "control_time_s",
        "phase",
        "cycle_index",
        "cableL0_command_mm",
        "tip_x_mm",
        "tip_y_mm",
        "tip_z_mm",
        "non_finite",
    ]

    def __init__(
        self,
        *,
        trunk: Trunk,
        tip_dofs: Any,
        tip_monitor: Any,
        start_marker: Any,
        config: dict[str, Any],
        run_dir: Path,
    ) -> None:
        Sofa.Core.Controller.__init__(self)
        self.trunk = trunk
        self.tip_dofs = tip_dofs
        self.tip_monitor = tip_monitor
        self.start_marker = start_marker
        self.dt = float(config["dt"])
        self.signal = CyclicControlSignal(CyclicControlConfig.from_mapping(config))
        self.total_steps = self.signal.total_steps(self.dt)
        self.trajectory_start_step = round(self.signal.config.settle_duration_s / self.dt)
        self.csv_flush_interval_steps = int(config["csv_flush_interval_steps"])
        if self.csv_flush_interval_steps <= 0:
            raise ValueError("csv_flush_interval_steps must be positive")
        self.step = 0
        self.sample = None
        self.last_cycle_index = None
        self.trajectory_started = False
        self.closed = False

        run_dir.mkdir(parents=True, exist_ok=True)
        self.handle = (run_dir / "trajectory.csv").open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=self.FIELDNAMES)
        self.writer.writeheader()
        self.handle.flush()
        print(f"[TrunkCycle] initialized dt={self.dt} total_steps={self.total_steps}")

    def onAnimateBeginEvent(self, _event: Any) -> None:
        if self.step >= self.total_steps:
            self.trunk.node.cableL0.cable.value = [0.0]
            return
        self.sample = self.signal.sample_step(self.step, self.dt)
        self.trunk.node.cableL0.cable.value = [self.sample.displacement_mm]
        if (
            self.sample.cycle_index is not None
            and self.sample.cycle_index != self.last_cycle_index
        ):
            self.last_cycle_index = self.sample.cycle_index
            print(
                f"[TrunkCycle] cycle "
                f"{self.sample.cycle_index + 1}/{self.signal.config.cycles} started"
            )

    def onAnimateEndEvent(self, _event: Any) -> None:
        if self.step >= self.total_steps or self.sample is None:
            return
        tip = [float(axis) for axis in self.tip_dofs.position.value[0]]
        finite = all(math.isfinite(axis) for axis in tip)
        if self.step + 1 == self.trajectory_start_step and not self.trajectory_started:
            self.start_marker.position.value = [tip]
            self.start_marker.showObject.value = True
            self.tip_monitor.listening.value = True
            self.trajectory_started = True
            print(
                "[TrunkCycle] trajectory visualization started "
                f"at t={(self.step + 1) * self.dt:.2f}s tip={tip}"
            )
        self.writer.writerow(
            {
                "step": self.step,
                "time_s": (self.step + 1) * self.dt,
                "control_time_s": self.sample.time_s,
                "phase": self.sample.phase,
                "cycle_index": (
                    "" if self.sample.cycle_index is None else self.sample.cycle_index
                ),
                "cableL0_command_mm": self.sample.displacement_mm,
                "tip_x_mm": tip[0],
                "tip_y_mm": tip[1],
                "tip_z_mm": tip[2],
                "non_finite": int(not finite),
            }
        )
        if (self.step + 1) % self.csv_flush_interval_steps == 0:
            self.handle.flush()
        if not finite:
            self.handle.flush()
            print(f"[TrunkCycle][ERROR] non-finite tip at step {self.step}")
        self.step += 1
        if self.step == self.total_steps:
            self.trunk.node.cableL0.cable.value = [0.0]
            self._close()
            print(f"[TrunkCycle] completed rows={self.step}")

    def onCleanupEvent(self, _event: Any) -> None:
        self._close()

    def _close(self) -> None:
        if not self.closed:
            self.handle.flush()
            self.handle.close()
            self.closed = True


def createScene(root_node: Any) -> Any:
    config, config_path = _load_config()
    control_config = CyclicControlConfig.from_mapping(config)
    run_dir = Path(os.environ.get("TRUNK_RUN_DIR", PROJECT_ROOT / "outputs" / "trunk_cycle_manual"))
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    if config.get("controlled_cable") != "cableL0":
        raise ValueError("the first experiment supports only cableL0")

    root_node.dt = float(config["dt"])
    root_node.gravity = [0.0, -9810.0, 0.0]
    root_node.addObject("RequiredPlugin", name="SoftRobots")
    root_node.addObject("RequiredPlugin", name="SofaPython3")
    root_node.addObject("RequiredPlugin", name="SofaValidation")
    root_node.addObject(
        "RequiredPlugin",
        pluginName=[
            "Sofa.Component.AnimationLoop",
            "Sofa.Component.Constraint.Lagrangian.Correction",
            "Sofa.Component.Constraint.Lagrangian.Solver",
            "Sofa.Component.Constraint.Projective",
            "Sofa.Component.Engine.Select",
            "Sofa.Component.IO.Mesh",
            "Sofa.Component.LinearSolver.Direct",
            "Sofa.Component.Mapping.Linear",
            "Sofa.Component.Mass",
            "Sofa.Component.ODESolver.Backward",
            "Sofa.Component.SolidMechanics.FEM.Elastic",
            "Sofa.Component.StateContainer",
            "Sofa.Component.Topology.Container.Constant",
            "Sofa.Component.Visual",
            "Sofa.GL.Component.Rendering3D",
        ],
    )
    root_node.addObject("DefaultVisualManagerLoop")
    root_node.addObject("VisualStyle", displayFlags="showVisualModels showBehaviorModels")
    root_node.addObject("FreeMotionAnimationLoop")
    root_node.addObject(
        "BlockGaussSeidelConstraintSolver", maxIterations=100, tolerance=1e-5
    )

    simulation = root_node.addChild("Simulation")
    simulation.addObject(
        "EulerImplicitSolver",
        name="odesolver",
        firstOrder=False,
        rayleighMass=0.1,
        rayleighStiffness=0.1,
    )
    simulation.addObject("SparseLDLSolver", name="precond")
    simulation.addObject("GenericConstraintCorrection")

    trunk = Trunk(simulation, inverseMode=False)
    trunk.addVisualModel(color=[0.2, 0.7, 0.9, 0.85])
    trunk.fixExtremity()

    tip = trunk.node.addChild("TipObservation")
    tip_dofs = tip.addObject(
        "MechanicalObject",
        name="dofs",
        position=[[0.0, 0.0, 195.0]],
        showObject=True,
        showObjectScale=3.0,
        showColor=[1.0, 0.2, 0.2, 1.0],
    )
    tip.addObject("BarycentricMapping", mapForces=False, mapMasses=False)
    tip_monitor = tip.addObject(
        "Monitor",
        name="tipTrajectory",
        template="Vec3",
        indices=[0],
        listening=False,
        showTrajectories=True,
        TrajectoriesPrecision=float(config["trajectory_precision_s"]),
        TrajectoriesColor=config["trajectory_color_rgba"],
        sizeFactor=2.0,
    )

    marker_node = root_node.addChild("TrajectoryStart")
    start_marker = marker_node.addObject(
        "MechanicalObject",
        name="dofs",
        position=[[0.0, 0.0, 195.0]],
        showObject=False,
        showObjectScale=4.0,
        showColor=[0.2, 1.0, 0.2, 1.0],
    )

    root_node.addObject(
        TrunkCyclicController(
            trunk=trunk,
            tip_dofs=tip_dofs,
            tip_monitor=tip_monitor,
            start_marker=start_marker,
            config=config,
            run_dir=run_dir,
        )
    )
    print(
        "[TrunkCycle] scene ready "
        f"config={config_path} duration={control_config.total_duration_s}s output={run_dir}"
    )
    return root_node
