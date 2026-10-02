"""Shared construction helpers for project-specific Trunk experiments."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
TRUNK_ROOT = SRC_ROOT / "simulation" / "examples" / "softrobots_trunk"
sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(TRUNK_ROOT))

from trunk import Trunk  # noqa: E402


@dataclass(frozen=True)
class ObservedTrunk:
    trunk: Any
    tip_dofs: Any
    tip_monitor: Any
    start_marker: Any


def create_observed_trunk(root_node: Any, config: dict[str, Any]) -> ObservedTrunk:
    """Create the fixed Trunk model and its reusable tip observation objects."""

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
    return ObservedTrunk(trunk, tip_dofs, tip_monitor, start_marker)
