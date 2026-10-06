"""Checks for the canonical, Git-ignored Koopman dataset release format."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from modeling.koopman_dataset import (
    ACTION_COLUMNS,
    REQUIRED_COLUMNS,
    STATE_COLUMNS,
    DatasetEpisode,
    DatasetQualityPolicy,
    audit_dataset,
)
from modeling.koopman_dataset_cli import (
    KoopmanDatasetDefinition,
    materialize_canonical_dataset,
)
from modeling.koopman_model import load_canonical_dataset


POLICY = DatasetQualityPolicy(
    min_rows_per_episode=3,
    min_action_span_mm=0.5,
    max_limited_command_fraction=0.2,
)


def _write_episode(path: Path, offset: float) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for step in range(3):
            row: dict[str, object] = {
                "step": step,
                "time_s": (step + 1) * 0.01,
                "phase": "settle" if step == 0 else "excitation",
                "command_limited": 0,
                "non_finite": 0,
            }
            for index, column in enumerate(ACTION_COLUMNS):
                row[column] = offset + step + index * 0.01
            for index, column in enumerate(STATE_COLUMNS):
                row[column] = offset + step * 10.0 + index * 0.001
            writer.writerow(row)


class CanonicalKoopmanDatasetReleaseTest(unittest.TestCase):
    def test_materialized_release_is_self_describing_and_loadable(self) -> None:
        definition = KoopmanDatasetDefinition(
            dataset_id="koopman_v1",
            config_rel="configs/koopman_dataset_v1.json",
            dt_s=0.01,
            required_batches={},
            policy=POLICY,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_entries = []
            episodes = []
            for index, split in enumerate(("train", "validation", "test")):
                episode_id = f"{split}_episode"
                run_dir = root / "outputs" / "trunk_forward_data" / episode_id
                run_dir.mkdir(parents=True)
                _write_episode(run_dir / "episode.csv", float(index + 1))
                (run_dir / "effective_config.json").write_text("{}\n", encoding="utf-8")
                (run_dir / "metadata.json").write_text("{}\n", encoding="utf-8")
                source_entries.append(
                    {"episode_id": episode_id, "split": split, "run_dir": str(run_dir)}
                )
                episodes.append(DatasetEpisode(episode_id, split, run_dir / "episode.csv", 0.01))
            report = audit_dataset(episodes, POLICY)
            self.assertTrue(report.ok)
            audit_dir = root / "outputs" / "koopman_datasets" / "audit_v1"
            audit_dir.mkdir(parents=True)
            (audit_dir / "dataset_manifest.json").write_text(
                json.dumps({"dataset_id": "koopman_v1", "episodes": source_entries}),
                encoding="utf-8",
            )
            (audit_dir / "audit.json").write_text(
                json.dumps(report.to_mapping()), encoding="utf-8"
            )

            self.assertEqual(
                materialize_canonical_dataset(
                    root,
                    definition,
                    audit_output_name="audit_v1",
                    release_name="release_v1",
                ),
                0,
            )
            with patch("modeling.koopman_model.resolve_dataset_definition", return_value=definition):
                dataset = load_canonical_dataset(root, "koopman_v1", "release_v1")
            self.assertEqual(dataset.release_id, "release_v1")
            self.assertEqual(len(dataset.transitions_by_split["train"]), 1)
            state, action, next_state = dataset.transitions_by_split["train"][0]
            self.assertEqual(state.shape, (2, len(STATE_COLUMNS)))
            self.assertEqual(action.shape, (2, len(ACTION_COLUMNS)))
            self.assertEqual(next_state.shape, (2, len(STATE_COLUMNS)))
            self.assertTrue(np.all(np.isfinite(state)))


if __name__ == "__main__":
    unittest.main()
