"""Registry and command construction for remote trajectory experiments."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class TrajectoryRunSpec:
    trajectory: str
    controller: str
    config_rel: str
    steps: int


_TRAJECTORY_ALIASES = {
    "line": "line",
    "timed_linear": "line",
    "ellipse": "ellipse",
    "periodic_ellipse": "ellipse",
    "circle": "circle",
    "triangle": "rounded_triangle",
    "rounded_triangle": "rounded_triangle",
    "square": "rounded_square",
    "rounded_square": "rounded_square",
}
_CONTROLLER_ALIASES = {
    "reference": "reference_goal",
    "reference_goal": "reference_goal",
}
_RUN_SPECS = {
    ("line", "reference_goal"): TrajectoryRunSpec(
        trajectory="line",
        controller="reference_goal",
        config_rel="configs/trunk_trajectory_tracking_line.json",
        steps=200,
    ),
    ("ellipse", "reference_goal"): TrajectoryRunSpec(
        trajectory="ellipse",
        controller="reference_goal",
        config_rel="configs/trunk_trajectory_tracking_ellipse.json",
        steps=350,
    ),
    ("circle", "reference_goal"): TrajectoryRunSpec(
        trajectory="circle",
        controller="reference_goal",
        config_rel="configs/trunk_trajectory_tracking_circle.json",
        steps=350,
    ),
    ("rounded_triangle", "reference_goal"): TrajectoryRunSpec(
        trajectory="rounded_triangle",
        controller="reference_goal",
        config_rel="configs/trunk_trajectory_tracking_rounded_triangle.json",
        steps=350,
    ),
    ("rounded_square", "reference_goal"): TrajectoryRunSpec(
        trajectory="rounded_square",
        controller="reference_goal",
        config_rel="configs/trunk_trajectory_tracking_rounded_square.json",
        steps=350,
    ),
}


def resolve_run_spec(trajectory: str, controller: str) -> TrajectoryRunSpec:
    try:
        canonical_trajectory = _TRAJECTORY_ALIASES[trajectory]
    except KeyError as error:
        raise ValueError(
            f"unsupported trajectory {trajectory!r}; choose from line, ellipse, "
            "circle, rounded_triangle, rounded_square"
        ) from error
    try:
        canonical_controller = _CONTROLLER_ALIASES[controller]
    except KeyError as error:
        raise ValueError(
            f"unsupported controller {controller!r}; choose from reference_goal"
        ) from error
    try:
        return _RUN_SPECS[(canonical_trajectory, canonical_controller)]
    except KeyError as error:
        raise ValueError(
            f"unsupported trajectory/controller combination: "
            f"{canonical_trajectory}/{canonical_controller}"
        ) from error


def validate_output_name(output_name: str) -> str:
    if not output_name or not RUN_ID_PATTERN.fullmatch(output_name):
        raise ValueError(
            "output name must contain only letters, digits, '.', '_' or '-'; "
            "it must not contain a path"
        )
    return output_name


def default_output_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_trunk_trajectory_cli"


def build_runner_environment(spec: TrajectoryRunSpec) -> dict[str, str]:
    return {
        "TRUNK_INVERSE_CONFIG_REL": spec.config_rel,
        "TRUNK_INVERSE_SCENE_REL": "src/simulation/scenes/trunk_trajectory_tracking.py",
        "TRUNK_INVERSE_STEPS": str(spec.steps),
    }


def run_remote_experiment(
    project_root: Path,
    trajectory: str,
    controller: str,
    output_name: str,
) -> int:
    spec = resolve_run_spec(trajectory, controller)
    validate_output_name(output_name)
    runner = project_root / "scripts" / "remote" / "run_trunk_inverse_tracking.sh"
    environment = dict(os.environ)
    environment.update(build_runner_environment(spec))
    completed = subprocess.run(
        ["bash", str(runner), output_name], env=environment, check=False
    )
    return completed.returncode


def run_remote_workspace_experiment(
    project_root: Path,
    trajectory: str,
    controller: str,
    output_name: str,
) -> int:
    spec = resolve_run_spec(trajectory, controller)
    validate_output_name(output_name)
    runner = project_root / "scripts" / "server" / "run_trunk_trajectory_tracking_batch.sh"
    environment = dict(os.environ)
    environment.update(build_runner_environment(spec))
    environment["TRUNK_INVERSE_CONFIG"] = str(project_root / spec.config_rel)
    environment["TRUNK_INVERSE_SCENE"] = str(
        project_root / "src" / "simulation" / "scenes" / "trunk_trajectory_tracking.py"
    )
    completed = subprocess.run(
        ["bash", str(runner), output_name], env=environment, check=False
    )
    return completed.returncode


def run_remote_workspace_gui_experiment(
    project_root: Path,
    trajectory: str,
    controller: str,
    output_name: str,
) -> int:
    spec = resolve_run_spec(trajectory, controller)
    validate_output_name(output_name)
    runner = project_root / "scripts" / "server" / "run_trunk_trajectory_tracking_gui.sh"
    environment = dict(os.environ)
    environment.update(build_runner_environment(spec))
    environment["TRUNK_INVERSE_CONFIG"] = str(project_root / spec.config_rel)
    environment["TRUNK_INVERSE_SCENE"] = str(
        project_root / "src" / "simulation" / "scenes" / "trunk_trajectory_tracking.py"
    )
    environment["TRUNK_INVERSE_GUI_DESCRIPTION"] = (
        f"Pipeline: {spec.trajectory} + {spec.controller} + sofa_inverse_qp\n"
        "Green reference path; green point: current reference; red point: actual tip; "
        "orange line: actual trajectory"
    )
    completed = subprocess.run(
        ["bash", str(runner), output_name], env=environment, check=False
    )
    return completed.returncode


def format_available_runs() -> str:
    lines = ["available trajectory/controller combinations:"]
    for spec in _RUN_SPECS.values():
        lines.append(
            f"  {spec.trajectory} {spec.controller} "
            f"({spec.steps} steps, {spec.config_rel})"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run one configured Trunk trajectory/controller experiment remotely."
    )
    parser.add_argument(
        "trajectory",
        nargs="?",
        default="line",
        help=(
            "line, ellipse, circle, rounded_triangle or rounded_square "
            "(default: line)"
        ),
    )
    parser.add_argument(
        "controller",
        nargs="?",
        default="reference_goal",
        help="reference_goal (default: reference_goal)",
    )
    parser.add_argument(
        "output_name",
        nargs="?",
        default=None,
        help="remote run_id (default: UTC timestamp)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list registered trajectory/controller combinations",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="open the remote desktop visualization instead of batch mode",
    )
    args = parser.parse_args(argv)
    if args.list:
        print(format_available_runs())
        return 0
    output_name = args.output_name or default_output_name()
    try:
        spec = resolve_run_spec(args.trajectory, args.controller)
        validate_output_name(output_name)
    except ValueError as error:
        parser.error(str(error))
    project_root = Path(__file__).resolve().parents[2]
    if project_root.as_posix().startswith("/root/gpufree-share/"):
        if args.gui:
            return run_remote_workspace_gui_experiment(
                project_root, args.trajectory, args.controller, output_name
            )
        return run_remote_workspace_experiment(
            project_root, args.trajectory, args.controller, output_name
        )
    local_config = project_root / "scripts" / "remote" / "config.local.sh"
    if local_config.is_file():
        if args.gui:
            parser.error("--gui must be run from the remote XFCE workspace")
        return run_remote_experiment(
            project_root, args.trajectory, args.controller, output_name
        )
    parser.error(
        "scripts/remote/config.local.sh is missing; run this command from the local "
        "workspace, or use a synchronized remote workspace"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
