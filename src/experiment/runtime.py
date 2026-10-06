"""Shared SOFA run lifecycle for registered experiments.

The module is intentionally independent of the local SSH and XFCE boundaries.
Those boundaries supply a resolved :class:`RunManifest` and runtime paths; this
module owns run-directory preparation, command construction, logging,
metadata, artifact verification, and final status markers.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .contracts import RunManifest


@dataclass(frozen=True)
class ArtifactVerification:
    """Result of validating the common tracking artifact contract."""

    row_count: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_workspace_path(workspace: Path, relative_path: str, prefix: str) -> Path:
    if not relative_path.startswith(prefix) or ".." in Path(relative_path).parts:
        raise ValueError(f"manifest path must be below {prefix}: {relative_path}")
    candidate = (workspace / relative_path).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError as error:
        raise ValueError(f"manifest path escapes workspace: {relative_path}") from error
    return candidate


def build_sofa_command(
    manifest: RunManifest,
    *,
    runsofa: Path,
    sofa_validation_library: Path,
    scene: Path,
) -> tuple[str, ...]:
    """Build the supported SOFA command shape for a registered manifest."""

    command: list[str] = [
        str(runsofa),
        "-a",
        "-n",
        str(manifest.steps),
        "-l",
        str(sofa_validation_library),
        "-l",
        "SofaPython3",
        "-l",
        "SoftRobots",
    ]
    if manifest.pipeline_id == "trunk_tracking":
        command.extend(("-l", "SoftRobots.Inverse"))
    elif manifest.pipeline_id not in {"trunk_forward_data", "trunk_koopman_mpc"}:
        raise ValueError(f"unsupported experiment pipeline: {manifest.pipeline_id}")
    if manifest.mode == "batch":
        command.extend(("-g", "batch"))
    else:
        command.extend(("-l", "SofaImGui", "-g", "imgui"))
    command.append(str(scene))
    return tuple(command)


def _trajectory_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _verify_koopman_mpc_artifacts(run_dir: Path, records: Path) -> tuple[str, ...]:
    """Check persisted direct actions against the fixed K-MPC safety contract."""

    errors: list[str] = []
    try:
        effective = json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
        provenance = json.loads((run_dir / "model_provenance.json").read_text(encoding="utf-8"))
        if not isinstance(effective, dict) or not isinstance(provenance, dict):
            raise ValueError("configuration or provenance is not a JSON object")
        safety = effective.get("action_safety")
        model = effective.get("model")
        if not isinstance(safety, dict) or not isinstance(model, dict):
            raise ValueError("K-MPC effective configuration is incomplete")
        maxima = safety.get("maximum_displacements_mm")
        delta = safety.get("max_command_delta_mm")
        if (
            not isinstance(maxima, list)
            or not maxima
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0.0 for value in maxima)
            or not isinstance(delta, (int, float))
            or isinstance(delta, bool)
            or not math.isfinite(delta)
            or delta <= 0.0
        ):
            raise ValueError("K-MPC action safety configuration is invalid")
        if provenance.get("final_output_id") != model.get("final_output_id"):
            raise ValueError("K-MPC model provenance does not match its effective configuration")
        if not isinstance(provenance.get("selected_model"), str) or not provenance["selected_model"]:
            raise ValueError("K-MPC model provenance has no selected model")
        if (
            isinstance(provenance.get("lift_dimension"), bool)
            or not isinstance(provenance.get("lift_dimension"), int)
            or provenance["lift_dimension"] < 1
        ):
            raise ValueError("K-MPC model provenance has an invalid lift dimension")
        previous = [0.0] * len(maxima)
        with records.open(newline="", encoding="utf-8") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                if row.get("command_kind") != "cable_displacement":
                    raise ValueError(f"row {row_number}: K-MPC command kind is invalid")
                command = json.loads(row.get("command_cables_mm", ""))
                if not isinstance(command, list) or len(command) != len(maxima):
                    raise ValueError(f"row {row_number}: K-MPC command vector is invalid")
                values = [float(value) for value in command]
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"row {row_number}: K-MPC command is non-finite")
                if any(value < -1e-9 or value > maximum + 1e-9 for value, maximum in zip(values, maxima)):
                    raise ValueError(f"row {row_number}: K-MPC command exceeds its bounds")
                if any(abs(value - old) > float(delta) + 1e-9 for value, old in zip(values, previous)):
                    raise ValueError(f"row {row_number}: K-MPC command exceeds its slew bound")
                previous = values
                diagnostics = json.loads(row.get("controller_diagnostics", ""))
                if not isinstance(diagnostics, dict) or not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    for value in diagnostics.values()
                ):
                    raise ValueError(f"row {row_number}: K-MPC diagnostics are invalid")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        errors.append(f"K-MPC artifact validation failed: {error}")
    return tuple(errors)


def verify_tracking_artifacts(
    run_dir: Path,
    manifest: RunManifest,
    *,
    process_exit_code: int | None = None,
    accept_completed_signal: bool = False,
) -> ArtifactVerification:
    """Validate the registered tracking or forward-data artifact contract."""

    errors: list[str] = []
    stdout_log = run_dir / "stdout.log"
    if manifest.artifact_profile == "trunk_forward_data":
        records = run_dir / "episode.csv"
        required_summary = None
        required_provenance = None
    elif manifest.artifact_profile in {
        "trajectory_tracking",
        "trunk_inverse_tracking",
    }:
        records = run_dir / "trajectory.csv"
        required_summary = run_dir / "performance.json"
        required_provenance = None
    elif manifest.artifact_profile == "koopman_mpc_tracking":
        records = run_dir / "trajectory.csv"
        required_summary = run_dir / "performance.json"
        required_provenance = run_dir / "model_provenance.json"
    else:
        return ArtifactVerification(
            row_count=0,
            errors=(f"unsupported artifact profile: {manifest.artifact_profile}",),
        )
    row_count = _trajectory_rows(records)

    if process_exit_code not in (None, 0) and not accept_completed_signal:
        errors.append(f"runSofa exit code was {process_exit_code}")
    if row_count != manifest.steps:
        errors.append(f"trajectory row count was {row_count}, expected {manifest.steps}")
    if required_summary is not None and (
        not required_summary.is_file() or required_summary.stat().st_size == 0
    ):
        errors.append("performance.json is missing or empty")
    if required_provenance is not None and (
        not required_provenance.is_file() or required_provenance.stat().st_size == 0
    ):
        errors.append("model_provenance.json is missing or empty")
    if manifest.artifact_profile == "koopman_mpc_tracking" and not errors:
        errors.extend(_verify_koopman_mpc_artifacts(run_dir, records))
    if not stdout_log.is_file() or stdout_log.stat().st_size == 0:
        errors.append("stdout.log is missing or empty")
    elif "[ERROR]" in stdout_log.read_text(encoding="utf-8", errors="replace"):
        errors.append("stdout.log contains an [ERROR] entry")
    return ArtifactVerification(row_count=row_count, errors=tuple(errors))


def _write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _runtime_environment(
    manifest: RunManifest,
    workspace: Path,
    sofa_root: Path,
    sofa_validation_library: Path,
    config: Path,
    run_dir: Path,
) -> dict[str, str]:
    environment = dict(os.environ)
    environment["PATH"] = f"{sofa_root / 'bin'}:{environment.get('PATH', '')}"
    environment["PYTHONPATH"] = (
        f"{workspace / 'src'}"
        + (f":{environment['PYTHONPATH']}" if environment.get("PYTHONPATH") else "")
    )
    library_paths = [str(sofa_root / "lib"), str(sofa_root / "bin"), str(sofa_validation_library.parent)]
    if environment.get("LD_LIBRARY_PATH"):
        library_paths.append(environment["LD_LIBRARY_PATH"])
    environment["LD_LIBRARY_PATH"] = ":".join(library_paths)
    if manifest.pipeline_id == "trunk_tracking":
        environment["TRUNK_INVERSE_CONFIG"] = str(config)
    elif manifest.pipeline_id == "trunk_forward_data":
        environment["TRUNK_FORWARD_CONFIG"] = str(config)
    elif manifest.pipeline_id == "trunk_koopman_mpc":
        environment["TRUNK_KOOPMAN_MPC_CONFIG"] = str(config)
    else:
        raise ValueError(f"unsupported experiment pipeline: {manifest.pipeline_id}")
    environment["TRUNK_RUN_DIR"] = str(run_dir)
    return environment


def _stream_gui_output(process: subprocess.Popen[str], stdout_log: Path) -> int:
    assert process.stdout is not None
    with stdout_log.open("w", encoding="utf-8") as handle:
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            print(line, end="", flush=True)
    return process.wait()


def _run_sofa(
    command: Sequence[str],
    *,
    environment: dict[str, str],
    stdout_log: Path,
    mode: str,
    timeout_s: int,
) -> int:
    try:
        if mode == "gui":
            process = subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                return _stream_gui_output(process, stdout_log)
            except KeyboardInterrupt:
                # The terminal can signal the parent after the GUI has emitted
                # all requested records.  Finalization decides whether artifacts
                # are complete before assigning the user-facing status.
                process.wait()
                return process.returncode if process.returncode is not None else 130
        with stdout_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                env=environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        return completed.returncode
    except subprocess.TimeoutExpired:
        with stdout_log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[ERROR] runtime timed out after {timeout_s} seconds\n")
        return 124


def _device_info() -> str:
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return completed.stdout.strip()


def _git_context(workspace: Path) -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain", "--untracked-files=normal"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    ).stdout
    if not commit:
        return "", "unavailable"
    return commit, "dirty" if status else "clean"


def execute_sofa_run(
    manifest: RunManifest,
    *,
    workspace: Path,
    sofa_root: Path,
    sofa_validation_library: Path,
) -> int:
    """Execute and finalize one registered SOFA experiment."""

    workspace = workspace.resolve()
    run_dir = workspace / "runs" / manifest.run_id
    if run_dir.exists():
        raise ValueError(f"run directory already exists: {run_dir}")
    scene = _safe_workspace_path(workspace, manifest.scene_rel, "src/simulation/scenes/")
    config = _safe_workspace_path(workspace, manifest.config_rel, "configs/")
    runsofa = sofa_root / "bin" / "runSofa"
    if not runsofa.is_file() or not os.access(runsofa, os.X_OK):
        raise ValueError(f"runSofa is unavailable: {runsofa}")
    if not sofa_validation_library.is_file() or not scene.is_file() or not config.is_file():
        raise ValueError("SOFA validation plugin, scene, or config is unavailable")

    run_dir.mkdir(parents=True)
    _write_json(run_dir / "requested_config.json", manifest.to_mapping())
    try:
        effective_config = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"registered config is invalid JSON: {config}") from error
    _write_json(run_dir / "effective_config.json", effective_config)

    command = build_sofa_command(
        manifest,
        runsofa=runsofa,
        sofa_validation_library=sofa_validation_library,
        scene=scene,
    )
    start_utc = _utc_now()
    process_exit_code = _run_sofa(
        command,
        environment=_runtime_environment(
            manifest, workspace, sofa_root, sofa_validation_library, config, run_dir
        ),
        stdout_log=run_dir / "stdout.log",
        mode=manifest.mode,
        timeout_s=manifest.timeout_s,
    )
    end_utc = _utc_now()
    verification = verify_tracking_artifacts(
        run_dir,
        manifest,
        process_exit_code=process_exit_code,
        accept_completed_signal=manifest.mode == "gui" and process_exit_code < 0,
    )
    success = verification.ok
    exit_code = 0 if success else process_exit_code
    if not success and exit_code == 0:
        exit_code = 7
    git_commit, git_worktree = _git_context(workspace)

    (run_dir / "process_exit_code").write_text(
        f"{process_exit_code}\n", encoding="utf-8"
    )
    (run_dir / "exit_code").write_text(f"{exit_code}\n", encoding="utf-8")
    _write_json(
        run_dir / "metadata.json",
        {
            "run_id": manifest.run_id,
            "manifest": manifest.to_mapping(),
            "scene": str(scene),
            "scene_relative": manifest.scene_rel,
            "config": manifest.config_rel,
            "steps": manifest.steps,
            "gui": manifest.mode,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "process_exit_code": process_exit_code,
            "exit_code": exit_code,
            "command": list(command),
            "git_commit": git_commit,
            "git_worktree": git_worktree,
            "device": _device_info(),
            "python": sys.version,
            "platform": platform.platform(),
            "artifact_verification": {
                "row_count": verification.row_count,
                "errors": list(verification.errors),
            },
        },
    )
    if success:
        (run_dir / "COMPLETE").touch()
        print(
            "experiment_status=complete\n"
            f"run_id={manifest.run_id}\n"
            f"steps={manifest.steps}\n"
            f"rows={verification.row_count}\n"
            f"run_dir={run_dir}"
        )
        return 0

    (run_dir / "FAILED").touch()
    print(
        "experiment_status=failed\n"
        f"run_id={manifest.run_id}\n"
        f"process_exit_code={process_exit_code}\n"
        f"rows={verification.row_count}\n"
        f"errors={' | '.join(verification.errors)}\n"
        f"run_dir={run_dir}",
        file=sys.stderr,
    )
    return 7


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one resolved SOFA experiment.")
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--sofa-root", required=True)
    parser.add_argument("--sofa-validation-library", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = RunManifest.from_json(args.manifest_json)
        return execute_sofa_run(
            manifest,
            workspace=Path(args.workspace),
            sofa_root=Path(args.sofa_root),
            sofa_validation_library=Path(args.sofa_validation_library),
        )
    except ValueError as error:
        print(f"experiment runtime error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
