"""Controlled offline assembly and audit for registered Koopman datasets."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from experiment.contracts import RUN_ID_PATTERN
from experiment.forward_data_cli import resolve_forward_data_batch

from .koopman_dataset import DatasetEpisode, DatasetQualityPolicy, audit_dataset


@dataclass(frozen=True)
class KoopmanDatasetDefinition:
    dataset_id: str
    config_rel: str
    dt_s: float
    required_batches: Mapping[str, str]
    policy: DatasetQualityPolicy


_DATASETS = {
    "koopman_v1": KoopmanDatasetDefinition(
        dataset_id="koopman_v1",
        config_rel="configs/koopman_dataset_v1.json",
        dt_s=0.01,
        required_batches={
            "train": "koopman_v1_train",
            "validation": "koopman_v1_validation",
            "test": "koopman_v1_test",
        },
        policy=DatasetQualityPolicy(
            min_rows_per_episode=2000,
            min_action_span_mm=1.0,
            max_limited_command_fraction=0.05,
        ),
    )
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def resolve_dataset_definition(
    dataset_id: str, project_root: Path
) -> KoopmanDatasetDefinition:
    try:
        definition = _DATASETS[dataset_id]
    except KeyError as error:
        choices = ", ".join(sorted(_DATASETS))
        raise ValueError(f"unsupported Koopman dataset {dataset_id!r}; choose from {choices}") from error
    payload = _read_mapping(project_root / definition.config_rel, "dataset configuration")
    if payload.get("dataset_id") != definition.dataset_id:
        raise ValueError("dataset configuration ID does not match its registered definition")
    dt_s = payload.get("dt_s")
    if isinstance(dt_s, bool) or not isinstance(dt_s, (int, float)) or not math.isfinite(dt_s):
        raise ValueError("dataset configuration dt_s must be a finite number")
    if abs(float(dt_s) - definition.dt_s) > 1e-12:
        raise ValueError("dataset configuration dt_s does not match its registered definition")
    if payload.get("required_batches") != dict(definition.required_batches):
        raise ValueError("dataset configuration batch contract does not match registry")
    policy_payload = payload.get("quality_policy")
    if not isinstance(policy_payload, dict):
        raise ValueError("dataset configuration quality_policy must be an object")
    try:
        policy = DatasetQualityPolicy(
            min_rows_per_episode=policy_payload["min_rows_per_episode"],
            min_action_span_mm=policy_payload["min_action_span_mm"],
            max_limited_command_fraction=policy_payload["max_limited_command_fraction"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("dataset configuration quality_policy is invalid") from error
    if policy != definition.policy:
        raise ValueError("dataset configuration quality_policy does not match registry")
    return definition


def _validate_run_id(value: str, label: str) -> str:
    if not value or not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must contain only letters, digits, '.', '_' or '-'")
    return value


def _read_split_episodes(
    project_root: Path,
    *,
    split: str,
    batch_output_name: str,
    definition: KoopmanDatasetDefinition,
) -> tuple[tuple[DatasetEpisode, ...], list[dict[str, Any]]]:
    _validate_run_id(batch_output_name, f"{split} batch output")
    batch_dir = project_root / "outputs" / "forward_data_batches" / batch_output_name
    batch_manifest = _read_mapping(batch_dir / "batch_manifest.json", f"{split} batch manifest")
    summary = _read_mapping(batch_dir / "summary.json", f"{split} batch summary")
    expected_batch = definition.required_batches[split]
    if batch_manifest.get("batch_id") != expected_batch:
        raise ValueError(
            f"{split} batch {batch_output_name!r} is not a {expected_batch!r} collection"
        )
    if summary.get("status") != "complete" or summary.get("failed") != 0:
        raise ValueError(f"{split} batch {batch_output_name!r} is not fully successful")
    cases = batch_manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"{split} batch manifest cases must be a list")
    expected_specs = resolve_forward_data_batch(expected_batch, project_root)
    expected_inputs = [spec.input_name for spec in expected_specs]
    actual_inputs = [case.get("input") for case in cases if isinstance(case, dict)]
    if actual_inputs != expected_inputs:
        raise ValueError(f"{split} batch inputs do not match the registered collection")

    episodes: list[DatasetEpisode] = []
    provenance: list[dict[str, Any]] = []
    for case, spec in zip(cases, expected_specs):
        if not isinstance(case, dict):
            raise ValueError(f"{split} batch contains an invalid case")
        run_id = case.get("run_id")
        if not isinstance(run_id, str):
            raise ValueError(f"{split} batch case has no run ID")
        _validate_run_id(run_id, f"{split} run ID")
        run_dir = project_root / "outputs" / "trunk_forward_data" / run_id
        required = ("COMPLETE", "exit_code", "effective_config.json", "metadata.json", "episode.csv")
        missing = [name for name in required if not (run_dir / name).is_file()]
        if missing:
            raise ValueError(
                f"{split} run {run_id!r} is not fetched or missing: {', '.join(missing)}"
            )
        if (run_dir / "FAILED").exists() or (run_dir / "exit_code").read_text(
            encoding="utf-8"
        ).strip() != "0":
            raise ValueError(f"{split} run {run_id!r} is not a successful standard artifact")
        config = _read_mapping(run_dir / "effective_config.json", f"{split} run config")
        if config.get("dataset_id") != definition.dataset_id or config.get("dataset_split") != split:
            raise ValueError(f"{split} run {run_id!r} does not declare the expected dataset split")
        if config.get("episode_id") != spec.input_name.removeprefix("koopman_v1_"):
            raise ValueError(f"{split} run {run_id!r} does not match its registered episode")
        episodes.append(DatasetEpisode(run_id, split, run_dir / "episode.csv", definition.dt_s))
        provenance.append(
            {
                "episode_id": run_id,
                "split": split,
                "input": spec.input_name,
                "config": spec.config_rel,
                "run_dir": str(run_dir),
            }
        )
    return tuple(episodes), provenance


def assemble_and_audit_dataset(
    project_root: Path,
    definition: KoopmanDatasetDefinition,
    *,
    output_name: str,
    batch_outputs: Mapping[str, str],
) -> int:
    """Assemble a registered dataset only from fetched, verified episode runs."""

    _validate_run_id(output_name, "dataset output")
    output_dir = project_root / "outputs" / "koopman_datasets" / output_name
    try:
        output_dir.mkdir(parents=True)
    except FileExistsError as error:
        raise ValueError(f"dataset output directory already exists: {output_dir}") from error

    episodes: list[DatasetEpisode] = []
    provenance: list[dict[str, Any]] = []
    for split in ("train", "validation", "test"):
        split_episodes, split_provenance = _read_split_episodes(
            project_root,
            split=split,
            batch_output_name=batch_outputs[split],
            definition=definition,
        )
        episodes.extend(split_episodes)
        provenance.extend(split_provenance)

    report = audit_dataset(episodes, definition.policy)
    manifest = {
        "schema_version": 1,
        "dataset_id": definition.dataset_id,
        "config": definition.config_rel,
        "created_at_utc": _utc_timestamp(),
        "source_batches": dict(batch_outputs),
        "episodes": provenance,
    }
    _write_json(output_dir / "dataset_manifest.json", manifest)
    _write_json(output_dir / "audit.json", report.to_mapping())
    print(f"dataset_output_dir={output_dir}")
    print(f"dataset_audit={'passed' if report.ok else 'failed'}")
    print(f"transitions={sum(report.split_transitions.values())}")
    return 0 if report.ok else 1


def format_available_datasets(project_root: Path) -> str:
    lines = ["available controlled Koopman datasets:"]
    for dataset_id in _DATASETS:
        definition = resolve_dataset_definition(dataset_id, project_root)
        batches = ", ".join(
            f"{split}={batch}" for split, batch in definition.required_batches.items()
        )
        lines.append(f"  {dataset_id} ({batches})")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble and audit one registered Koopman dataset."
    )
    parser.add_argument("--dataset", default="koopman_v1", help="registered dataset")
    parser.add_argument("--train-batch", default=None, help="completed registered train batch output")
    parser.add_argument(
        "--validation-batch", default=None, help="completed registered validation batch output"
    )
    parser.add_argument("--test-batch", default=None, help="completed registered test batch output")
    parser.add_argument("--output", default=None, help="dataset audit output ID")
    parser.add_argument("--list", action="store_true", help="list registered datasets")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        if args.list:
            if any((args.train_batch, args.validation_batch, args.test_batch, args.output)):
                raise ValueError("--list cannot be combined with dataset assembly options")
            print(format_available_datasets(project_root))
            return 0
        if not all((args.train_batch, args.validation_batch, args.test_batch, args.output)):
            raise ValueError(
                "--train-batch, --validation-batch, --test-batch and --output are all required"
            )
        definition = resolve_dataset_definition(args.dataset, project_root)
        return assemble_and_audit_dataset(
            project_root,
            definition,
            output_name=args.output,
            batch_outputs={
                "train": args.train_batch,
                "validation": args.validation_batch,
                "test": args.test_batch,
            },
        )
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
