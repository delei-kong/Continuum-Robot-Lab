"""Controlled command-line entrypoint for supported Trunk tracking experiments."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_REMOTE_WORKSPACE_PREFIX = "/root/gpufree-share/"


@dataclass(frozen=True)
class TrackingPreset:
    """Code-owned description of one supported tracking input."""

    input_name: str
    config_rel: str
    scene_rel: str
    artifact_profile: str
    gui_description: str


@dataclass(frozen=True)
class TrackingRunSpec:
    """A preset resolved against its configuration-derived step count."""

    input_name: str
    algorithm: str
    config_rel: str
    scene_rel: str
    artifact_profile: str
    steps: int
    gui_description: str

    @property
    def trajectory(self) -> str:
        """Compatibility name for callers that previously selected a trajectory."""

        return self.input_name

    @property
    def controller(self) -> str:
        """Compatibility name for callers that previously selected a controller."""

        return self.algorithm


_INPUT_ALIASES = {
    "line": "line",
    "timed_linear": "line",
    "ellipse": "ellipse",
    "periodic_ellipse": "ellipse",
    "circle": "circle",
    "triangle": "rounded_triangle",
    "rounded_triangle": "rounded_triangle",
    "square": "rounded_square",
    "rounded_square": "rounded_square",
    "target": "single_target",
    "single_target": "single_target",
    "periodic_random": "periodic_random",
    "random": "periodic_random",
    "random_waypoints": "periodic_random",
}
_ALGORITHM_ALIASES = {
    "reference": "reference_goal",
    "reference_goal": "reference_goal",
}
_PRESETS = {
    "line": TrackingPreset(
        input_name="line",
        config_rel="configs/trunk_trajectory_tracking_line.json",
        scene_rel="src/simulation/scenes/trunk_trajectory_tracking.py",
        artifact_profile="trajectory_tracking",
        gui_description=(
            "Pipeline: timed line trajectory + reference_goal + sofa_inverse_qp\n"
            "Green reference path; green point: current reference; red point: actual tip; "
            "orange line: actual trajectory"
        ),
    ),
    "ellipse": TrackingPreset(
        input_name="ellipse",
        config_rel="configs/trunk_trajectory_tracking_ellipse.json",
        scene_rel="src/simulation/scenes/trunk_trajectory_tracking.py",
        artifact_profile="trajectory_tracking",
        gui_description=(
            "Pipeline: closed ellipse trajectory + reference_goal + sofa_inverse_qp\n"
            "Green reference path; green point: current reference; red point: actual tip; "
            "orange line: actual trajectory"
        ),
    ),
    "circle": TrackingPreset(
        input_name="circle",
        config_rel="configs/trunk_trajectory_tracking_circle.json",
        scene_rel="src/simulation/scenes/trunk_trajectory_tracking.py",
        artifact_profile="trajectory_tracking",
        gui_description=(
            "Pipeline: closed circle trajectory + reference_goal + sofa_inverse_qp\n"
            "Green reference path; green point: current reference; red point: actual tip; "
            "orange line: actual trajectory"
        ),
    ),
    "rounded_triangle": TrackingPreset(
        input_name="rounded_triangle",
        config_rel="configs/trunk_trajectory_tracking_rounded_triangle.json",
        scene_rel="src/simulation/scenes/trunk_trajectory_tracking.py",
        artifact_profile="trajectory_tracking",
        gui_description=(
            "Pipeline: rounded triangle trajectory + reference_goal + sofa_inverse_qp\n"
            "Green reference path; green point: current reference; red point: actual tip; "
            "orange line: actual trajectory"
        ),
    ),
    "rounded_square": TrackingPreset(
        input_name="rounded_square",
        config_rel="configs/trunk_trajectory_tracking_rounded_square.json",
        scene_rel="src/simulation/scenes/trunk_trajectory_tracking.py",
        artifact_profile="trajectory_tracking",
        gui_description=(
            "Pipeline: rounded square trajectory + reference_goal + sofa_inverse_qp\n"
            "Green reference path; green point: current reference; red point: actual tip; "
            "orange line: actual trajectory"
        ),
    ),
    "single_target": TrackingPreset(
        input_name="single_target",
        config_rel="configs/trunk_inverse_tracking.json",
        scene_rel="src/simulation/scenes/trunk_inverse_tracking.py",
        artifact_profile="trunk_inverse_tracking",
        gui_description=(
            "Pipeline: single target tracking + reference_goal + sofa_inverse_qp\n"
            "Yellow marker: final target; green point: current reference; red point: actual tip; "
            "orange line: actual trajectory"
        ),
    ),
    "periodic_random": TrackingPreset(
        input_name="periodic_random",
        config_rel="configs/trunk_inverse_periodic_random.json",
        scene_rel="src/simulation/scenes/trunk_inverse_tracking.py",
        artifact_profile="trunk_inverse_tracking",
        gui_description=(
            "Pipeline: seeded periodic random waypoint tracking + reference_goal + "
            "sofa_inverse_qp\n"
            "Fixed colored markers: generated waypoints; green point: current reference; "
            "red point: actual tip; orange line: actual trajectory"
        ),
    ),
}


def _canonical(value: str, aliases: Mapping[str, str], label: str) -> str:
    try:
        return aliases[value]
    except KeyError as error:
        choices = ", ".join(sorted(set(aliases.values())))
        raise ValueError(f"unsupported {label} {value!r}; choose from {choices}") from error


def _finite_positive(mapping: Mapping[str, Any], name: str) -> float:
    value = mapping.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"configuration field {name!r} must be a positive number")
    return float(value)


def _positive_integer(mapping: Mapping[str, Any], name: str) -> int:
    value = mapping.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"configuration field {name!r} must be a positive integer")
    return value


def _whole_steps(duration_s: float, dt_s: float) -> int:
    steps = round(duration_s / dt_s)
    if steps < 1 or abs(steps * dt_s - duration_s) > 1e-9:
        raise ValueError("experiment duration must be an integer multiple of dt")
    return steps


def derive_steps_from_config(config: Mapping[str, Any]) -> int:
    """Derive steps from a supported configuration; never accept a duplicate override."""

    dt_s = _finite_positive(config, "dt")
    control_rate_hz = config.get("control_rate_hz")
    if control_rate_hz is not None:
        control_rate = _finite_positive(config, "control_rate_hz")
        if abs(dt_s * control_rate - 1.0) > 1e-9:
            raise ValueError("one simulation step must equal one control period")

    if "duration_s" in config:
        return _whole_steps(_finite_positive(config, "duration_s"), dt_s)

    if config.get("tracking_mode") == "periodic_random_waypoints":
        duration_s = (
            _finite_positive(config, "settle_duration_s")
            + _positive_integer(config, "waypoint_count")
            * _positive_integer(config, "cycle_count")
            * (
                _finite_positive(config, "transition_duration_s")
                + _finite_positive(config, "hold_duration_s")
            )
        )
        return _whole_steps(duration_s, dt_s)

    duration_s = sum(
        _finite_positive(config, name)
        for name in ("settle_duration_s", "transition_duration_s", "hold_duration_s")
    )
    return _whole_steps(duration_s, dt_s)


def _load_config(project_root: Path, config_rel: str) -> Mapping[str, Any]:
    config_path = (project_root / config_rel).resolve()
    try:
        config_path.relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError(f"configuration escapes project root: {config_rel}") from error
    try:
        with config_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as error:
        raise ValueError(f"registered configuration is missing: {config_rel}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"registered configuration is invalid JSON: {config_rel}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"registered configuration must be a JSON object: {config_rel}")
    return payload


def resolve_tracking_spec(
    input_name: str,
    algorithm: str,
    project_root: Path,
) -> TrackingRunSpec:
    canonical_input = _canonical(input_name, _INPUT_ALIASES, "tracking input")
    canonical_algorithm = _canonical(algorithm, _ALGORITHM_ALIASES, "algorithm")
    preset = _PRESETS[canonical_input]
    steps = derive_steps_from_config(_load_config(project_root, preset.config_rel))
    return TrackingRunSpec(
        input_name=preset.input_name,
        algorithm=canonical_algorithm,
        config_rel=preset.config_rel,
        scene_rel=preset.scene_rel,
        artifact_profile=preset.artifact_profile,
        steps=steps,
        gui_description=preset.gui_description,
    )


def resolve_run_spec(
    trajectory: str, controller: str, project_root: Path | None = None
) -> TrackingRunSpec:
    """Compatibility alias for the earlier trajectory/controller-only registry."""

    root = project_root or Path(__file__).resolve().parents[2]
    return resolve_tracking_spec(trajectory, controller, root)


def validate_output_name(output_name: str) -> str:
    if not output_name or not RUN_ID_PATTERN.fullmatch(output_name):
        raise ValueError(
            "output name must contain only letters, digits, '.', '_' or '-'; "
            "it must not contain a path"
        )
    return output_name


def default_output_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_tracking"


def build_runner_environment(spec: TrackingRunSpec) -> dict[str, str]:
    """Bridge the resolved spec to the existing Phase-A SOFA adapters."""

    return {
        "TRUNK_INVERSE_CONFIG_REL": spec.config_rel,
        "TRUNK_INVERSE_SCENE_REL": spec.scene_rel,
        "TRUNK_INVERSE_STEPS": str(spec.steps),
    }


def _server_environment(project_root: Path, spec: TrackingRunSpec) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(build_runner_environment(spec))
    environment["TRUNK_INVERSE_CONFIG"] = str(project_root / spec.config_rel)
    environment["TRUNK_INVERSE_SCENE"] = str(project_root / spec.scene_rel)
    environment["TRUNK_INVERSE_GUI_DESCRIPTION"] = spec.gui_description
    return environment


def run_local_remote(project_root: Path, spec: TrackingRunSpec, output_name: str) -> int:
    environment = dict(os.environ)
    environment.update(build_runner_environment(spec))
    runner = project_root / "scripts" / "remote" / "run_trunk_inverse_tracking.sh"
    completed = subprocess.run(
        ["bash", str(runner), output_name], env=environment, check=False
    )
    return completed.returncode


def run_server_batch(project_root: Path, spec: TrackingRunSpec, output_name: str) -> int:
    runner = project_root / "scripts" / "server" / "run_trunk_trajectory_tracking_batch.sh"
    return subprocess.run(
        ["bash", str(runner), output_name],
        env=_server_environment(project_root, spec),
        check=False,
    ).returncode


def run_server_gui(project_root: Path, spec: TrackingRunSpec, output_name: str) -> int:
    runner = project_root / "scripts" / "server" / "run_trunk_inverse_tracking_gui.sh"
    return subprocess.run(
        ["bash", str(runner), output_name],
        env=_server_environment(project_root, spec),
        check=False,
    ).returncode


def run_remote_experiment(
    project_root: Path,
    trajectory: str,
    controller: str,
    output_name: str,
) -> int:
    """Compatibility wrapper for the former local-to-remote trajectory CLI."""

    spec = resolve_tracking_spec(trajectory, controller, project_root)
    return run_tracking_experiment(
        project_root, spec, output_name, target="local", mode="batch"
    )


def run_remote_workspace_experiment(
    project_root: Path,
    trajectory: str,
    controller: str,
    output_name: str,
) -> int:
    """Compatibility wrapper for the former remote-workspace batch CLI."""

    spec = resolve_tracking_spec(trajectory, controller, project_root)
    return run_tracking_experiment(
        project_root, spec, output_name, target="server", mode="batch"
    )


def run_remote_workspace_gui_experiment(
    project_root: Path,
    trajectory: str,
    controller: str,
    output_name: str,
) -> int:
    """Compatibility wrapper for the former remote-workspace GUI CLI."""

    spec = resolve_tracking_spec(trajectory, controller, project_root)
    return run_tracking_experiment(
        project_root, spec, output_name, target="server", mode="gui"
    )


def run_tracking_experiment(
    project_root: Path,
    spec: TrackingRunSpec,
    output_name: str,
    *,
    target: str,
    mode: str,
) -> int:
    validate_output_name(output_name)
    resolved_target = target
    if resolved_target == "auto":
        resolved_target = (
            "server"
            if project_root.as_posix().startswith(_REMOTE_WORKSPACE_PREFIX)
            else "local"
        )
    if resolved_target == "local":
        if mode != "batch":
            raise ValueError("GUI mode must be run from the remote XFCE workspace")
        local_config = project_root / "scripts" / "remote" / "config.local.sh"
        if not local_config.is_file():
            raise ValueError(
                "scripts/remote/config.local.sh is missing; run from the remote workspace "
                "or configure the local remote connection"
            )
        return run_local_remote(project_root, spec, output_name)
    if resolved_target == "server":
        if mode == "gui":
            return run_server_gui(project_root, spec, output_name)
        return run_server_batch(project_root, spec, output_name)
    raise ValueError(f"unsupported execution target {target!r}")


def format_available_runs(project_root: Path | None = None) -> str:
    root = project_root or Path(__file__).resolve().parents[2]
    lines = ["available tracking input/algorithm combinations:"]
    for input_name in _PRESETS:
        spec = resolve_tracking_spec(input_name, "reference_goal", root)
        lines.append(
            f"  {spec.input_name} {spec.algorithm} "
            f"({spec.steps} steps, {spec.config_rel}, {spec.artifact_profile})"
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one registered Trunk tracking experiment."
    )
    parser.add_argument(
        "--input",
        default="line",
        help=(
            "line, ellipse, circle, rounded_triangle, rounded_square, "
            "single_target, or periodic_random (default: line)"
        ),
    )
    parser.add_argument(
        "--algorithm",
        default="reference_goal",
        help="registered tracking algorithm (default: reference_goal)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="run ID (default: generated UTC timestamp)",
    )
    parser.add_argument(
        "--mode",
        choices=("batch", "gui"),
        default="batch",
        help="execution display mode (default: batch)",
    )
    parser.add_argument(
        "--gui",
        action="store_const",
        const="gui",
        dest="mode",
        help="compatibility alias for --mode gui",
    )
    parser.add_argument(
        "--target",
        choices=("auto", "local", "server"),
        default="auto",
        help="execution location (default: infer from workspace)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list registered tracking inputs and their resolved step counts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    if args.list:
        try:
            print(format_available_runs(project_root))
        except ValueError as error:
            parser.error(str(error))
        return 0
    output_name = args.output or default_output_name()
    try:
        spec = resolve_tracking_spec(args.input, args.algorithm, project_root)
        validate_output_name(output_name)
        return run_tracking_experiment(
            project_root,
            spec,
            output_name,
            target=args.target,
            mode=args.mode,
        )
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
