import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiment import tracking_cli
from experiment.tracking_cli import (
    build_run_manifest,
    default_output_name,
    derive_steps_from_config,
    resolve_run_spec,
    resolve_tracking_batch,
    resolve_tracking_spec,
    run_tracking_batch,
    validate_output_name,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TrajectoryCliTest(unittest.TestCase):
    def test_aliases_resolve_to_registered_configs(self) -> None:
        line = resolve_run_spec("line", "reference")
        ellipse = resolve_run_spec("periodic_ellipse", "reference_goal")
        circle = resolve_run_spec("circle", "reference_goal")
        triangle = resolve_run_spec("triangle", "reference_goal")
        square = resolve_run_spec("rounded_square", "reference_goal")
        single_target = resolve_tracking_spec(
            "target", "reference_goal", PROJECT_ROOT
        )
        periodic_random = resolve_tracking_spec(
            "random", "reference_goal", PROJECT_ROOT
        )
        self.assertEqual(line.trajectory, "line")
        self.assertEqual(line.steps, 200)
        self.assertEqual(ellipse.trajectory, "ellipse")
        self.assertEqual(ellipse.steps, 350)
        self.assertEqual(circle.trajectory, "circle")
        self.assertEqual(triangle.trajectory, "rounded_triangle")
        self.assertEqual(square.trajectory, "rounded_square")
        self.assertEqual(circle.steps, 350)
        self.assertEqual(triangle.steps, 350)
        self.assertEqual(square.steps, 350)
        self.assertEqual(single_target.input_name, "single_target")
        self.assertEqual(single_target.steps, 200)
        self.assertEqual(periodic_random.input_name, "periodic_random")
        self.assertEqual(periodic_random.steps, 925)
        manifest = build_run_manifest(ellipse, "ellipse_manifest_v1", "batch")
        self.assertEqual(manifest.run_id, "ellipse_manifest_v1")
        self.assertEqual(manifest.mode, "batch")
        self.assertEqual(manifest.steps, 350)
        self.assertEqual(manifest.config_rel, ellipse.config_rel)
        self.assertEqual(manifest.scene_rel, ellipse.scene_rel)
        self.assertEqual(manifest.artifact_profile, ellipse.artifact_profile)

    def test_unknown_combination_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_run_spec("unknown", "reference_goal")
        with self.assertRaises(ValueError):
            resolve_run_spec("line", "pid")

    def test_output_name_cannot_escape_run_directory(self) -> None:
        self.assertEqual(validate_output_name("ellipse_v1"), "ellipse_v1")
        with self.assertRaises(ValueError):
            validate_output_name("../outside")
        with self.assertRaises(ValueError):
            validate_output_name("name with spaces")

    def test_default_output_name_is_a_valid_run_id(self) -> None:
        output_name = default_output_name()
        self.assertTrue(output_name.endswith("_tracking"))
        self.assertEqual(validate_output_name(output_name), output_name)

    def test_step_derivation_rejects_inconsistent_control_period(self) -> None:
        with self.assertRaises(ValueError):
            derive_steps_from_config(
                {"dt": 0.04, "control_rate_hz": 20.0, "duration_s": 8.0}
            )

    def test_new_entrypoints_exist(self) -> None:
        self.assertTrue(
            (
                PROJECT_ROOT
                / "scripts/experiment/run_tracking.py"
            ).is_file()
        )

    @patch("experiment.tracking_cli.run_server_batch", return_value=17)
    def test_server_batch_dispatches_resolved_spec(self, run_server_batch) -> None:
        spec = resolve_tracking_spec("ellipse", "reference_goal", PROJECT_ROOT)
        result = tracking_cli.run_tracking_experiment(
            PROJECT_ROOT,
            spec,
            "ellipse_v1",
            target="server",
            mode="batch",
        )
        self.assertEqual(result, 17)
        run_server_batch.assert_called_once_with(PROJECT_ROOT, spec, "ellipse_v1")

    def test_local_gui_is_rejected_before_starting_a_process(self) -> None:
        spec = resolve_tracking_spec("line", "reference_goal", PROJECT_ROOT)
        with self.assertRaisesRegex(ValueError, "GUI mode"):
            tracking_cli.run_tracking_experiment(
                PROJECT_ROOT,
                spec,
                "line_gui_v1",
                target="local",
                mode="gui",
            )
        self.assertTrue(
            (
                PROJECT_ROOT
                / "scripts/remote/fetch_run.sh"
            ).is_file()
        )

    def test_registered_batch_resolves_only_approved_cases(self) -> None:
        cases = resolve_tracking_batch(
            "baseline_trajectories", "reference_goal", PROJECT_ROOT
        )
        self.assertEqual([case.input_name for case in cases], ["line", "ellipse"])
        with self.assertRaises(ValueError):
            resolve_tracking_batch("unregistered", "reference_goal", PROJECT_ROOT)

    @patch(
        "experiment.tracking_cli.run_tracking_experiment",
        side_effect=[0, RuntimeError("simulated adapter failure")],
    )
    def test_batch_persists_each_case_and_continues_after_failure(self, runner) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result_root = Path(temporary_directory) / "tracking_batches"
            result = run_tracking_batch(
                PROJECT_ROOT,
                "baseline_trajectories",
                "reference_goal",
                "batch_v1",
                target="server",
                results_root=result_root,
            )
            batch_dir = result_root / "batch_v1"
            manifest = json.loads(
                (batch_dir / "batch_manifest.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (batch_dir / "summary.json").read_text(encoding="utf-8")
            )
            with (batch_dir / "summary.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(result, 1)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual([case["run_id"] for case in manifest["cases"]], [
            "batch_v1__line",
            "batch_v1__ellipse",
        ])
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual([row["status"] for row in rows], ["succeeded", "failed"])
        self.assertIn("simulated adapter failure", rows[1]["error"])


if __name__ == "__main__":
    unittest.main()
