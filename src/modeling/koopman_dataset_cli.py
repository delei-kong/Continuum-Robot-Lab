"""Controlled offline assembly and audit for registered Koopman datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from experiment.contracts import RUN_ID_PATTERN
from experiment.forward_data_cli import resolve_forward_data_batch

from .koopman_dataset import (
    ACTION_COLUMNS,
    STATE_COLUMNS,
    DatasetEpisode,
    DatasetQualityPolicy,
    audit_dataset,
    load_transitions,
)


CANONICAL_DATASET_FORMAT = "continuum_dynamics_dataset_v1"
CANONICAL_DATASET_SCHEMA_VERSION = 1
_SPLITS = ("train", "validation", "test")


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _load_accepted_audit_episodes(
    project_root: Path,
    definition: KoopmanDatasetDefinition,
    audit_output_name: str,
) -> tuple[
    Mapping[str, tuple[DatasetEpisode, ...]],
    Mapping[str, Any],
    Mapping[str, Any],
    Path,
    Path,
]:
    """Revalidate an audit result before copying it into the canonical dataset store."""

    _validate_run_id(audit_output_name, "dataset audit output")
    audit_dir = project_root / "outputs" / "koopman_datasets" / audit_output_name
    audit_path = audit_dir / "audit.json"
    manifest_path = audit_dir / "dataset_manifest.json"
    audit = _read_mapping(audit_path, "dataset audit")
    source_manifest = _read_mapping(manifest_path, "dataset audit manifest")
    if source_manifest.get("dataset_id") != definition.dataset_id or audit.get("ok") is not True:
        raise ValueError("dataset audit output is not an accepted registered dataset")
    if audit.get("state_columns") != list(STATE_COLUMNS) or audit.get("action_columns") != list(ACTION_COLUMNS):
        raise ValueError("dataset audit state/action contract does not match the canonical format")
    manifest_entries = source_manifest.get("episodes")
    audit_entries = audit.get("episodes")
    if not isinstance(manifest_entries, list) or not isinstance(audit_entries, list):
        raise ValueError("dataset audit output has no episode provenance")
    audit_by_id = {
        entry.get("episode_id"): entry
        for entry in audit_entries
        if isinstance(entry, dict) and isinstance(entry.get("episode_id"), str)
    }
    episodes_by_split: dict[str, list[DatasetEpisode]] = {split: [] for split in _SPLITS}
    for entry in manifest_entries:
        if not isinstance(entry, dict):
            raise ValueError("dataset manifest contains an invalid episode entry")
        episode_id = entry.get("episode_id")
        split = entry.get("split")
        if not isinstance(episode_id, str) or split not in episodes_by_split:
            raise ValueError("dataset manifest episode has invalid ID or split")
        _validate_run_id(episode_id, "dataset episode ID")
        source_dir = project_root / "outputs" / "trunk_forward_data" / episode_id
        declared_dir = entry.get("run_dir")
        if not isinstance(declared_dir, str) or Path(declared_dir).resolve() != source_dir.resolve():
            raise ValueError(f"dataset manifest run directory does not match {episode_id!r}")
        audit_entry = audit_by_id.get(episode_id)
        if not isinstance(audit_entry, dict) or audit_entry.get("split") != split:
            raise ValueError(f"dataset audit has no matching entry for {episode_id!r}")
        if audit_entry.get("errors") not in ([], ()):
            raise ValueError(f"dataset episode {episode_id!r} did not pass its audit")
        episodes_by_split[split].append(
            DatasetEpisode(episode_id, split, source_dir / "episode.csv", definition.dt_s)
        )
    episodes = tuple(episode for split in _SPLITS for episode in episodes_by_split[split])
    report = audit_dataset(episodes, definition.policy)
    if not report.ok:
        raise ValueError("dataset artifacts no longer satisfy the approved audit contract")
    current_hashes = {entry.episode_id: entry.sha256 for entry in report.episodes}
    for episode_id, audit_entry in audit_by_id.items():
        if episode_id in current_hashes and audit_entry.get("sha256") != current_hashes[episode_id]:
            raise ValueError(f"dataset episode {episode_id!r} changed after audit")
    return (
        {split: tuple(episodes_by_split[split]) for split in _SPLITS},
        audit,
        source_manifest,
        audit_path,
        manifest_path,
    )


def _write_split_transitions(path: Path, episodes: tuple[DatasetEpisode, ...]) -> int:
    states: list[np.ndarray] = []
    actions: list[np.ndarray] = []
    next_states: list[np.ndarray] = []
    episode_indices: list[np.ndarray] = []
    episode_ids: list[str] = []
    for episode_index, episode in enumerate(episodes):
        transitions = load_transitions(episode)
        states.append(np.asarray([transition.state for transition in transitions], dtype=np.float64))
        actions.append(np.asarray([transition.action for transition in transitions], dtype=np.float64))
        next_states.append(
            np.asarray([transition.next_state for transition in transitions], dtype=np.float64)
        )
        episode_indices.append(np.full(len(transitions), episode_index, dtype=np.int32))
        episode_ids.append(episode.episode_id)
    state = np.concatenate(states, axis=0)
    action = np.concatenate(actions, axis=0)
    next_state = np.concatenate(next_states, axis=0)
    index = np.concatenate(episode_indices, axis=0)
    np.savez_compressed(
        path,
        state=state,
        action=action,
        next_state=next_state,
        episode_index=index,
        episode_ids=np.asarray(episode_ids, dtype=str),
    )
    return len(state)


def materialize_canonical_dataset(
    project_root: Path,
    definition: KoopmanDatasetDefinition,
    *,
    audit_output_name: str,
    release_name: str,
) -> int:
    """Copy one audited dataset into the versioned, Git-ignored canonical store."""

    _validate_run_id(release_name, "dataset release")
    (
        episodes_by_split,
        audit,
        source_manifest,
        audit_path,
        source_manifest_path,
    ) = _load_accepted_audit_episodes(project_root, definition, audit_output_name)
    dataset_root = project_root / "datasets" / definition.dataset_id
    release_dir = dataset_root / release_name
    if release_dir.exists():
        raise ValueError(f"canonical dataset release already exists: {release_dir}")
    dataset_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{release_name}.", dir=dataset_root))
    try:
        (staging_dir / "episodes").mkdir()
        (staging_dir / "transitions").mkdir()
        (staging_dir / "provenance" / "effective_configs").mkdir(parents=True)
        (staging_dir / "provenance" / "run_metadata").mkdir(parents=True)
        shutil.copy2(audit_path, staging_dir / "provenance" / "audit.json")
        shutil.copy2(source_manifest_path, staging_dir / "provenance" / "source_manifest.json")
        split_manifest: dict[str, dict[str, object]] = {}
        for split in _SPLITS:
            split_episodes = episodes_by_split[split]
            split_dir = staging_dir / "episodes" / split
            split_dir.mkdir()
            episode_entries: list[dict[str, object]] = []
            for episode in split_episodes:
                source_dir = episode.csv_path.parent
                relative_csv = Path("episodes") / split / f"{episode.episode_id}.csv"
                shutil.copy2(episode.csv_path, staging_dir / relative_csv)
                shutil.copy2(
                    source_dir / "effective_config.json",
                    staging_dir / "provenance" / "effective_configs" / f"{episode.episode_id}.json",
                )
                shutil.copy2(
                    source_dir / "metadata.json",
                    staging_dir / "provenance" / "run_metadata" / f"{episode.episode_id}.json",
                )
                episode_entries.append(
                    {
                        "episode_id": episode.episode_id,
                        "path": relative_csv.as_posix(),
                        "sha256": _sha256(staging_dir / relative_csv),
                    }
                )
            transition_relative = Path("transitions") / f"{split}.npz"
            transition_count = _write_split_transitions(
                staging_dir / transition_relative, split_episodes
            )
            split_manifest[split] = {
                "episode_count": len(split_episodes),
                "episodes": episode_entries,
                "transitions": transition_count,
                "transitions_path": transition_relative.as_posix(),
                "transitions_sha256": _sha256(staging_dir / transition_relative),
            }
        schema = {
            "schema_version": CANONICAL_DATASET_SCHEMA_VERSION,
            "format": CANONICAL_DATASET_FORMAT,
            "dataset_id": definition.dataset_id,
            "dt_s": definition.dt_s,
            "state_columns": list(STATE_COLUMNS),
            "action_columns": list(ACTION_COLUMNS),
            "state_dimension": len(STATE_COLUMNS),
            "action_dimension": len(ACTION_COLUMNS),
            "transition_contract": "(state[t-1], action[t], state[t]) within one episode only",
            "transition_arrays": {
                "state": "float64 [transitions, state_dimension]",
                "action": "float64 [transitions, action_dimension]",
                "next_state": "float64 [transitions, state_dimension]",
                "episode_index": "int32 [transitions]",
                "episode_ids": "unicode [episode_count]",
            },
        }
        _write_json(staging_dir / "schema.json", schema)
        manifest = {
            "schema_version": CANONICAL_DATASET_SCHEMA_VERSION,
            "format": CANONICAL_DATASET_FORMAT,
            "status": "complete",
            "dataset_id": definition.dataset_id,
            "release_id": release_name,
            "created_at_utc": _utc_timestamp(),
            "schema_path": "schema.json",
            "source_audit": {
                "output_id": audit_output_name,
                "audit_sha256": _sha256(audit_path),
                "source_manifest_sha256": _sha256(source_manifest_path),
                "audit_ok": audit.get("ok"),
                "source_batches": source_manifest.get("source_batches"),
            },
            "splits": split_manifest,
        }
        _write_json(staging_dir / "dataset_manifest.json", manifest)
        (staging_dir / "COMPLETE").touch()
        staging_dir.replace(release_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    print(f"canonical_dataset_dir={release_dir}")
    print(f"canonical_dataset_format={CANONICAL_DATASET_FORMAT}")
    print(f"canonical_dataset_status=complete")
    return 0


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
    parser.add_argument(
        "--materialize-from",
        default=None,
        help="accepted dataset audit output ID to copy into the canonical dataset store",
    )
    parser.add_argument(
        "--release",
        default=None,
        help="new canonical dataset release ID, stored below datasets/<dataset>/",
    )
    parser.add_argument("--list", action="store_true", help="list registered datasets")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        if args.list:
            if any(
                (
                    args.train_batch,
                    args.validation_batch,
                    args.test_batch,
                    args.output,
                    args.materialize_from,
                    args.release,
                )
            ):
                raise ValueError("--list cannot be combined with dataset assembly options")
            print(format_available_datasets(project_root))
            return 0
        definition = resolve_dataset_definition(args.dataset, project_root)
        if args.materialize_from or args.release:
            if not args.materialize_from or not args.release:
                raise ValueError("--materialize-from and --release are required together")
            if any((args.train_batch, args.validation_batch, args.test_batch, args.output)):
                raise ValueError("dataset materialization cannot be combined with audit assembly options")
            return materialize_canonical_dataset(
                project_root,
                definition,
                audit_output_name=args.materialize_from,
                release_name=args.release,
            )
        if not all((args.train_batch, args.validation_batch, args.test_batch, args.output)):
            raise ValueError(
                "--train-batch, --validation-batch, --test-batch and --output are all required"
            )
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
