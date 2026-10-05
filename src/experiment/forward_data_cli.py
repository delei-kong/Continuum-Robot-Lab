"""Registered entrypoint for direct Trunk dynamics-data experiments."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

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
    )
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
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        if args.list:
            print(format_available_runs(project_root))
            return 0
        spec = resolve_forward_data_spec(args.input, project_root)
        output_name = args.output or default_output_name()
        return run_forward_data_experiment(
            project_root, spec, output_name, target=args.target, mode=args.mode
        )
    except ValueError as error:
        print(f"forward data entrypoint error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
