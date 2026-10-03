import unittest
from pathlib import Path

from evaluation.trajectory_cli import (
    build_runner_environment,
    default_output_name,
    resolve_run_spec,
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
        self.assertEqual(
            build_runner_environment(line)["TRUNK_INVERSE_CONFIG_REL"],
            "configs/trunk_trajectory_tracking_line.json",
        )
        self.assertEqual(
            build_runner_environment(triangle)["TRUNK_INVERSE_CONFIG_REL"],
            "configs/trunk_trajectory_tracking_rounded_triangle.json",
        )

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
        self.assertTrue(output_name.endswith("_trunk_trajectory_cli"))
        self.assertEqual(validate_output_name(output_name), output_name)

    def test_remote_workspace_runner_uses_server_entrypoint(self) -> None:
        spec = resolve_run_spec("ellipse", "reference_goal")
        self.assertEqual(spec.steps, 350)
        self.assertTrue(
            (
                PROJECT_ROOT
                / "scripts/server/run_trunk_trajectory_tracking_batch.sh"
            ).is_file()
        )
        self.assertTrue(
            (
                PROJECT_ROOT
                / "scripts/server/run_trunk_trajectory_tracking_gui.sh"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
