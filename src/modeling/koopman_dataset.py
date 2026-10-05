"""Contracts and quality checks for Koopman forward-dynamics datasets.

The SOFA recorder writes the action applied during a step and the state observed
after that step.  A learning transition is therefore assembled as
``(state[t - 1], action[t], state[t])`` within one episode.  Episode boundaries
are never crossed.
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from simulation.forward_data import CABLE_NAMES


DATASET_SPLITS = ("train", "validation", "test")
CENTERLINE_POINT_COUNT = 10

ACTION_COLUMNS = tuple(f"{cable}_command_mm" for cable in CABLE_NAMES)
_CABLE_STATE_COLUMNS = tuple(
    column
    for cable in CABLE_NAMES
    for column in (f"{cable}_displacement_mm", f"{cable}_force")
)
_TIP_STATE_COLUMNS = ("tip_x_mm", "tip_y_mm", "tip_z_mm")
_CENTERLINE_STATE_COLUMNS = tuple(
    f"centerline_{point}_{component}"
    for point in range(CENTERLINE_POINT_COUNT)
    for component in (
        "x_mm",
        "y_mm",
        "z_mm",
        "vx_mm_s",
        "vy_mm_s",
        "vz_mm_s",
    )
)
STATE_COLUMNS = _CABLE_STATE_COLUMNS + _TIP_STATE_COLUMNS + _CENTERLINE_STATE_COLUMNS
REQUIRED_COLUMNS = (
    "step",
    "time_s",
    "phase",
    "command_limited",
    *ACTION_COLUMNS,
    *STATE_COLUMNS,
    "non_finite",
)


def _parse_finite(value: str | None, column: str, row_number: int) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"row {row_number}: {column} is not numeric") from error
    if not math.isfinite(parsed):
        raise ValueError(f"row {row_number}: {column} is not finite")
    return parsed


def _parse_binary(value: str | None, column: str, row_number: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"row {row_number}: {column} must be 0 or 1") from error
    if parsed not in (0, 1):
        raise ValueError(f"row {row_number}: {column} must be 0 or 1")
    return parsed


@dataclass(frozen=True)
class DatasetEpisode:
    """One immutable episode assigned to exactly one dataset split."""

    episode_id: str
    split: str
    csv_path: Path
    dt_s: float

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("episode_id must be non-empty")
        if self.split not in DATASET_SPLITS:
            raise ValueError(f"unsupported dataset split: {self.split}")
        if not math.isfinite(self.dt_s) or self.dt_s <= 0.0:
            raise ValueError("episode dt_s must be positive and finite")


@dataclass(frozen=True)
class DatasetQualityPolicy:
    """Fixed quality gates for a versioned Koopman dataset."""

    min_rows_per_episode: int
    min_action_span_mm: float
    max_limited_command_fraction: float

    def __post_init__(self) -> None:
        if self.min_rows_per_episode < 2:
            raise ValueError("min_rows_per_episode must be at least two")
        if not math.isfinite(self.min_action_span_mm) or self.min_action_span_mm < 0.0:
            raise ValueError("min_action_span_mm must be finite and non-negative")
        if (
            not math.isfinite(self.max_limited_command_fraction)
            or not 0.0 <= self.max_limited_command_fraction <= 1.0
        ):
            raise ValueError("max_limited_command_fraction must lie in [0, 1]")


@dataclass(frozen=True)
class DynamicsTransition:
    """One model-ready direct-dynamics transition from a single episode."""

    state: tuple[float, ...]
    action: tuple[float, ...]
    next_state: tuple[float, ...]


@dataclass(frozen=True)
class EpisodeAudit:
    episode_id: str
    split: str
    path: str
    sha256: str
    rows: int
    transitions: int
    limited_command_fraction: float
    action_min_mm: Mapping[str, float]
    action_max_mm: Mapping[str, float]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetAudit:
    """Serializable result of applying the dataset contract to all episodes."""

    episodes: tuple[EpisodeAudit, ...]
    split_rows: Mapping[str, int]
    split_transitions: Mapping[str, int]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and all(episode.ok for episode in self.episodes)

    def to_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "state_columns": list(STATE_COLUMNS),
            "action_columns": list(ACTION_COLUMNS),
            "episodes": [episode.to_mapping() for episode in self.episodes],
            "split_rows": dict(self.split_rows),
            "split_transitions": dict(self.split_transitions),
            "errors": list(self.errors),
        }


def _read_episode(path: Path) -> tuple[tuple[dict[str, str], ...], tuple[str, ...]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            rows = tuple(dict(row) for row in reader)
    except OSError as error:
        raise ValueError(f"cannot read episode CSV: {path}") from error
    return rows, header


def _episode_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_rows(
    rows: Sequence[Mapping[str, str]],
    episode: DatasetEpisode,
    policy: DatasetQualityPolicy,
) -> tuple[tuple[str, ...], float, dict[str, float], dict[str, float]]:
    errors: list[str] = []
    if len(rows) < policy.min_rows_per_episode:
        errors.append(
            f"expected at least {policy.min_rows_per_episode} rows, found {len(rows)}"
        )

    action_min = {column: math.inf for column in ACTION_COLUMNS}
    action_max = {column: -math.inf for column in ACTION_COLUMNS}
    limited_count = 0
    numeric_columns = ACTION_COLUMNS + STATE_COLUMNS
    for row_index, row in enumerate(rows):
        row_number = row_index + 2  # Header occupies physical CSV row one.
        try:
            step = _parse_finite(row.get("step"), "step", row_number)
            if step != row_index:
                raise ValueError(
                    f"row {row_number}: step is {step:g}, expected {row_index}"
                )
            expected_time = (row_index + 1) * episode.dt_s
            time_s = _parse_finite(row.get("time_s"), "time_s", row_number)
            if abs(time_s - expected_time) > 1e-9:
                raise ValueError(
                    f"row {row_number}: time_s is {time_s:g}, expected {expected_time:g}"
                )
            if row.get("phase") not in {"settle", "excitation"}:
                raise ValueError(f"row {row_number}: invalid phase {row.get('phase')!r}")
            limited_count += _parse_binary(
                row.get("command_limited"), "command_limited", row_number
            )
            if _parse_binary(row.get("non_finite"), "non_finite", row_number):
                raise ValueError(f"row {row_number}: recorder flagged non-finite data")
            for column in numeric_columns:
                value = _parse_finite(row.get(column), column, row_number)
                if column in action_min:
                    action_min[column] = min(action_min[column], value)
                    action_max[column] = max(action_max[column], value)
        except ValueError as error:
            errors.append(str(error))
            if len(errors) >= 20:
                errors.append("additional row errors omitted")
                break

    fraction = limited_count / len(rows) if rows else 1.0
    if fraction > policy.max_limited_command_fraction:
        errors.append(
            "limited command fraction "
            f"{fraction:.6f} exceeds {policy.max_limited_command_fraction:.6f}"
        )
    for column in ACTION_COLUMNS:
        span = action_max[column] - action_min[column]
        if not math.isfinite(span) or span < policy.min_action_span_mm:
            errors.append(
                f"action span for {column} is {span:g}, below {policy.min_action_span_mm:g}"
            )
    return tuple(errors), fraction, action_min, action_max


def audit_episode(episode: DatasetEpisode, policy: DatasetQualityPolicy) -> EpisodeAudit:
    """Audit one CSV episode without changing it."""

    try:
        rows, header = _read_episode(episode.csv_path)
        sha256 = _episode_hash(episode.csv_path)
    except ValueError as error:
        return EpisodeAudit(
            episode_id=episode.episode_id,
            split=episode.split,
            path=str(episode.csv_path),
            sha256="",
            rows=0,
            transitions=0,
            limited_command_fraction=1.0,
            action_min_mm={},
            action_max_mm={},
            errors=(str(error),),
        )
    missing = sorted(set(REQUIRED_COLUMNS) - set(header))
    if missing:
        return EpisodeAudit(
            episode_id=episode.episode_id,
            split=episode.split,
            path=str(episode.csv_path),
            sha256=sha256,
            rows=len(rows),
            transitions=max(0, len(rows) - 1),
            limited_command_fraction=1.0,
            action_min_mm={},
            action_max_mm={},
            errors=(f"missing required columns: {', '.join(missing)}",),
        )
    errors, fraction, action_min, action_max = _validate_rows(rows, episode, policy)
    return EpisodeAudit(
        episode_id=episode.episode_id,
        split=episode.split,
        path=str(episode.csv_path),
        sha256=sha256,
        rows=len(rows),
        transitions=max(0, len(rows) - 1),
        limited_command_fraction=fraction,
        action_min_mm=action_min,
        action_max_mm=action_max,
        errors=errors,
    )


def audit_dataset(
    episodes: Iterable[DatasetEpisode], policy: DatasetQualityPolicy
) -> DatasetAudit:
    """Validate split isolation, episode quality and action coverage."""

    declared = tuple(episodes)
    errors: list[str] = []
    ids = [episode.episode_id for episode in declared]
    if len(ids) != len(set(ids)):
        errors.append("dataset episode IDs must be unique")
    paths = [episode.csv_path.resolve() for episode in declared]
    if len(paths) != len(set(paths)):
        errors.append("one episode CSV cannot be assigned more than once")

    audited = tuple(audit_episode(episode, policy) for episode in declared)
    split_rows = {split: 0 for split in DATASET_SPLITS}
    split_transitions = {split: 0 for split in DATASET_SPLITS}
    split_counts = {split: 0 for split in DATASET_SPLITS}
    hashes: dict[str, list[EpisodeAudit]] = {}
    for result in audited:
        split_counts[result.split] += 1
        split_rows[result.split] += result.rows
        split_transitions[result.split] += result.transitions
        if result.sha256:
            hashes.setdefault(result.sha256, []).append(result)
    for split, count in split_counts.items():
        if count == 0:
            errors.append(f"dataset split is empty: {split}")
    for sha256, same_content in hashes.items():
        if len(same_content) > 1:
            labels = ", ".join(
                f"{result.episode_id}:{result.split}" for result in same_content
            )
            errors.append(f"duplicate episode content {sha256[:12]} across {labels}")
    return DatasetAudit(
        episodes=audited,
        split_rows=split_rows,
        split_transitions=split_transitions,
        errors=tuple(errors),
    )


def load_transitions(episode: DatasetEpisode) -> tuple[DynamicsTransition, ...]:
    """Load aligned transitions after the caller has accepted an audit result.

    The first recorded row has no pre-action state in the CSV, so an episode of
    ``N`` recorded steps supplies exactly ``N - 1`` transitions.
    """

    rows, header = _read_episode(episode.csv_path)
    missing = sorted(set(REQUIRED_COLUMNS) - set(header))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    parsed: list[dict[str, float]] = []
    for row_index, row in enumerate(rows):
        row_number = row_index + 2
        parsed.append(
            {
                column: _parse_finite(row.get(column), column, row_number)
                for column in ACTION_COLUMNS + STATE_COLUMNS
            }
        )
    return tuple(
        DynamicsTransition(
            state=tuple(previous[column] for column in STATE_COLUMNS),
            action=tuple(current[column] for column in ACTION_COLUMNS),
            next_state=tuple(current[column] for column in STATE_COLUMNS),
        )
        for previous, current in zip(parsed, parsed[1:])
    )
