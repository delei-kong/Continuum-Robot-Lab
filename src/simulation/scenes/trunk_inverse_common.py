"""Shared SOFA graph construction for inverse Trunk tracking scenes."""

from __future__ import annotations

import math
from typing import Any

from simulation.inverse_tracking import (
    Point3,
    crosshair_marker_geometry,
    octahedron_marker_geometry,
    translate_marker,
)
from simulation.scenes.trunk_common import Trunk


CABLE_NAMES = tuple(f"cableL{index}" for index in range(4)) + tuple(
    f"cableS{index}" for index in range(4)
)
MarkerSpec = tuple[Point3, list[float], list[float]]


def scalar_data(data: Any) -> float:
    value = data.value
    while isinstance(value, (list, tuple)):
        if not value:
            return math.nan
        value = value[0]
    return float(value)


def create_inverse_trunk(
    root_node: Any, raw_config: dict[str, Any], marker_specs: tuple[MarkerSpec, ...]
) -> tuple[Any, Any, Any]:
    root_node.addObject("RequiredPlugin", name="SoftRobots")
    root_node.addObject("RequiredPlugin", name="SoftRobots.Inverse")
    root_node.addObject("RequiredPlugin", name="SofaPython3")
    root_node.addObject("RequiredPlugin", name="SofaValidation")
    root_node.addObject(
        "RequiredPlugin",
        pluginName=[
            "Sofa.Component.AnimationLoop",
            "Sofa.Component.Constraint.Lagrangian.Correction",
            "Sofa.Component.Constraint.Projective",
            "Sofa.Component.Engine.Select",
            "Sofa.Component.IO.Mesh",
            "Sofa.Component.LinearSolver.Direct",
            "Sofa.Component.LinearSolver.Iterative",
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
        "QPInverseProblemSolver",
        name="inverseSolver",
        epsilon=float(raw_config["qp_epsilon"]),
        printLog=False,
        saveMatrices=False,
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
    trunk = Trunk(simulation, inverseMode=True)
    trunk.addVisualModel(color=[0.2, 0.7, 0.9, 0.85])
    trunk.fixExtremity()

    target = root_node.addChild("Target")
    target.addObject("EulerImplicitSolver", firstOrder=True)
    target.addObject("CGLinearSolver", iterations=100, tolerance=1e-5, threshold=1e-5)
    target_dofs = target.addObject(
        "MechanicalObject",
        name="dofs",
        position=[raw_config["start_target_mm"]],
        showObject=True,
        showObjectScale=float(raw_config.get("reference_marker_scale_mm", 1.5)),
        showColor=[0.2, 1.0, 0.2, 1.0],
    )
    target.addObject("UncoupledConstraintCorrection", defaultCompliance=1e-5)

    marker_vertices, marker_triangles, marker_edges = octahedron_marker_geometry(
        float(raw_config["target_marker_radius_mm"])
    )
    crosshair_vertices, crosshair_edges = crosshair_marker_geometry(
        float(raw_config["target_crosshair_half_length_mm"])
    )
    for marker_index, (target_position, marker_color, crosshair_color) in enumerate(
        marker_specs
    ):
        target_visual = root_node.addChild(f"TargetVisualMarker{marker_index}")
        diamond_visual = target_visual.addChild("Diamond")
        diamond_visual.addObject(
            "OglModel",
            name="diamond",
            position=translate_marker(marker_vertices, target_position),
            triangles=marker_triangles,
            edges=marker_edges,
            color=marker_color,
            updateNormals=False,
        )
        crosshair_visual = target_visual.addChild("Crosshair")
        crosshair_visual.addObject(
            "OglModel",
            name="crosshair",
            position=translate_marker(crosshair_vertices, target_position),
            edges=crosshair_edges,
            color=crosshair_color,
            updateNormals=False,
        )

    effectors = trunk.node.addChild("Effectors")
    effector_dofs = effectors.addObject(
        "MechanicalObject",
        name="dofs",
        position=[[0.0, 0.0, 195.0]],
        showObject=True,
        showObjectScale=float(raw_config.get("tip_marker_scale_mm", 3.0)),
        showColor=[1.0, 0.2, 0.2, 1.0],
    )
    effectors.addObject(
        "PositionEffector",
        name="positionEffector",
        indices=[0],
        effectorGoal=target_dofs.getData("position").getLinkPath(),
    )
    effectors.addObject(
        "Monitor",
        name="tipTrajectory",
        template="Vec3",
        indices=[0],
        listening=True,
        showTrajectories=True,
        TrajectoriesPrecision=float(raw_config["trajectory_precision_s"]),
        TrajectoriesColor=raw_config["trajectory_color_rgba"],
        sizeFactor=float(raw_config.get("trajectory_size_factor", 2.0)),
    )
    effectors.addObject("BarycentricMapping", mapForces=False, mapMasses=False)
    return trunk, target_dofs, effector_dofs
