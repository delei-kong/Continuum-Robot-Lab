import csv
import tempfile
import unittest
from pathlib import Path

from modeling.koopman_dataset import (
    ACTION_COLUMNS,
    REQUIRED_COLUMNS,
    STATE_COLUMNS,
    DatasetEpisode,
    DatasetQualityPolicy,
    audit_dataset,
    audit_episode,
    load_transitions,
)


POLICY = DatasetQualityPolicy(
    min_rows_per_episode=3,
    min_action_span_mm=0.5,
    max_limited_command_fraction=0.2,
)


def _row(step: int, *, offset: float = 0.0) -> dict[str, object]:
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
    return row


def _write_episode(path: Path, *, offset: float = 0.0) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for step in range(3):
            writer.writerow(_row(step, offset=offset))


class KoopmanDatasetAuditTest(unittest.TestCase):
    def test_valid_episode_and_isolated_splits_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            episodes = []
            for index, split in enumerate(("train", "validation", "test")):
                path = root / f"{split}.csv"
                _write_episode(path, offset=float(index + 1))
                episodes.append(DatasetEpisode(split, split, path, 0.01))
            report = audit_dataset(episodes, POLICY)
        self.assertTrue(report.ok)
        self.assertEqual(report.split_rows, {"train": 3, "validation": 3, "test": 3})
        self.assertEqual(
            report.split_transitions,
            {"train": 2, "validation": 2, "test": 2},
        )

    def test_duplicate_content_and_recorder_flag_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            train = root / "train.csv"
            validation = root / "validation.csv"
            test = root / "test.csv"
            _write_episode(train)
            _write_episode(validation)
            validation.write_bytes(train.read_bytes())
            _write_episode(test, offset=3.0)
            with test.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows[1]["non_finite"] = "1"
            with test.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            report = audit_dataset(
                (
                    DatasetEpisode("train", "train", train, 0.01),
                    DatasetEpisode("validation", "validation", validation, 0.01),
                    DatasetEpisode("test", "test", test, 0.01),
                ),
                POLICY,
            )
        self.assertFalse(report.ok)
        self.assertTrue(any("duplicate episode content" in error for error in report.errors))
        self.assertTrue(any("non-finite" in error for error in report.episodes[2].errors))

    def test_transition_uses_previous_state_and_current_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "episode.csv"
            _write_episode(path, offset=1.0)
            episode = DatasetEpisode("train_01", "train", path, 0.01)
            audit = audit_episode(episode, POLICY)
            transitions = load_transitions(episode)
        self.assertTrue(audit.ok)
        self.assertEqual(len(transitions), 2)
        self.assertEqual(transitions[0].state[0], 1.0)
        self.assertEqual(transitions[0].action[0], 2.0)
        self.assertEqual(transitions[0].next_state[0], 11.0)


if __name__ == "__main__":
    unittest.main()
