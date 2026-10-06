"""Controlled linear and fixed-lift Koopman dynamics training.

The model input is an already audited dataset, never an arbitrary CSV.  Both
models learn the same discrete transition contract::

    state[t - 1] + action[t] -> state[t]

The linear baseline uses the normalized state as its lifting.  The Koopman
candidate uses a deterministic random-Fourier feature lifting and EDMD with
control (EDMDc).  Normalization, model selection and all fit statistics are
derived from the train split only.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from experiment.contracts import RUN_ID_PATTERN

from .koopman_dataset import (
    ACTION_COLUMNS,
    STATE_COLUMNS,
    DatasetEpisode,
    DynamicsTransition,
    audit_dataset,
    load_transitions,
)
from .koopman_dataset_cli import resolve_dataset_definition


MODEL_OUTPUT_ROOT = Path("outputs") / "koopman_models"
_MODEL_CONFIGS = {
    "koopman_v1_fixed_lift": "configs/koopman_model_v1.json",
    "koopman_v2_rff_candidates": "configs/koopman_model_v2.json",
}
_SPLITS = ("train", "validation", "test")
_TIP_INDICES = tuple(STATE_COLUMNS.index(column) for column in ("tip_x_mm", "tip_y_mm", "tip_z_mm"))
_CENTERLINE_POSITION_INDICES = tuple(
    index
    for index, column in enumerate(STATE_COLUMNS)
    if column.startswith("centerline_")
    and column.endswith(("_x_mm", "_y_mm", "_z_mm"))
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _positive_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{label} must be a finite positive number")
    return parsed


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validate_output_id(value: str, label: str) -> str:
    if not value or not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must contain only letters, digits, '.', '_' or '-'")
    return value


@dataclass(frozen=True)
class EvaluationConfig:
    rollout_horizons: tuple[int, ...]
    rollout_start_stride: int
    max_starts_per_episode: int

    def __post_init__(self) -> None:
        if not self.rollout_horizons or any(horizon < 1 for horizon in self.rollout_horizons):
            raise ValueError("rollout_horizons must contain positive integers")
        if tuple(sorted(set(self.rollout_horizons))) != self.rollout_horizons:
            raise ValueError("rollout_horizons must be sorted and unique")
        if self.rollout_start_stride < 1 or self.max_starts_per_episode < 1:
            raise ValueError("rollout start controls must be positive")


@dataclass(frozen=True)
class RffCandidate:
    name: str
    ridge: float
    feature_count: int
    bandwidth: float
    seed: int


@dataclass(frozen=True)
class KoopmanModelDefinition:
    model_id: str
    dataset_id: str
    config_rel: str
    minimum_scale: float
    baseline_ridge: float
    rff_candidates: tuple[RffCandidate, ...]
    evaluation: EvaluationConfig


@dataclass(frozen=True)
class AuditedDataset:
    dataset_id: str
    audit_output_id: str
    episodes_by_split: Mapping[str, tuple[DatasetEpisode, ...]]
    audit_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class Normalization:
    state_mean: np.ndarray
    state_scale: np.ndarray
    action_mean: np.ndarray
    action_scale: np.ndarray

    def normalize_state(self, state: np.ndarray) -> np.ndarray:
        return (state - self.state_mean) / self.state_scale

    def denormalize_state(self, state: np.ndarray) -> np.ndarray:
        return state * self.state_scale + self.state_mean

    def normalize_action(self, action: np.ndarray) -> np.ndarray:
        return (action - self.action_mean) / self.action_scale

    def to_mapping(self) -> dict[str, object]:
        return {
            "state_columns": list(STATE_COLUMNS),
            "action_columns": list(ACTION_COLUMNS),
            "state_mean": self.state_mean.tolist(),
            "state_scale": self.state_scale.tolist(),
            "action_mean": self.action_mean.tolist(),
            "action_scale": self.action_scale.tolist(),
        }


@dataclass(frozen=True)
class FixedLift:
    kind: str
    state_dimension: int
    frequencies: np.ndarray
    phases: np.ndarray

    @property
    def feature_dimension(self) -> int:
        return self.state_dimension + self.frequencies.shape[1]

    def lift(self, normalized_state: np.ndarray) -> np.ndarray:
        values = np.asarray(normalized_state, dtype=np.float64)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        if values.ndim != 2 or values.shape[1] != self.state_dimension:
            raise ValueError("normalized state shape does not match lift")
        if self.kind == "linear_affine":
            return values
        if self.kind != "edmd_rff":
            raise ValueError(f"unsupported lift kind: {self.kind}")
        angles = values @ self.frequencies + self.phases
        rff_scale = math.sqrt(2.0 / self.frequencies.shape[1])
        return np.concatenate((values, rff_scale * np.cos(angles)), axis=1)


@dataclass(frozen=True)
class TrainedDynamicsModel:
    name: str
    lift: FixedLift
    normalization: Normalization
    lift_transition: np.ndarray
    action_transition: np.ndarray
    bias: np.ndarray
    ridge: float

    def predict_step(self, state: np.ndarray, action: np.ndarray) -> np.ndarray:
        normalized_state = self.normalization.normalize_state(np.asarray(state, dtype=np.float64))
        normalized_action = self.normalization.normalize_action(np.asarray(action, dtype=np.float64))
        lift = self.lift.lift(normalized_state)
        next_lift = self.advance_lift(lift, normalized_action)
        return self.normalization.denormalize_state(next_lift[:, : len(STATE_COLUMNS)])

    def advance_lift(self, lift: np.ndarray, normalized_action: np.ndarray) -> np.ndarray:
        values = np.asarray(lift, dtype=np.float64)
        actions = np.asarray(normalized_action, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != self.lift.feature_dimension:
            raise ValueError("lift state shape does not match trained model")
        if actions.ndim == 1:
            actions = actions.reshape(1, -1)
        if actions.ndim != 2 or actions.shape != (values.shape[0], len(ACTION_COLUMNS)):
            raise ValueError("action shape does not match trained model")
        result = values @ self.lift_transition + actions @ self.action_transition + self.bias
        if not np.all(np.isfinite(result)):
            raise ValueError(f"{self.name} produced a non-finite lifted state")
        return result

    def to_npz(self, prefix: str) -> dict[str, np.ndarray]:
        return {
            f"{prefix}_lift_transition": self.lift_transition,
            f"{prefix}_action_transition": self.action_transition,
            f"{prefix}_bias": self.bias,
            f"{prefix}_frequencies": self.lift.frequencies,
            f"{prefix}_phases": self.lift.phases,
        }


def available_model_ids() -> tuple[str, ...]:
    return tuple(_MODEL_CONFIGS)


def _parse_rff_candidate(payload: Mapping[str, Any], label: str) -> RffCandidate:
    name = payload.get("name")
    if not isinstance(name, str) or not name or name == "linear_affine":
        raise ValueError(f"{label}.name must be a non-empty reserved-safe model name")
    seed = payload.get("random_seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"{label}.random_seed must be a non-negative integer")
    return RffCandidate(
        name=name,
        ridge=_positive_float(payload.get("ridge"), f"{label}.ridge"),
        feature_count=_positive_int(payload.get("feature_count"), f"{label}.feature_count"),
        bandwidth=_positive_float(payload.get("bandwidth"), f"{label}.bandwidth"),
        seed=seed,
    )


def resolve_model_definition(
    model_id: str, dataset_id: str, project_root: Path
) -> KoopmanModelDefinition:
    dataset = resolve_dataset_definition(dataset_id, project_root)
    try:
        config_rel = _MODEL_CONFIGS[model_id]
    except KeyError as error:
        choices = ", ".join(available_model_ids())
        raise ValueError(f"unsupported Koopman model {model_id!r}; choose from {choices}") from error
    path = project_root / config_rel
    payload = _read_mapping(path, "Koopman model configuration")
    if payload.get("model_id") != model_id or payload.get("dataset_id") != dataset.dataset_id:
        raise ValueError("Koopman model configuration does not match the registered model")
    normalization = payload.get("normalization")
    linear = payload.get("linear_affine")
    evaluation = payload.get("evaluation")
    if not all(isinstance(section, dict) for section in (normalization, linear, evaluation)):
        raise ValueError("Koopman model configuration sections must be objects")
    horizons = evaluation.get("rollout_horizons")
    if not isinstance(horizons, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in horizons
    ):
        raise ValueError("evaluation.rollout_horizons must be an integer list")
    if model_id == "koopman_v1_fixed_lift":
        rff = payload.get("edmd_rff")
        if not isinstance(rff, dict):
            raise ValueError("edmd_rff must be an object")
        candidates = (_parse_rff_candidate({"name": "edmd_rff", **rff}, "edmd_rff"),)
    else:
        rff_candidates = payload.get("edmd_rff_candidates")
        if not isinstance(rff_candidates, list) or not rff_candidates:
            raise ValueError("edmd_rff_candidates must be a non-empty list")
        if not all(isinstance(candidate, dict) for candidate in rff_candidates):
            raise ValueError("edmd_rff_candidates must contain only objects")
        candidates = tuple(
            _parse_rff_candidate(candidate, f"edmd_rff_candidates[{index}]")
            for index, candidate in enumerate(rff_candidates)
        )
        if len({candidate.name for candidate in candidates}) != len(candidates):
            raise ValueError("edmd_rff candidate names must be unique")
    return KoopmanModelDefinition(
        model_id=model_id,
        dataset_id=dataset.dataset_id,
        config_rel=config_rel,
        minimum_scale=_positive_float(normalization.get("minimum_scale"), "normalization.minimum_scale"),
        baseline_ridge=_positive_float(linear.get("ridge"), "linear_affine.ridge"),
        rff_candidates=candidates,
        evaluation=EvaluationConfig(
            rollout_horizons=tuple(horizons),
            rollout_start_stride=_positive_int(
                evaluation.get("rollout_start_stride"), "evaluation.rollout_start_stride"
            ),
            max_starts_per_episode=_positive_int(
                evaluation.get("max_starts_per_episode"), "evaluation.max_starts_per_episode"
            ),
        ),
    )


def load_audited_dataset(
    project_root: Path, dataset_id: str, audit_output_id: str
) -> AuditedDataset:
    """Resolve and revalidate one controlled dataset-audit output directory."""

    _validate_output_id(audit_output_id, "dataset audit output")
    definition = resolve_dataset_definition(dataset_id, project_root)
    dataset_dir = project_root / "outputs" / "koopman_datasets" / audit_output_id
    manifest_path = dataset_dir / "dataset_manifest.json"
    audit_path = dataset_dir / "audit.json"
    manifest = _read_mapping(manifest_path, "dataset manifest")
    audit = _read_mapping(audit_path, "dataset audit")
    if manifest.get("dataset_id") != definition.dataset_id or audit.get("ok") is not True:
        raise ValueError("dataset audit output is not an accepted registered dataset")
    if audit.get("state_columns") != list(STATE_COLUMNS) or audit.get("action_columns") != list(ACTION_COLUMNS):
        raise ValueError("dataset audit state/action contract does not match Koopman model")
    entries = manifest.get("episodes")
    audit_entries = audit.get("episodes")
    if not isinstance(entries, list) or not isinstance(audit_entries, list):
        raise ValueError("dataset audit output has no episode provenance")
    audit_by_id = {
        item.get("episode_id"): item
        for item in audit_entries
        if isinstance(item, dict) and isinstance(item.get("episode_id"), str)
    }
    episodes_by_split: dict[str, list[DatasetEpisode]] = {split: [] for split in _SPLITS}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("dataset manifest contains an invalid episode entry")
        episode_id = entry.get("episode_id")
        split = entry.get("split")
        if not isinstance(episode_id, str) or split not in episodes_by_split:
            raise ValueError("dataset manifest episode has invalid ID or split")
        _validate_output_id(episode_id, "dataset episode ID")
        run_dir = project_root / "outputs" / "trunk_forward_data" / episode_id
        expected_run_dir = entry.get("run_dir")
        if not isinstance(expected_run_dir, str) or Path(expected_run_dir).resolve() != run_dir.resolve():
            raise ValueError(f"dataset manifest run directory does not match {episode_id!r}")
        audit_entry = audit_by_id.get(episode_id)
        if not isinstance(audit_entry, dict) or audit_entry.get("split") != split:
            raise ValueError(f"dataset audit has no matching entry for {episode_id!r}")
        if audit_entry.get("errors") not in ([], ()):
            raise ValueError(f"dataset episode {episode_id!r} did not pass its audit")
        episodes_by_split[split].append(
            DatasetEpisode(episode_id, split, run_dir / "episode.csv", definition.dt_s)
        )
    episodes = tuple(episode for split in _SPLITS for episode in episodes_by_split[split])
    report = audit_dataset(episodes, definition.policy)
    if not report.ok:
        raise ValueError("dataset artifacts no longer satisfy the approved audit contract")
    audited_hashes = {entry.episode_id: entry.sha256 for entry in report.episodes}
    for episode_id, expected in audit_by_id.items():
        if episode_id in audited_hashes and expected.get("sha256") != audited_hashes[episode_id]:
            raise ValueError(f"dataset episode {episode_id!r} changed after audit")
    return AuditedDataset(
        dataset_id=dataset_id,
        audit_output_id=audit_output_id,
        episodes_by_split={split: tuple(episodes_by_split[split]) for split in _SPLITS},
        audit_sha256=_sha256(audit_path),
        manifest_sha256=_sha256(manifest_path),
    )


def _transition_arrays(
    transitions: Sequence[DynamicsTransition],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not transitions:
        raise ValueError("an episode has no model transitions")
    state = np.asarray([transition.state for transition in transitions], dtype=np.float64)
    action = np.asarray([transition.action for transition in transitions], dtype=np.float64)
    next_state = np.asarray([transition.next_state for transition in transitions], dtype=np.float64)
    expected = (len(transitions), len(STATE_COLUMNS))
    if state.shape != expected or next_state.shape != expected:
        raise ValueError("transition state shape violates the Koopman dataset contract")
    if action.shape != (len(transitions), len(ACTION_COLUMNS)):
        raise ValueError("transition action shape violates the Koopman dataset contract")
    if not all(np.all(np.isfinite(values)) for values in (state, action, next_state)):
        raise ValueError("training transitions contain non-finite values")
    return state, action, next_state


def _load_split_transitions(
    episodes: Sequence[DatasetEpisode],
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray], ...]:
    return tuple(_transition_arrays(load_transitions(episode)) for episode in episodes)


def fit_normalization(
    train_episodes: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]], minimum_scale: float
) -> Normalization:
    if not train_episodes:
        raise ValueError("training split is empty")
    state_samples = np.concatenate(
        [np.concatenate((state, next_state), axis=0) for state, _, next_state in train_episodes], axis=0
    )
    action_samples = np.concatenate([action for _, action, _ in train_episodes], axis=0)
    state_scale = np.maximum(np.std(state_samples, axis=0), minimum_scale)
    action_scale = np.maximum(np.std(action_samples, axis=0), minimum_scale)
    return Normalization(
        state_mean=np.mean(state_samples, axis=0),
        state_scale=state_scale,
        action_mean=np.mean(action_samples, axis=0),
        action_scale=action_scale,
    )


def _fit_model(
    name: str,
    lift: FixedLift,
    normalization: Normalization,
    train_episodes: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    ridge: float,
) -> TrainedDynamicsModel:
    state = np.concatenate([episode[0] for episode in train_episodes], axis=0)
    action = np.concatenate([episode[1] for episode in train_episodes], axis=0)
    next_state = np.concatenate([episode[2] for episode in train_episodes], axis=0)
    lifted_state = lift.lift(normalization.normalize_state(state))
    lifted_next_state = lift.lift(normalization.normalize_state(next_state))
    normalized_action = normalization.normalize_action(action)
    design = np.concatenate(
        (lifted_state, normalized_action, np.ones((len(state), 1), dtype=np.float64)), axis=1
    )
    penalty = np.eye(design.shape[1], dtype=np.float64) * ridge
    penalty[-1, -1] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ lifted_next_state)
    feature_count = lift.feature_dimension
    return TrainedDynamicsModel(
        name=name,
        lift=lift,
        normalization=normalization,
        lift_transition=coefficients[:feature_count],
        action_transition=coefficients[feature_count:-1],
        bias=coefficients[-1],
        ridge=ridge,
    )


def fit_models(
    definition: KoopmanModelDefinition,
    train_episodes: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[Normalization, Mapping[str, TrainedDynamicsModel]]:
    normalization = fit_normalization(train_episodes, definition.minimum_scale)
    state_dimension = len(STATE_COLUMNS)
    linear_lift = FixedLift(
        kind="linear_affine",
        state_dimension=state_dimension,
        frequencies=np.empty((state_dimension, 0), dtype=np.float64),
        phases=np.empty((0,), dtype=np.float64),
    )
    models: dict[str, TrainedDynamicsModel] = {
        "linear_affine": _fit_model(
            "linear_affine", linear_lift, normalization, train_episodes, definition.baseline_ridge
        )
    }
    for candidate in definition.rff_candidates:
        generator = np.random.default_rng(candidate.seed)
        rff_lift = FixedLift(
            kind="edmd_rff",
            state_dimension=state_dimension,
            frequencies=generator.normal(
                loc=0.0,
                scale=1.0 / candidate.bandwidth,
                size=(state_dimension, candidate.feature_count),
            ),
            phases=generator.uniform(0.0, 2.0 * math.pi, size=(candidate.feature_count,)),
        )
        models[candidate.name] = _fit_model(
            candidate.name, rff_lift, normalization, train_episodes, candidate.ridge
        )
    return normalization, models


@dataclass
class _ErrorAccumulator:
    normalized_square_sum: float = 0.0
    normalized_count: int = 0
    tip_square_sum: float = 0.0
    tip_count: int = 0
    centerline_square_sum: float = 0.0
    centerline_count: int = 0
    sample_count: int = 0

    def add(self, prediction: np.ndarray, expected: np.ndarray, normalization: Normalization) -> None:
        if prediction.shape != expected.shape or prediction.ndim != 2:
            raise ValueError("prediction and reference shapes do not match")
        if not np.all(np.isfinite(prediction)):
            raise ValueError("model evaluation produced a non-finite state prediction")
        normalized_error = (prediction - expected) / normalization.state_scale
        self.normalized_square_sum += float(np.sum(np.square(normalized_error)))
        self.normalized_count += int(normalized_error.size)
        tip_error = prediction[:, _TIP_INDICES] - expected[:, _TIP_INDICES]
        self.tip_square_sum += float(np.sum(np.square(tip_error)))
        self.tip_count += int(tip_error.size)
        centerline_error = prediction[:, _CENTERLINE_POSITION_INDICES] - expected[:, _CENTERLINE_POSITION_INDICES]
        self.centerline_square_sum += float(np.sum(np.square(centerline_error)))
        self.centerline_count += int(centerline_error.size)
        self.sample_count += int(len(prediction))

    def to_mapping(self) -> dict[str, float | int]:
        if not self.normalized_count or not self.tip_count or not self.centerline_count:
            raise ValueError("evaluation received no samples")
        return {
            "samples": self.sample_count,
            "state_normalized_rmse": math.sqrt(self.normalized_square_sum / self.normalized_count),
            "tip_rmse_mm": math.sqrt(self.tip_square_sum / self.tip_count),
            "centerline_position_rmse_mm": math.sqrt(
                self.centerline_square_sum / self.centerline_count
            ),
        }


def evaluate_model(
    model: TrainedDynamicsModel,
    episodes: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    evaluation: EvaluationConfig,
) -> dict[str, object]:
    """Evaluate one-step and open-loop action-conditioned rollouts per episode."""

    one_step = _ErrorAccumulator()
    for state, action, next_state in episodes:
        one_step.add(model.predict_step(state, action), next_state, model.normalization)
    rollouts: dict[str, dict[str, float | int]] = {}
    for horizon in evaluation.rollout_horizons:
        if horizon == 1:
            rollouts[str(horizon)] = one_step.to_mapping()
            continue
        total = _ErrorAccumulator()
        for state, action, next_state in episodes:
            last_start = len(state) - horizon
            if last_start < 0:
                continue
            starts = np.arange(0, last_start + 1, evaluation.rollout_start_stride, dtype=int)
            starts = starts[: evaluation.max_starts_per_episode]
            if not len(starts):
                continue
            lifted = model.lift.lift(model.normalization.normalize_state(state[starts]))
            for offset in range(horizon):
                normalized_action = model.normalization.normalize_action(action[starts + offset])
                lifted = model.advance_lift(lifted, normalized_action)
            prediction = model.normalization.denormalize_state(lifted[:, : len(STATE_COLUMNS)])
            total.add(prediction, next_state[starts + horizon - 1], model.normalization)
        rollouts[str(horizon)] = total.to_mapping()
    primary = str(max(evaluation.rollout_horizons))
    return {
        "one_step": one_step.to_mapping(),
        "rollouts": rollouts,
        "primary_horizon_steps": int(primary),
        "primary_rollout": rollouts[primary],
    }


def _model_summary(model: TrainedDynamicsModel) -> dict[str, object]:
    return {
        "lift": model.lift.kind,
        "lift_dimension": model.lift.feature_dimension,
        "ridge": model.ridge,
    }


def _dataset_provenance(dataset: AuditedDataset) -> dict[str, object]:
    return {
        "dataset_id": dataset.dataset_id,
        "audit_output_id": dataset.audit_output_id,
        "audit_sha256": dataset.audit_sha256,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "splits": {
            split: [episode.episode_id for episode in dataset.episodes_by_split[split]]
            for split in _SPLITS
        },
    }


def _select_koopman_candidate(
    definition: KoopmanModelDefinition, validation_metrics: Mapping[str, Mapping[str, object]]
) -> str:
    return min(
        (candidate.name for candidate in definition.rff_candidates),
        key=lambda name: float(
            validation_metrics[name]["primary_rollout"]["state_normalized_rmse"]  # type: ignore[index]
        ),
    )


def _load_selection(
    project_root: Path,
    selection_output: str,
    definition: KoopmanModelDefinition,
    dataset: AuditedDataset,
    model_config_sha256: str,
) -> str:
    _validate_output_id(selection_output, "selection output")
    payload = _read_mapping(
        project_root / MODEL_OUTPUT_ROOT / selection_output / "selection.json", "model selection"
    )
    if payload.get("evaluation_stage") != "validation":
        raise ValueError("model selection was not produced by the validation stage")
    if payload.get("model_id") != definition.model_id:
        raise ValueError("model selection belongs to a different registered model")
    if payload.get("model_config_sha256") != model_config_sha256:
        raise ValueError("model configuration changed after validation selection")
    if payload.get("dataset_audit_sha256") != dataset.audit_sha256:
        raise ValueError("dataset audit changed after validation selection")
    if payload.get("dataset_manifest_sha256") != dataset.manifest_sha256:
        raise ValueError("dataset manifest changed after validation selection")
    selected = payload.get("selected_by_validation")
    if selected not in {candidate.name for candidate in definition.rff_candidates}:
        raise ValueError("model selection does not name a registered Koopman candidate")
    return selected


def train_and_evaluate(
    project_root: Path,
    *,
    model_id: str,
    dataset_id: str,
    dataset_audit_output: str,
    output_id: str,
    evaluation_stage: str,
    selection_output: str | None,
) -> int:
    """Fit a registered model family for validation selection or final test reporting."""

    if evaluation_stage not in {"validation", "final"}:
        raise ValueError("evaluation stage must be validation or final")
    if evaluation_stage == "validation" and selection_output is not None:
        raise ValueError("validation stage cannot consume a prior selection")
    if evaluation_stage == "final" and not selection_output:
        raise ValueError("final stage requires a validation selection output")
    _validate_output_id(output_id, "model output")
    definition = resolve_model_definition(model_id, dataset_id, project_root)
    output_dir = project_root / MODEL_OUTPUT_ROOT / output_id
    try:
        output_dir.mkdir(parents=True)
    except FileExistsError as error:
        raise ValueError(f"model output directory already exists: {output_dir}") from error
    try:
        dataset = load_audited_dataset(project_root, definition.dataset_id, dataset_audit_output)
        model_config_path = project_root / definition.config_rel
        model_config_sha256 = _sha256(model_config_path)
        split_transitions = {
            split: _load_split_transitions(dataset.episodes_by_split[split])
            for split in ("train", "validation")
        }
        normalization, models = fit_models(definition, split_transitions["train"])
        validation_metrics = {
            name: evaluate_model(model, split_transitions["validation"], definition.evaluation)
            for name, model in models.items()
        }
        selected_model = _select_koopman_candidate(definition, validation_metrics)
        if evaluation_stage == "final":
            selected_model = _load_selection(
                project_root,
                selection_output or "",
                definition,
                dataset,
                model_config_sha256,
            )
            test_transitions = _load_split_transitions(dataset.episodes_by_split["test"])
            test_models = ("linear_affine", selected_model)
            test_metrics = {
                name: evaluate_model(models[name], test_transitions, definition.evaluation)
                for name in test_models
            }
        else:
            test_transitions = ()
            test_metrics = None
        requested = {
            "model_id": definition.model_id,
            "model_config": definition.config_rel,
            "dataset_id": definition.dataset_id,
            "dataset_audit_output": dataset_audit_output,
            "output_id": output_id,
            "evaluation_stage": evaluation_stage,
            "selection_output": selection_output,
        }
        _write_json(output_dir / "requested_config.json", requested)
        _write_json(output_dir / "model_config.json", _read_mapping(model_config_path, "model config"))
        _write_json(output_dir / "dataset_provenance.json", _dataset_provenance(dataset))
        _write_json(output_dir / "normalization.json", normalization.to_mapping())
        _write_json(output_dir / "validation_metrics.json", validation_metrics)
        selection = {
            "evaluation_stage": "validation",
            "model_id": definition.model_id,
            "model_config_sha256": model_config_sha256,
            "dataset_audit_sha256": dataset.audit_sha256,
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "selected_by_validation": selected_model,
            "selection_metric": "primary_rollout.state_normalized_rmse",
            "primary_horizon_steps": max(definition.evaluation.rollout_horizons),
        }
        _write_json(output_dir / "selection.json", selection)
        if test_metrics is not None:
            _write_json(output_dir / "test_metrics.json", test_metrics)
        np.savez_compressed(
            output_dir / "models.npz",
            state_mean=normalization.state_mean,
            state_scale=normalization.state_scale,
            action_mean=normalization.action_mean,
            action_scale=normalization.action_scale,
            **{key: value for name, model in models.items() for key, value in model.to_npz(name).items()},
        )
        summary = {
            "status": "complete",
            "created_at_utc": _utc_timestamp(),
            "evaluation_stage": evaluation_stage,
            "model_id": definition.model_id,
            "model_config_sha256": model_config_sha256,
            "dataset": _dataset_provenance(dataset),
            "train_transitions": sum(len(episode[0]) for episode in split_transitions["train"]),
            "validation_transitions": sum(
                len(episode[0]) for episode in split_transitions["validation"]
            ),
            "test_transitions": sum(len(episode[0]) for episode in test_transitions),
            "models": {name: _model_summary(model) for name, model in models.items()},
            "selected_by_validation": selected_model,
            "validation_primary": {
                name: metrics["primary_rollout"] for name, metrics in validation_metrics.items()
            },
            "test_evaluated": test_metrics is not None,
            "test_primary": (
                {name: metrics["primary_rollout"] for name, metrics in test_metrics.items()}
                if test_metrics is not None
                else None
            ),
        }
        _write_json(output_dir / "summary.json", summary)
        _write_json(
            output_dir / "metadata.json",
            {
                "created_at_utc": _utc_timestamp(),
                "python_version": sys.version,
                "platform": platform.platform(),
                "numpy_version": np.__version__,
            },
        )
        (output_dir / "exit_code").write_text("0\n", encoding="utf-8")
        (output_dir / "COMPLETE").touch()
    except Exception as error:
        (output_dir / "FAILED").touch()
        (output_dir / "exit_code").write_text("1\n", encoding="utf-8")
        (output_dir / "error.log").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        raise
    print(f"model_output_dir={output_dir}")
    print(f"evaluation_stage={evaluation_stage}")
    print(f"selected_by_validation={selected_model}")
    print("model_training=passed")
    return 0
