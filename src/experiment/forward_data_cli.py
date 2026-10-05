"""Registered entrypoint for direct Trunk dynamics-data experiments."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from simulation.forward_data import ForwardDataConfig

from .contracts import RUN_ID_PATTERN, RunManifest


_REMOTE_WORKSPACE_PREFIX = "/root/gpufree-share/"


@dataclass(frozen=True)
class ForwardDataPreset:
    input_name: str
    config_rel: str
    scene_rel: str
    description: str


@dataclass(frozen=True)
class ForwardDataRunSpec:
    input_name: str
    config_rel: str
    scene_rel: str
    steps: int
    description: str


_PRESETS = {
    "multisine_pilot": ForwardDataPreset(
        input_name="multisine_pilot",
        config_rel="configs/trunk_forward_multisine_pilot.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description=(
            "Direct 8-cable seeded multisine excitation; records cable telemetry, "
            "tip, and centerline state."
        ),
    ),
    "koopman_v1_train_low": ForwardDataPreset(
        input_name="koopman_v1_train_low",
        config_rel="configs/trunk_forward_koopman_v1_train_low.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 train split: low-amplitude direct 8-cable multisine.",
    ),
    "koopman_v1_train_medium": ForwardDataPreset(
        input_name="koopman_v1_train_medium",
        config_rel="configs/trunk_forward_koopman_v1_train_medium.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 train split: medium-amplitude direct 8-cable multisine.",
    ),
    "koopman_v1_train_high": ForwardDataPreset(
        input_name="koopman_v1_train_high",
        config_rel="configs/trunk_forward_koopman_v1_train_high.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 train split: high-amplitude direct 8-cable multisine.",
    ),
    "koopman_v1_train_mixed": ForwardDataPreset(
        input_name="koopman_v1_train_mixed",
        config_rel="configs/trunk_forward_koopman_v1_train_mixed.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 train split: higher-frequency direct 8-cable multisine.",
    ),
    "koopman_v1_validation_low": ForwardDataPreset(
        input_name="koopman_v1_validation_low",
        config_rel="configs/trunk_forward_koopman_v1_validation_low.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 validation split: held-out low-amplitude multisine.",
    ),
    "koopman_v1_validation_high": ForwardDataPreset(
        input_name="koopman_v1_validation_high",
        config_rel="configs/trunk_forward_koopman_v1_validation_high.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 validation split: held-out high-amplitude multisine.",
    ),
    "koopman_v1_test_medium": ForwardDataPreset(
        input_name="koopman_v1_test_medium",
        config_rel="configs/trunk_forward_koopman_v1_test_medium.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 test split: held-out medium-amplitude multisine.",
    ),
    "koopman_v1_test_high": ForwardDataPreset(
        input_name="koopman_v1_test_high",
        config_rel="configs/trunk_forward_koopman_v1_test_high.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        description="Koopman v1 test split: held-out high-amplitude multisine.",
    ),
}

_FORWARD_DATA_BATCHES = {
    "koopman_v1_train": (
        "koopman_v1_train_low",
        "koopman_v1_train_medium",
        "koopman_v1_train_high",
        "koopman_v1_train_mixed",
    ),
    "koopman_v1_validation": (
        "koopman_v1_validation_low",
        "koopman_v1_validation_high",
    ),
    "koopman_v1_test": (
        "koopman_v1_test_medium",
        "koopman_v1_test_high",
    ),
}


def _load_config(project_root: Path, config_rel: str) -> Mapping[str, Any]:
    config_path = (project_root / config_rel).resolve()
    try:
        config_path.relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError(f"configuration escapes project root: {config_rel}") from error
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"registered configuration is missing: {config_rel}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"registered configuration is invalid JSON: {config_rel}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"registered configuration must be a JSON object: {config_rel}")
    return payload


def resolve_forward_data_spec(input_name: str, project_root: Path) -> ForwardDataRunSpec:
    try:
        preset = _PRESETS[input_name]
    except KeyError as error:
        choices = ", ".join(sorted(_PRESETS))
        raise ValueError(f"unsupported forward-data input {input_name!r}; choose from {choices}") from error
    config = ForwardDataConfig.from_mapping(_load_config(project_root, preset.config_rel))
    return ForwardDataRunSpec(
        input_name=preset.input_name,
        config_rel=preset.config_rel,
        scene_rel=preset.scene_rel,
        steps=config.total_steps,
        description=preset.description,
    )


def validate_output_name(output_name: str) -> str:
    if not output_name or not RUN_ID_PATTERN.fullmatch(output_name):
        raise ValueError("output name must contain only letters, digits, '.', '_' or '-'")
    return output_name


def default_output_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_trunk_forward_data"


def build_forward_data_manifest(
    spec: ForwardDataRunSpec, output_name: str, mode: str
) -> RunManifest:
    validate_output_name(output_name)
    if mode not in {"batch", "gui"}:
        raise ValueError(f"unsupported execution mode {mode!r}")
    return RunManifest(
        run_id=output_name,
        pipeline_id="trunk_forward_data",
        input_id=spec.input_name,
        algorithm_id="direct_multisine",
        config_rel=spec.config_rel,
        scene_rel=spec.scene_rel,
        artifact_profile="trunk_forward_data",
        steps=spec.steps,
        mode=mode,
        timeout_s=300,
        gui_description=spec.description,
    )


def _run_manifest(project_root: Path, manifest: RunManifest, target: str) -> int:
    resolved_target = target
    if resolved_target == "auto":
        resolved_target = (
            "server"
            if project_root.as_posix().startswith(_REMOTE_WORKSPACE_PREFIX)
            else "local"
        )
    environment = dict(os.environ)
    environment["EXPERIMENT_RUN_MANIFEST"] = manifest.to_json()
    if resolved_target == "local":
        if manifest.mode != "batch":
            raise ValueError("GUI mode must be run from the remote XFCE workspace")
        if not (project_root / "scripts/remote/config.local.sh").is_file():
            raise ValueError("local remote configuration is missing")
        runner = project_root / "scripts/remote/run_experiment.sh"
    elif resolved_target == "server":
        runner = project_root / "scripts/server/run_experiment.sh"
    else:
        raise ValueError(f"unsupported execution target {target!r}")
    return subprocess.run(
        ["bash", str(runner), manifest.run_id], env=environment, check=False
    ).returncode


def run_forward_data_experiment(
    project_root: Path,
    spec: ForwardDataRunSpec,
    output_name: str,
    *,
    target: str,
    mode: str,
) -> int:
    return _run_manifest(
        project_root, build_forward_data_manifest(spec, output_name, mode), target
    )


def format_available_batches() -> str:
    lines = ["available controlled forward-data batches:"]
    for batch_name, input_names in _FORWARD_DATA_BATCHES.items():
        lines.append(f"  {batch_name}: {', '.join(input_names)}")
    return "\n".join(lines)


def resolve_forward_data_batch(
    batch_name: str, project_root: Path
) -> tuple[ForwardDataRunSpec, ...]:
    try:
        input_names = _FORWARD_DATA_BATCHES[batch_name]
    except KeyError as error:
        choices = ", ".join(sorted(_FORWARD_DATA_BATCHES))
        raise ValueError(
            f"unsupported forward-data batch {batch_name!r}; choose from {choices}"
        ) from error
    return tuple(resolve_forward_data_spec(input_name, project_root) for input_name in input_names)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def run_forward_data_batch(
    project_root: Path,
    batch_name: str,
    output_name: str,
    *,
    target: str,
    results_root: Path | None = None,
) -> int:
    """Run one registered data split with isolated, auditable episode runs."""

    validate_output_name(output_name)
    specs = resolve_forward_data_batch(batch_name, project_root)
    batch_root = results_root or project_root / "outputs" / "forward_data_batches"
    batch_dir = batch_root / output_name
    try:
        batch_dir.mkdir(parents=True)
    except FileExistsError as error:
        raise ValueError(f"batch output directory already exists: {batch_dir}") from error

    planned_cases: list[dict[str, Any]] = []
    for spec in specs:
        run_id = f"{output_name}__{spec.input_name}"
        validate_output_name(run_id)
        planned_cases.append(
            {
                "case_id": spec.input_name,
                "input": spec.input_name,
                "run_id": run_id,
                "manifest": build_forward_data_manifest(spec, run_id, "batch").to_mapping(),
            }
        )
    created_at = _utc_timestamp()
    _write_json(
        batch_dir / "batch_manifest.json",
        {
            "schema_version": 1,
            "batch_id": batch_name,
            "output_name": output_name,
            "target": target,
            "created_at_utc": created_at,
            "cases": planned_cases,
        },
    )

    case_results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": batch_name,
        "output_name": output_name,
        "status": "running",
        "created_at_utc": created_at,
        "target": target,
        "cases": case_results,
        "succeeded": 0,
        "failed": 0,
    }
    _write_batch_summary(batch_dir, summary, case_results)

    for planned, spec in zip(planned_cases, specs):
        started_at = _utc_timestamp()
        try:
            return_code = run_forward_data_experiment(
                project_root,
                spec,
                planned["run_id"],
                target=target,
                mode="batch",
            )
            error_message = ""
        except Exception as error:  # Continue so a failed episode does not hide later cases.
            return_code = None
            error_message = f"{type(error).__name__}: {error}"
        case_results.append(
            {
                "case_id": planned["case_id"],
                "input": spec.input_name,
                "run_id": planned["run_id"],
                "status": "succeeded" if return_code == 0 else "failed",
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


def format_available_runs(project_root: Path) -> str:
    lines = ["available forward-data inputs:"]
    for input_name in _PRESETS:
        spec = resolve_forward_data_spec(input_name, project_root)
        lines.append(f"  {spec.input_name} ({spec.steps} steps, {spec.config_rel})")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one registered direct Trunk dynamics-data experiment."
    )
    parser.add_argument("--input", default="multisine_pilot", help="registered data input")
    parser.add_argument("--output", default=None, help="run ID (default: generated UTC timestamp)")
    parser.add_argument("--mode", choices=("batch", "gui"), default="batch")
    parser.add_argument("--target", choices=("auto", "local", "server"), default="auto")
    parser.add_argument("--list", action="store_true", help="list registered data inputs")
    parser.add_argument(
        "--batch",
        default=None,
        help="run one registered forward-data batch instead of one input",
    )
    parser.add_argument(
        "--list-batches",
        action="store_true",
        help="list registered forward-data batch matrices",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        if args.list and args.list_batches:
            raise ValueError("--list and --list-batches cannot be combined")
        if args.list:
            print(format_available_runs(project_root))
            return 0
        if args.list_batches:
            print(format_available_batches())
            return 0
        output_name = args.output or default_output_name()
        if args.batch:
            if args.input != "multisine_pilot":
                raise ValueError("--input cannot be combined with --batch")
            if args.mode != "batch":
                raise ValueError("registered batches only support --mode batch")
            return run_forward_data_batch(
                project_root, args.batch, output_name, target=args.target
            )
        spec = resolve_forward_data_spec(args.input, project_root)
        return run_forward_data_experiment(
            project_root, spec, output_name, target=args.target, mode=args.mode
        )
    except ValueError as error:
        print(f"forward data entrypoint error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
