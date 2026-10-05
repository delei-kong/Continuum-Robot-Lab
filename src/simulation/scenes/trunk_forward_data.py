"""Direct multi-cable Trunk scene for collecting Koopman training episodes."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from typing import Any

import Sofa.Core


PROJECT_ROOT = Path(__file__).resolve().parents[3]
from simulation.forward_data import (  # noqa: E402
    CABLE_NAMES,
    CableActionSafetyLayer,
    ForwardDataConfig,
    MultiSineExcitation,
)
from simulation.scenes.trunk_common import create_forward_observed_trunk  # noqa: E402


def _scalar_data(data: Any) -> float:
    value = data.value
    while isinstance(value, (list, tuple)):
        if not value:
            return math.nan
        value = value[0]
    return float(value)


def _load_config() -> tuple[dict[str, Any], Path]:
    default_path = PROJECT_ROOT / "configs" / "trunk_forward_multisine_pilot.json"
    config_path = Path(os.environ.get("TRUNK_FORWARD_CONFIG", default_path)).resolve()
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("forward data configuration must be a JSON object")
    return payload, config_path


class TrunkForwardDataController(Sofa.Core.Controller):
    """Apply safe direct actions and record one synchronized state transition stream."""

    def __init__(
        self,
        *,
        trunk: Any,
        tip_dofs: Any,
        centerline_dofs: Any,
        config: ForwardDataConfig,
        run_dir: Path,
    ) -> None:
        Sofa.Core.Controller.__init__(self)
        self.trunk = trunk
        self.tip_dofs = tip_dofs
        self.centerline_dofs = centerline_dofs
        self.config = config
        self.signal = MultiSineExcitation(config)
        self.safety = CableActionSafetyLayer(
            config.cable_max_displacements_mm, config.max_command_delta_mm
        )
        self.step = 0
        self.phase = "settle"
        self.command_mm = (0.0,) * len(CABLE_NAMES)
        self.command_limited = False
        self.closed = False

        run_dir.mkdir(parents=True, exist_ok=True)
        self.handle = (run_dir / "episode.csv").open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=self._fieldnames())
        self.writer.writeheader()
        self.handle.flush()
        print(
            "[TrunkForwardData] initialized "
            f"dt={config.dt_s} steps={config.total_steps} cables={len(CABLE_NAMES)}"
        )

    def _fieldnames(self) -> list[str]:
        fields = ["step", "time_s", "phase", "command_limited"]
        for cable_name in CABLE_NAMES:
            fields.extend(
                (
                    f"{cable_name}_command_mm",
                    f"{cable_name}_displacement_mm",
                    f"{cable_name}_force",
                )
            )
        fields.extend(("tip_x_mm", "tip_y_mm", "tip_z_mm"))
        for index in range(len(self.config.centerline_z_mm)):
            for axis in ("x", "y", "z"):
                fields.append(f"centerline_{index}_{axis}_mm")
                fields.append(f"centerline_{index}_v{axis}_mm_s")
        fields.append("non_finite")
        return fields

    def onAnimateBeginEvent(self, _event: Any) -> None:
        if self.step >= self.config.total_steps:
            self._release_cables()
            return
        self.phase, desired = self.signal.sample(self.step * self.config.dt_s)
        projection = self.safety.project(desired)
        self.command_mm = projection.applied_mm
        self.command_limited = projection.limited
        for cable_name, command in zip(CABLE_NAMES, self.command_mm):
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            cable.value = [command]

    def onAnimateEndEvent(self, _event: Any) -> None:
        if self.step >= self.config.total_steps:
            return
        row: dict[str, Any] = {
            "step": self.step,
            "time_s": (self.step + 1) * self.config.dt_s,
            "phase": self.phase,
            "command_limited": int(self.command_limited),
        }
        finite_values: list[float] = []
        for cable_name, command in zip(CABLE_NAMES, self.command_mm):
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            displacement = _scalar_data(cable.displacement)
            force = _scalar_data(cable.force)
            row[f"{cable_name}_command_mm"] = command
            row[f"{cable_name}_displacement_mm"] = displacement
            row[f"{cable_name}_force"] = force
            finite_values.extend((command, displacement, force))

        tip = tuple(float(axis) for axis in self.tip_dofs.position.value[0])
        row.update(zip(("tip_x_mm", "tip_y_mm", "tip_z_mm"), tip))
        finite_values.extend(tip)
        positions = self.centerline_dofs.position.value
        velocities = self.centerline_dofs.velocity.value
        for index, (position, velocity) in enumerate(zip(positions, velocities)):
            for axis_index, axis_name in enumerate(("x", "y", "z")):
                position_value = float(position[axis_index])
                velocity_value = float(velocity[axis_index])
                row[f"centerline_{index}_{axis_name}_mm"] = position_value
                row[f"centerline_{index}_v{axis_name}_mm_s"] = velocity_value
                finite_values.extend((position_value, velocity_value))

        finite = len(positions) == len(self.config.centerline_z_mm) and all(
            math.isfinite(value) for value in finite_values
        )
        row["non_finite"] = int(not finite)
        self.writer.writerow(row)
        if (self.step + 1) % self.config.csv_flush_interval_steps == 0 or not finite:
            self.handle.flush()
        if not finite:
            print(f"[TrunkForwardData][ERROR] non-finite state at step {self.step}")

        self.step += 1
        if self.step == self.config.total_steps:
            self._release_cables()
            self._close()
            print(f"[TrunkForwardData] completed rows={self.step}")

    def onCleanupEvent(self, _event: Any) -> None:
        self._release_cables()
        self._close()

    def _release_cables(self) -> None:
        for cable_name in CABLE_NAMES:
            cable = getattr(getattr(self.trunk.node, cable_name), "cable")
            cable.value = [0.0]

    def _close(self) -> None:
        if not self.closed:
            self.handle.flush()
            self.handle.close()
            self.closed = True


def createScene(root_node: Any) -> Any:
    raw_config, config_path = _load_config()
    config = ForwardDataConfig.from_mapping(raw_config)
    run_dir = Path(
        os.environ.get("TRUNK_RUN_DIR", PROJECT_ROOT / "outputs" / "trunk_forward_manual")
    ).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "config.json").open("w", encoding="utf-8") as handle:
        json.dump(raw_config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    observed = create_forward_observed_trunk(root_node, raw_config)
    root_node.addObject(
        TrunkForwardDataController(
            trunk=observed.trunk,
            tip_dofs=observed.tip_dofs,
            centerline_dofs=observed.centerline_dofs,
            config=config,
            run_dir=run_dir,
        )
    )
    print(
        "[TrunkForwardData] scene ready "
        f"config={config_path} duration={config.duration_s}s output={run_dir}"
    )
    return root_node
