"""Controlled command-line entrypoint for supported Trunk tracking experiments."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import RUN_ID_PATTERN, RunManifest, TrackingPreset, TrackingRunSpec

_REMOTE_WORKSPACE_PREFIX = "/root/gpufree-share/"


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
_TRACKING_BATCHES = {
    # A deliberately small baseline matrix.  Adding a matrix is a reviewed
    # code change rather than a free-form command-line parameter scan.
    "baseline_trajectories": ("line", "ellipse"),
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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_runner_environment(spec: TrackingRunSpec) -> dict[str, str]:
    """Return the deprecated scene bridge for external compatibility only.

    The shared execution core no longer consumes these values.  They remain
    available for notebooks that imported the Phase-A helper directly.
    """

    return {
        "TRUNK_INVERSE_CONFIG_REL": spec.config_rel,
        "TRUNK_INVERSE_SCENE_REL": spec.scene_rel,
        "TRUNK_INVERSE_STEPS": str(spec.steps),
    }


def build_run_manifest(
    spec: TrackingRunSpec, output_name: str, mode: str
) -> RunManifest:
    """Create the one internal runtime request for a resolved tracking run."""

    validate_output_name(output_name)
    if mode not in {"batch", "gui"}:
        raise ValueError(f"unsupported execution mode {mode!r}")
    return RunManifest(
        run_id=output_name,
        pipeline_id="trunk_tracking",
        input_id=spec.input_name,
        algorithm_id=spec.algorithm,
        config_rel=spec.config_rel,
        scene_rel=spec.scene_rel,
        artifact_profile=spec.artifact_profile,
        steps=spec.steps,
        mode=mode,
        timeout_s=300,
        gui_description=spec.gui_description,
    )


def _runtime_environment(
    spec: TrackingRunSpec, output_name: str, mode: str
) -> dict[str, str]:
    environment = dict(os.environ)
    environment["EXPERIMENT_RUN_MANIFEST"] = build_run_manifest(
        spec, output_name, mode
    ).to_json()
    return environment


def run_local_remote(project_root: Path, spec: TrackingRunSpec, output_name: str) -> int:
    runner = project_root / "scripts" / "remote" / "run_experiment.sh"
    completed = subprocess.run(
        ["bash", str(runner), output_name],
        env=_runtime_environment(spec, output_name, "batch"),
        check=False,
    )
    return completed.returncode


def run_server_batch(project_root: Path, spec: TrackingRunSpec, output_name: str) -> int:
    runner = project_root / "scripts" / "server" / "run_experiment.sh"
    return subprocess.run(
        ["bash", str(runner), output_name],
        env=_runtime_environment(spec, output_name, "batch"),
        check=False,
    ).returncode


def run_server_gui(project_root: Path, spec: TrackingRunSpec, output_name: str) -> int:
    runner = project_root / "scripts" / "server" / "run_experiment.sh"
    return subprocess.run(
        ["bash", str(runner), output_name],
        env=_runtime_environment(spec, output_name, "gui"),
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


def format_available_batches() -> str:
    lines = ["available controlled tracking batches:"]
    for batch_name, input_names in _TRACKING_BATCHES.items():
        lines.append(f"  {batch_name}: {', '.join(input_names)}")
    return "\n".join(lines)


def resolve_tracking_batch(
    batch_name: str, algorithm: str, project_root: Path
) -> tuple[TrackingRunSpec, ...]:
    try:
        input_names = _TRACKING_BATCHES[batch_name]
    except KeyError as error:
        choices = ", ".join(sorted(_TRACKING_BATCHES))
        raise ValueError(
            f"unsupported tracking batch {batch_name!r}; choose from {choices}"
        ) from error
    return tuple(
        resolve_tracking_spec(input_name, algorithm, project_root)
        for input_name in input_names
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_batch_summary(
    batch_dir: Path, summary: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]
) -> None:
    _write_json(batch_dir / "summary.json", summary)
    with (batch_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "case_id",
                "input",
                "run_id",
                "status",
                "return_code",
                "started_at_utc",
                "finished_at_utc",
                "error",
            ),
        )
        writer.writeheader()
        writer.writerows(cases)


def run_tracking_batch(
    project_root: Path,
    batch_name: str,
    algorithm: str,
    output_name: str,
    *,
    target: str,
    results_root: Path | None = None,
) -> int:
    """Run a code-registered batch without exposing arbitrary scan parameters.

    Each case delegates to the same single-run API and retains an independent
    run ID.  Completion data is persisted after every case so one failed case
    cannot erase the record of preceding successes or prevent later cases.
    """

    validate_output_name(output_name)
    cases = resolve_tracking_batch(batch_name, algorithm, project_root)
    batch_root = results_root or project_root / "outputs" / "tracking_batches"
    batch_dir = batch_root / output_name
    try:
        batch_dir.mkdir(parents=True)
    except FileExistsError as error:
        raise ValueError(f"batch output directory already exists: {batch_dir}") from error

    planned_cases: list[dict[str, Any]] = []
    for spec in cases:
        run_id = f"{output_name}__{spec.input_name}"
        validate_output_name(run_id)
        planned_cases.append(
            {
                "case_id": spec.input_name,
                "input": spec.input_name,
                "run_id": run_id,
                "manifest": build_run_manifest(spec, run_id, "batch").to_mapping(),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": batch_name,
        "output_name": output_name,
        "algorithm": _canonical(algorithm, _ALGORITHM_ALIASES, "algorithm"),
        "target": target,
        "created_at_utc": _utc_timestamp(),
        "cases": planned_cases,
    }
    _write_json(batch_dir / "batch_manifest.json", manifest)

    case_results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": batch_name,
        "output_name": output_name,
        "status": "running",
        "created_at_utc": manifest["created_at_utc"],
        "target": target,
        "cases": case_results,
        "succeeded": 0,
        "failed": 0,
    }
    _write_batch_summary(batch_dir, summary, case_results)

    for planned, spec in zip(planned_cases, cases):
        started_at = _utc_timestamp()
        try:
            return_code = run_tracking_experiment(
                project_root,
                spec,
                planned["run_id"],
                target=target,
                mode="batch",
            )
            error_message = ""
        except Exception as error:  # Preserve later cases after an adapter failure.
            return_code = None
            error_message = f"{type(error).__name__}: {error}"
        succeeded = return_code == 0
        case_results.append(
            {
                "case_id": planned["case_id"],
                "input": spec.input_name,
                "run_id": planned["run_id"],
                "status": "succeeded" if succeeded else "failed",
                "return_code": return_code,
                "started_at_utc": started_at,
                "finished_at_utc": _utc_timestamp(),
                "error": error_message,
            }
        )
        summary["succeeded"] = sum(
            result["status"] == "succeeded" for result in case_results
        )
        summary["failed"] = len(case_results) - summary["succeeded"]
        _write_batch_summary(batch_dir, summary, case_results)

    summary["status"] = "complete"
    summary["finished_at_utc"] = _utc_timestamp()
    _write_batch_summary(batch_dir, summary, case_results)
    print(f"batch_output_dir={batch_dir}")
    print(f"batch_succeeded={summary['succeeded']}")
    print(f"batch_failed={summary['failed']}")
    return 0 if summary["failed"] == 0 else 1


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
        default=None,
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
    parser.add_argument(
        "--batch",
        default=None,
        help="run one registered batch matrix instead of a single input",
    )
    parser.add_argument(
        "--list-batches",
        action="store_true",
        help="list registered tracking batch matrices",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    if args.list and args.list_batches:
        parser.error("--list and --list-batches cannot be combined")
    if args.list:
        try:
            print(format_available_runs(project_root))
        except ValueError as error:
            parser.error(str(error))
        return 0
    if args.list_batches:
        print(format_available_batches())
        return 0
    output_name = args.output or default_output_name()
    try:
        if args.batch:
            if args.input is not None:
                raise ValueError("--input cannot be combined with --batch")
            if args.mode != "batch":
                raise ValueError("registered batches only support --mode batch")
            return run_tracking_batch(
                project_root,
                args.batch,
                args.algorithm,
                output_name,
                target=args.target,
            )
        spec = resolve_tracking_spec(args.input or "line", args.algorithm, project_root)
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
