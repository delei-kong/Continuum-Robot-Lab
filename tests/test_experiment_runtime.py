import csv
import json
import tempfile
import unittest
from pathlib import Path

from experiment.contracts import RunManifest
from experiment.runtime import build_sofa_command, verify_tracking_artifacts
from experiment.tracking_cli import build_run_manifest, resolve_tracking_spec


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _manifest(*, mode: str = "batch", steps: int = 2) -> RunManifest:
    return RunManifest(
        run_id="runtime_test_v1",
        pipeline_id="trunk_tracking",
        input_id="line",
        algorithm_id="reference_goal",
        config_rel="configs/trunk_trajectory_tracking_line.json",
        scene_rel="src/simulation/scenes/trunk_trajectory_tracking.py",
        artifact_profile="trajectory_tracking",
        steps=steps,
        mode=mode,
        timeout_s=300,
        gui_description="test GUI description",
    )


def _forward_manifest(*, mode: str = "batch", steps: int = 2) -> RunManifest:
    return RunManifest(
        run_id="forward_runtime_test_v1",
        pipeline_id="trunk_forward_data",
        input_id="multisine_pilot",
        algorithm_id="direct_multisine",
        config_rel="configs/trunk_forward_multisine_pilot.json",
        scene_rel="src/simulation/scenes/trunk_forward_data.py",
        artifact_profile="trunk_forward_data",
        steps=steps,
        mode=mode,
        timeout_s=300,
        gui_description="test forward-data GUI description",
    )


class RunManifestTest(unittest.TestCase):
    def test_round_trip_rejects_unexpected_fields(self) -> None:
        manifest = _manifest(mode="gui", steps=350)
        self.assertEqual(RunManifest.from_json(manifest.to_json()), manifest)
        payload = manifest.to_mapping()
        payload["uncontrolled"] = True
        with self.assertRaisesRegex(ValueError, "unexpected"):
            RunManifest.from_mapping(payload)

    def test_tracking_manifest_is_derived_from_registered_spec(self) -> None:
        spec = resolve_tracking_spec("ellipse", "reference_goal", PROJECT_ROOT)
        manifest = build_run_manifest(spec, "ellipse_manifest_v1", "gui")
        self.assertEqual(manifest.pipeline_id, "trunk_tracking")
        self.assertEqual(manifest.run_id, "ellipse_manifest_v1")
        self.assertEqual(manifest.steps, 350)
        self.assertEqual(manifest.mode, "gui")
        self.assertEqual(manifest.config_rel, spec.config_rel)


class RuntimePlanTest(unittest.TestCase):
    def test_batch_and_gui_share_sofa_core_command(self) -> None:
        paths = {
            "runsofa": Path("/runtime/bin/runSofa"),
            "validation": Path("/runtime/lib/libSofaValidation.so"),
            "scene": Path("/workspace/src/simulation/scenes/trunk.py"),
        }
        batch = build_sofa_command(
            _manifest(mode="batch"),
            runsofa=paths["runsofa"],
            sofa_validation_library=paths["validation"],
            scene=paths["scene"],
        )
        gui = build_sofa_command(
            _manifest(mode="gui"),
            runsofa=paths["runsofa"],
            sofa_validation_library=paths["validation"],
            scene=paths["scene"],
        )
        self.assertEqual(batch[:10], gui[:10])
        self.assertEqual(batch[-1], gui[-1])
        self.assertIn("batch", batch)
        self.assertIn("SofaImGui", gui)
        self.assertIn("imgui", gui)

    def test_forward_data_command_excludes_inverse_plugin(self) -> None:
        command = build_sofa_command(
            _forward_manifest(),
            runsofa=Path("/runtime/bin/runSofa"),
            sofa_validation_library=Path("/runtime/lib/libSofaValidation.so"),
            scene=Path("/workspace/src/simulation/scenes/trunk_forward_data.py"),
        )
        self.assertIn("SoftRobots", command)
        self.assertNotIn("SoftRobots.Inverse", command)


class ArtifactVerificationTest(unittest.TestCase):
    def _write_artifacts(self, root: Path, rows: int, stdout: str = "[INFO] ok\n") -> None:
        with (root / "trajectory.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("step", "x"))
            writer.writeheader()
            for step in range(rows):
                writer.writerow({"step": step, "x": 0.0})
        (root / "performance.json").write_text(json.dumps({"completed_steps": rows}), encoding="utf-8")
        (root / "stdout.log").write_text(stdout, encoding="utf-8")

    def test_complete_artifacts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_artifacts(root, rows=2)
            result = verify_tracking_artifacts(root, _manifest(), process_exit_code=0)
        self.assertTrue(result.ok)
        self.assertEqual(result.row_count, 2)

    def test_missing_rows_and_error_log_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_artifacts(root, rows=1, stdout="[ERROR] bad\n")
            result = verify_tracking_artifacts(root, _manifest(), process_exit_code=4)
        self.assertFalse(result.ok)
        self.assertIn("runSofa exit code was 4", result.errors)
        self.assertTrue(any("row count" in error for error in result.errors))
        self.assertTrue(any("[ERROR]" in error for error in result.errors))

    def test_forward_data_artifacts_pass_without_tracking_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (root / "episode.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("step", "state"))
                writer.writeheader()
                for step in range(2):
                    writer.writerow({"step": step, "state": 0.0})
            (root / "stdout.log").write_text("[INFO] ok\n", encoding="utf-8")
            result = verify_tracking_artifacts(
                root, _forward_manifest(), process_exit_code=0
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.row_count, 2)


if __name__ == "__main__":
    unittest.main()
