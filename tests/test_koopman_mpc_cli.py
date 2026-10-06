"""Registration and boundary checks for the Koopman-MPC experiment entrypoint."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch

from experiment.koopman_mpc_cli import (
    build_koopman_mpc_manifest,
    resolve_koopman_mpc_spec,
    run_koopman_mpc_experiment,
)
from simulation.trajectory import trajectory_from_mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class KoopmanMpcCliTest(unittest.TestCase):
    def test_registered_trajectories_resolve_to_direct_mpc_scene(self) -> None:
        expected_configs = {
            "line": "configs/trunk_koopman_mpc_line.json",
            "ellipse": "configs/trunk_koopman_mpc_ellipse.json",
            "circle": "configs/trunk_koopman_mpc_circle.json",
            "triangle": "configs/trunk_koopman_mpc_triangle.json",
            "square": "configs/trunk_koopman_mpc_square.json",
        }
        for input_name, config_rel in expected_configs.items():
            with self.subTest(input_name=input_name):
                spec = resolve_koopman_mpc_spec(input_name, PROJECT_ROOT)
                self.assertEqual(spec.steps, 800)
                self.assertEqual(spec.config_rel, config_rel)
                self.assertEqual(spec.scene_rel, "src/simulation/scenes/trunk_koopman_mpc.py")
                config = json.loads((PROJECT_ROOT / config_rel).read_text(encoding="utf-8"))
                self.assertEqual(config["trajectory"]["settle_duration_s"], 1.0)
                self.assertEqual(config["trajectory_precision_s"], 0.01)
                self.assertEqual(config["trajectory_color_rgba"], [1.0, 0.45, 0.0, 1.0])
        spec = resolve_koopman_mpc_spec("line", PROJECT_ROOT)
        manifest = build_koopman_mpc_manifest(spec, "koopman_mpc_manifest_v1", "batch")
        self.assertEqual(manifest.pipeline_id, "trunk_koopman_mpc")
        self.assertEqual(manifest.algorithm_id, "koopman_mpc")
        self.assertEqual(manifest.artifact_profile, "koopman_mpc_tracking")

    def test_registered_closed_loops_start_at_the_physical_settle_reference(self) -> None:
        expected_start = (13.8, -64.3, 176.8)
        configs: dict[str, dict[str, object]] = {}
        for input_name in ("ellipse", "circle", "triangle", "square"):
            spec = resolve_koopman_mpc_spec(input_name, PROJECT_ROOT)
            config = json.loads((PROJECT_ROOT / spec.config_rel).read_text(encoding="utf-8"))
            configs[input_name] = config
            trajectory = trajectory_from_mapping(config["trajectory"])
            self.assertEqual(trajectory.sample(0.0).position_mm, expected_start)

        circle = configs["circle"]["trajectory"]
        self.assertIsInstance(circle, dict)
        cosine_axis = circle["axis_cos_mm"]
        sine_axis = circle["axis_sin_mm"]
        self.assertIsInstance(cosine_axis, list)
        self.assertIsInstance(sine_axis, list)
        self.assertAlmostEqual(
            math.dist((0.0, 0.0, 0.0), tuple(cosine_axis)),
            math.dist((0.0, 0.0, 0.0), tuple(sine_axis)),
        )
        self.assertAlmostEqual(sum(a * b for a, b in zip(cosine_axis, sine_axis)), 0.0)

        for input_name, expected_waypoints in (("triangle", 3), ("square", 4)):
            trajectory = configs[input_name]["trajectory"]
            self.assertIsInstance(trajectory, dict)
            waypoints = trajectory["waypoints_mm"]
            self.assertIsInstance(waypoints, list)
            self.assertEqual(len(waypoints), expected_waypoints)
            lengths = [
                math.dist(waypoints[index], waypoints[(index + 1) % len(waypoints)])
                for index in range(len(waypoints))
            ]
            for length in lengths[1:]:
                self.assertAlmostEqual(length, lengths[0])

    def test_unregistered_input_and_local_gui_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_koopman_mpc_spec("unregistered", PROJECT_ROOT)
        spec = resolve_koopman_mpc_spec("line", PROJECT_ROOT)
        with self.assertRaisesRegex(ValueError, "GUI mode"):
            run_koopman_mpc_experiment(
                PROJECT_ROOT,
                spec,
                "koopman_mpc_gui_v1",
                target="local",
                mode="gui",
            )

    @patch("experiment.koopman_mpc_cli.subprocess.run")
    def test_server_uses_common_manifest_boundary(self, run) -> None:
        run.return_value.returncode = 0
        spec = resolve_koopman_mpc_spec("line", PROJECT_ROOT)
        result = run_koopman_mpc_experiment(
            PROJECT_ROOT,
            spec,
            "koopman_mpc_batch_v1",
            target="server",
            mode="batch",
        )
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0][0], "bash")
        self.assertTrue(run.call_args.args[0][1].endswith("scripts/server/run_experiment.sh"))
        self.assertIn('"pipeline_id": "trunk_koopman_mpc"', run.call_args.kwargs["env"]["EXPERIMENT_RUN_MANIFEST"])


if __name__ == "__main__":
    unittest.main()
