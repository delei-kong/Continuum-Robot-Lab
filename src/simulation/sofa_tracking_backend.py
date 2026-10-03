"""SOFA data adapter for task-space inverse tracking."""

from __future__ import annotations

from typing import Any

from control.tracking_contracts import (
    ControlCommand,
    ControllerContext,
    TaskSpaceGoalCommand,
    TrackingObservation,
)
from simulation.scenes.trunk_inverse_common import CABLE_NAMES, scalar_data


class SofaInverseTaskSpacePlant:
    """Expose a Trunk inverse scene through the common tracking contracts."""

    def __init__(
        self,
        *,
        trunk: Any,
        target_dofs: Any,
        effector_dofs: Any,
        dt_s: float,
    ) -> None:
        self.trunk = trunk
        self.target_dofs = target_dofs
        self.effector_dofs = effector_dofs
        self._context = ControllerContext(
            dt_s=dt_s,
            cable_count=len(CABLE_NAMES),
            supported_command_kinds=frozenset({"task_space_goal"}),
        )

    @property
    def controller_context(self) -> ControllerContext:
        return self._context

    def apply(self, command: ControlCommand) -> None:
        if not isinstance(command, TaskSpaceGoalCommand):
            raise TypeError("SOFA inverse plant currently accepts only task-space goals")
        self.target_dofs.position.value = [list(command.position_mm)]

    def observe(self, time_s: float) -> TrackingObservation:
        tip = tuple(float(axis) for axis in self.effector_dofs.position.value[0])
        displacements = []
        forces = []
        for cable_name in CABLE_NAMES:
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            displacements.append(scalar_data(cable.displacement))
            forces.append(scalar_data(cable.force))
        return TrackingObservation(
            time_s=time_s,
            tip_position_mm=tip,  # type: ignore[arg-type]
            cable_displacements_mm=tuple(displacements),
            cable_forces_mn=tuple(forces),
        )

    def close(self) -> None:
        pass
