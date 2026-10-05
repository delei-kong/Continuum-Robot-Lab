import unittest
from pathlib import Path
from unittest.mock import patch

from experiment import forward_data_cli
from experiment.forward_data_cli import (
    build_forward_data_manifest,
    resolve_forward_data_spec,
    run_forward_data_experiment,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ForwardDataCliTest(unittest.TestCase):
    def test_registered_input_resolves_to_owned_config_and_scene(self) -> None:
        spec = resolve_forward_data_spec("multisine_pilot", PROJECT_ROOT)
        self.assertEqual(spec.steps, 1000)
        self.assertEqual(spec.config_rel, "configs/trunk_forward_multisine_pilot.json")
        manifest = build_forward_data_manifest(spec, "forward_data_manifest_v1", "batch")
        self.assertEqual(manifest.pipeline_id, "trunk_forward_data")
        self.assertEqual(manifest.artifact_profile, "trunk_forward_data")
        self.assertEqual(manifest.algorithm_id, "direct_multisine")

    def test_unknown_input_and_unsafe_run_id_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_forward_data_spec("unregistered", PROJECT_ROOT)
        spec = resolve_forward_data_spec("multisine_pilot", PROJECT_ROOT)
        with self.assertRaises(ValueError):
            build_forward_data_manifest(spec, "../outside", "batch")

    def test_local_gui_is_rejected_without_starting_boundary(self) -> None:
        spec = resolve_forward_data_spec("multisine_pilot", PROJECT_ROOT)
        with self.assertRaisesRegex(ValueError, "GUI mode"):
            run_forward_data_experiment(
                PROJECT_ROOT,
                spec,
                "forward_gui_v1",
                target="local",
                mode="gui",
            )

    @patch("experiment.forward_data_cli.subprocess.run")
    def test_server_uses_common_experiment_boundary(self, run) -> None:
        run.return_value.returncode = 0
        spec = resolve_forward_data_spec("multisine_pilot", PROJECT_ROOT)
        result = run_forward_data_experiment(
            PROJECT_ROOT,
            spec,
            "forward_batch_v1",
            target="server",
            mode="batch",
        )
        self.assertEqual(result, 0)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "bash")
        self.assertTrue(command[1].endswith("scripts/server/run_experiment.sh"))
        manifest = run.call_args.kwargs["env"]["EXPERIMENT_RUN_MANIFEST"]
        self.assertIn('"pipeline_id": "trunk_forward_data"', manifest)


if __name__ == "__main__":
    unittest.main()
