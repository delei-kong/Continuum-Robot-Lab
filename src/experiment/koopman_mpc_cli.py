"""Registered entrypoint for direct Koopman-MPC Trunk tracking experiments."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation.forward_data import CABLE_COUNT
from simulation.trajectory import trajectory_from_mapping

from .contracts import RUN_ID_PATTERN, RunManifest


_REMOTE_WORKSPACE_PREFIX = "/root/gpufree-share/"


@dataclass(frozen=True)
class KoopmanMpcPreset:
    input_name: str
    config_rel: str
    scene_rel: str
    description: str


@dataclass(frozen=True)
class KoopmanMpcRunSpec:
    input_name: str
    config_rel: str
    scene_rel: str
    steps: int
    description: str


_PRESETS = {
    "line": KoopmanMpcPreset(
        input_name="line",
        config_rel="configs/trunk_koopman_mpc_line.json",
        scene_rel="src/simulation/scenes/trunk_koopman_mpc.py",
        description=(
            "Direct 8-cable Koopman-MPC tracking of a registered extended line; "
            "green reference path and point, red measured tip, orange executed path."
        ),
    ),
    "ellipse": KoopmanMpcPreset(
        input_name="ellipse",
        config_rel="configs/trunk_koopman_mpc_ellipse.json",
        scene_rel="src/simulation/scenes/trunk_koopman_mpc.py",
        description=(
            "Direct 8-cable Koopman-MPC tracking of a registered ellipse; "
            "green reference path and point, red measured tip, orange executed path."
        ),
    ),
    "circle": KoopmanMpcPreset(
        input_name="circle",
        config_rel="configs/trunk_koopman_mpc_circle.json",
        scene_rel="src/simulation/scenes/trunk_koopman_mpc.py",
        description=(
            "Direct 8-cable Koopman-MPC tracking of a registered circle; "
            "green reference path and point, red measured tip, orange executed path."
        ),
    ),
    "triangle": KoopmanMpcPreset(
        input_name="triangle",
        config_rel="configs/trunk_koopman_mpc_triangle.json",
        scene_rel="src/simulation/scenes/trunk_koopman_mpc.py",
        description=(
            "Direct 8-cable Koopman-MPC tracking of a registered rounded triangular loop; "
            "green reference path and point, red measured tip, orange executed path."
        ),
    ),
    "square": KoopmanMpcPreset(
        input_name="square",
        config_rel="configs/trunk_koopman_mpc_square.json",
        scene_rel="src/simulation/scenes/trunk_koopman_mpc.py",
        description=(
            "Direct 8-cable Koopman-MPC tracking of a registered rounded square loop; "
            "green reference path and point, red measured tip, orange executed path."
        ),
    ),
}


def _read_config(project_root: Path, config_rel: str) -> Mapping[str, Any]:
    path = (project_root / config_rel).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError(f"configuration escapes project root: {config_rel}") from error
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"registered configuration is missing: {config_rel}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"registered configuration is invalid JSON: {config_rel}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"registered configuration must be a JSON object: {config_rel}")
    return payload


def _positive_float(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value <= 0.0
    ):
        raise ValueError(f"{label} must be a positive number")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must contain only letters, digits, '.', '_' or '-'")
    return value


def _derive_steps(config: Mapping[str, Any]) -> int:
    if config.get("tracking_mode") != "koopman_mpc_tracking":
        raise ValueError("K-MPC configuration requires tracking_mode=koopman_mpc_tracking")
    dt_s = _positive_float(config.get("dt"), "dt")
    control_rate_hz = _positive_float(config.get("control_rate_hz"), "control_rate_hz")
    if abs(dt_s * control_rate_hz - 1.0) > 1e-9:
        raise ValueError("one simulation step must equal one K-MPC control period")
    duration_s = _positive_float(config.get("duration_s"), "duration_s")
    steps = round(duration_s / dt_s)
    if steps < 1 or abs(steps * dt_s - duration_s) > 1e-9:
        raise ValueError("K-MPC duration must be an integer multiple of dt")
    _positive_int(config.get("benchmark_warmup_steps"), "benchmark_warmup_steps")
    settle_steps = _positive_int(config.get("plant_settle_steps"), "plant_settle_steps")
    if settle_steps >= steps:
        raise ValueError("plant_settle_steps must be shorter than the K-MPC experiment")
    model = config.get("model")
    controller = config.get("controller")
    trajectory = config.get("trajectory")
    safety = config.get("action_safety")
    if not all(isinstance(section, dict) for section in (model, controller, trajectory, safety)):
        raise ValueError("K-MPC model, controller, trajectory and action_safety must be objects")
    _safe_id(model.get("final_output_id"), "model.final_output_id")
    if controller.get("type") != "koopman_mpc":
        raise ValueError("K-MPC controller.type must be koopman_mpc")
    _positive_int(controller.get("horizon_steps"), "controller.horizon_steps")
    _positive_int(
        controller.get("projected_gradient_iterations"),
        "controller.projected_gradient_iterations",
    )
    if trajectory.get("type") not in {
        "timed_linear",
        "periodic_ellipse",
        "periodic_catmull_rom",
    }:
        raise ValueError("K-MPC trajectory type is unsupported")
    settle_duration_s = _positive_float(
        trajectory.get("settle_duration_s"), "trajectory.settle_duration_s"
    )
    if abs(settle_steps * dt_s - settle_duration_s) > 1e-9:
        raise ValueError("plant_settle_steps must equal trajectory.settle_duration_s / dt")
    try:
        resolved_trajectory = trajectory_from_mapping(trajectory)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"K-MPC trajectory configuration is invalid: {error}") from error
    if abs(resolved_trajectory.duration_s - duration_s) > 1e-9:
        raise ValueError("K-MPC trajectory duration must match the experiment duration")
    maxima = safety.get("maximum_displacements_mm")
    if not isinstance(maxima, list) or len(maxima) != CABLE_COUNT:
        raise ValueError("action_safety.maximum_displacements_mm must match the cable count")
    _positive_float(safety.get("max_command_delta_mm"), "action_safety.max_command_delta_mm")
    return steps


def resolve_koopman_mpc_spec(input_name: str, project_root: Path) -> KoopmanMpcRunSpec:
    try:
        preset = _PRESETS[input_name]
    except KeyError as error:
        choices = ", ".join(sorted(_PRESETS))
        raise ValueError(f"unsupported K-MPC input {input_name!r}; choose from {choices}") from error
    return KoopmanMpcRunSpec(
        input_name=preset.input_name,
        config_rel=preset.config_rel,
        scene_rel=preset.scene_rel,
        steps=_derive_steps(_read_config(project_root, preset.config_rel)),
        description=preset.description,
    )


def validate_output_name(output_name: str) -> str:
    return _safe_id(output_name, "output name")


def default_output_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_koopman_mpc")


def build_koopman_mpc_manifest(
    spec: KoopmanMpcRunSpec, output_name: str, mode: str
) -> RunManifest:
    validate_output_name(output_name)
    if mode not in {"batch", "gui"}:
        raise ValueError(f"unsupported execution mode {mode!r}")
    return RunManifest(
        run_id=output_name,
        pipeline_id="trunk_koopman_mpc",
        input_id=spec.input_name,
        algorithm_id="koopman_mpc",
        config_rel=spec.config_rel,
        scene_rel=spec.scene_rel,
        artifact_profile="koopman_mpc_tracking",
        steps=spec.steps,
        mode=mode,
        timeout_s=600,
        gui_description=spec.description,
    )


def run_koopman_mpc_experiment(
    project_root: Path,
    spec: KoopmanMpcRunSpec,
    output_name: str,
    *,
    target: str,
    mode: str,
) -> int:
    manifest = build_koopman_mpc_manifest(spec, output_name, mode)
    resolved_target = target
    if target == "auto":
        resolved_target = (
            "server" if project_root.as_posix().startswith(_REMOTE_WORKSPACE_PREFIX) else "local"
        )
    environment = dict(os.environ)
    environment["EXPERIMENT_RUN_MANIFEST"] = manifest.to_json()
    if resolved_target == "local":
        if mode != "batch":
            raise ValueError("GUI mode must be run from the remote XFCE workspace")
        if not (project_root / "scripts/remote/config.local.sh").is_file():
            raise ValueError("local remote configuration is missing")
        runner = project_root / "scripts/remote/run_experiment.sh"
    elif resolved_target == "server":
        runner = project_root / "scripts/server/run_experiment.sh"
    else:
        raise ValueError(f"unsupported execution target {target!r}")
    return subprocess.run(["bash", str(runner), output_name], env=environment, check=False).returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one registered direct Koopman-MPC Trunk experiment."
    )
    parser.add_argument("--input", default="line", help="registered K-MPC reference input")
    parser.add_argument("--output", default=None, help="run ID (default: generated UTC timestamp)")
    parser.add_argument("--mode", choices=("batch", "gui"), default="batch")
    parser.add_argument("--target", choices=("auto", "local", "server"), default="auto")
    parser.add_argument("--list", action="store_true", help="list registered K-MPC inputs")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        if args.list:
            if args.output or args.mode != "batch" or args.target != "auto":
                raise ValueError("--list cannot be combined with execution options")
            print("available registered K-MPC inputs:")
            for input_name in sorted(_PRESETS):
                spec = resolve_koopman_mpc_spec(input_name, project_root)
                print(f"  {spec.input_name} ({spec.steps} steps, {spec.config_rel})")
            return 0
        spec = resolve_koopman_mpc_spec(args.input, project_root)
        return run_koopman_mpc_experiment(
            project_root,
            spec,
            args.output or default_output_name(),
            target=args.target,
            mode=args.mode,
        )
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
