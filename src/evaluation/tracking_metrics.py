"""Offline serialization and baseline metrics for trajectory tracking."""

from __future__ import annotations

import csv
import json
from math import sqrt
from pathlib import Path
from typing import Any, Sequence

from control.tracking_contracts import CableDisplacementCommand, TaskSpaceGoalCommand
from evaluation.recording import TrackingStepRecord


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile values must not be empty")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("percentile probability must be between zero and one")
    ordered = sorted(float(value) for value in values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def timing_summary(
    values_ms: Sequence[float], deadline_ms: float, warmup_steps: int
) -> dict[str, float | int | bool]:
    measured = [float(value) for value in values_ms[warmup_steps:]]
    if not measured:
        raise ValueError("no timing samples remain after warmup")
    misses = sum(value > deadline_ms for value in measured)
    p99_ms = percentile(measured, 0.99)
    return {
        "warmup_steps": warmup_steps,
        "measured_steps": len(measured),
        "mean_ms": sum(measured) / len(measured),
        "p50_ms": percentile(measured, 0.50),
        "p95_ms": percentile(measured, 0.95),
        "p99_ms": p99_ms,
        "max_ms": max(measured),
        "deadline_ms": deadline_ms,
        "deadline_misses": misses,
        "deadline_success_ratio": (len(measured) - misses) / len(measured),
        "p99_deadline_met": p99_ms <= deadline_ms,
    }


def summarize_tracking_records(
    records: Sequence[TrackingStepRecord], deadline_ms: float, warmup_steps: int
) -> dict[str, Any]:
    if not records:
        raise ValueError("tracking records must not be empty")
    warmup = min(warmup_steps, len(records) - 1)

    def error_metrics(selected: Sequence[TrackingStepRecord]) -> dict[str, Any]:
        if not selected:
            raise ValueError("tracking metric records must not be empty")
        errors = [record.tracking_error_norm_mm for record in selected]
        axis_errors = [
            tuple(
                reference - actual
                for reference, actual in zip(
                    record.reference.position_mm, record.observation.tip_position_mm
                )
            )
            for record in selected
        ]
        return {
            "rmse_norm_mm": sqrt(sum(error * error for error in errors) / len(errors)),
            "mean_norm_mm": sum(errors) / len(errors),
            "p95_norm_mm": percentile(errors, 0.95),
            "max_norm_mm": max(errors),
            "final_norm_mm": errors[-1],
            "axis_rmse_mm": [
                sqrt(
                    sum(error[axis] ** 2 for error in axis_errors) / len(axis_errors)
                )
                for axis in range(3)
            ],
        }

    measured_records = records[warmup:]
    tracking = error_metrics(measured_records)
    tracking.update(
        {
            "warmup_steps": warmup,
            "measured_steps": len(measured_records),
            "all_steps": error_metrics(records),
            "by_phase": {
                phase: error_metrics(
                    [
                        record
                        for record in measured_records
                        if record.reference.phase == phase
                    ]
                )
                for phase in sorted(
                    {record.reference.phase for record in measured_records}
                )
            },
        }
    )
    periods = [
        record.control_period_wall_ms
        for record in records
        if record.control_period_wall_ms is not None
    ]
    period_warmup = min(warmup_steps, len(periods) - 1)
    return {
        "completed_steps": len(records),
        "tracking": tracking,
        "timing": {
            "controller": timing_summary(
                [record.controller_wall_ms for record in records], deadline_ms, warmup
            ),
            "backend": timing_summary(
                [record.backend_wall_ms for record in records], deadline_ms, warmup
            ),
            "control_period": timing_summary(periods, deadline_ms, period_warmup),
        },
    }


def _record_to_row(record: TrackingStepRecord, cable_count: int) -> dict[str, Any]:
    reference = record.reference
    observation = record.observation
    output = record.controller_output
    command = output.command
    row: dict[str, Any] = {
        "step": record.step,
        "time_s": record.time_s,
        "phase": reference.phase,
        "cycle_index": reference.cycle_index,
        "reference_x_mm": reference.position_mm[0],
        "reference_y_mm": reference.position_mm[1],
        "reference_z_mm": reference.position_mm[2],
        "tip_x_mm": observation.tip_position_mm[0],
        "tip_y_mm": observation.tip_position_mm[1],
        "tip_z_mm": observation.tip_position_mm[2],
        "error_norm_mm": record.tracking_error_norm_mm,
        "command_kind": command.kind,
        "command_x_mm": "",
        "command_y_mm": "",
        "command_z_mm": "",
        "command_cables_mm": "",
        "controller_diagnostics": json.dumps(dict(output.diagnostics), sort_keys=True),
        "controller_wall_ms": record.controller_wall_ms,
        "backend_wall_ms": record.backend_wall_ms,
        "control_period_wall_ms": record.control_period_wall_ms or "",
    }
    if isinstance(command, TaskSpaceGoalCommand):
        row.update(
            {
                "command_x_mm": command.position_mm[0],
                "command_y_mm": command.position_mm[1],
                "command_z_mm": command.position_mm[2],
            }
        )
    elif isinstance(command, CableDisplacementCommand):
        row["command_cables_mm"] = json.dumps(command.displacements_mm)
    for index in range(cable_count):
        row[f"cable_{index}_displacement_mm"] = observation.cable_displacements_mm[index]
        row[f"cable_{index}_force_mn"] = (
            observation.cable_forces_mn[index] if observation.cable_forces_mn else ""
        )
    return row


def write_tracking_artifacts(
    run_dir: Path,
    records: Sequence[TrackingStepRecord],
    *,
    deadline_ms: float,
    warmup_steps: int,
) -> dict[str, Any]:
    if not records:
        raise ValueError("tracking records must not be empty")
    cable_count = len(records[0].observation.cable_displacements_mm)
    rows = [_record_to_row(record, cable_count) for record in records]
    with (run_dir / "trajectory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize_tracking_records(records, deadline_ms, warmup_steps)
    with (run_dir / "performance.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return summary
