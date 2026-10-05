import unittest

from control.pid_controller import TaskSpacePIDController
from control.reference_controller import controller_from_mapping
from control.tracking_contracts import (
    ControllerContext,
    TaskSpaceGoalCommand,
    TrackingObservation,
    TrajectoryReference,
)


class TaskSpacePIDControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ControllerContext(
            dt_s=0.1,
            cable_count=8,
            supported_command_kinds=frozenset({"task_space_goal"}),
        )
        self.observation = TrackingObservation(0.0, (0.0, 0.0, 0.0))

    def test_pid_applies_proportional_correction_to_task_goal(self) -> None:
        controller = TaskSpacePIDController(
            kp=(0.5, 0.25, 0.1),
            ki=(0.0, 0.0, 0.0),
            kd=(0.0, 0.0, 0.0),
            max_correction_mm=100.0,
        )
        controller.reset(self.context)
        output = controller.compute(
            self.observation,
            TrajectoryReference(0.1, (10.0, -4.0, 5.0), phase="tracking"),
            0.1,
        )
        self.assertIsInstance(output.command, TaskSpaceGoalCommand)
        self.assertEqual(output.command.position_mm, (15.0, -5.0, 5.5))
        self.assertAlmostEqual(output.diagnostics["pid_error_norm_mm"], 11.874342087)
        controller.finalize()

    def test_integral_is_clamped_and_phase_change_resets_derivative_and_integral(self) -> None:
        controller = TaskSpacePIDController(
            kp=(0.0, 0.0, 0.0),
            ki=(1.0, 1.0, 1.0),
            kd=(1.0, 1.0, 1.0),
            integral_limit_mm_s=(0.2, 0.2, 0.2),
            max_correction_mm=100.0,
        )
        controller.reset(self.context)
        first = controller.compute(
            self.observation,
            TrajectoryReference(0.1, (1.0, 0.0, 0.0), phase="settle"),
            0.1,
        )
        second = controller.compute(
            self.observation,
            TrajectoryReference(0.2, (1.0, 0.0, 0.0), phase="settle"),
            0.1,
        )
        tracking = controller.compute(
            self.observation,
            TrajectoryReference(0.3, (1.0, 0.0, 0.0), phase="tracking"),
            0.1,
        )
        self.assertEqual(first.diagnostics["pid_derivative_norm_mm_s"], 0.0)
        self.assertLessEqual(second.diagnostics["pid_integral_norm_mm_s"], 0.2)
        self.assertEqual(tracking.diagnostics["pid_integral_norm_mm_s"], 0.0)
        self.assertEqual(tracking.diagnostics["pid_derivative_norm_mm_s"], 0.0)

    def test_pid_factory_reads_scalar_or_vector_gains(self) -> None:
        controller = controller_from_mapping(
            {
                "type": "task_space_pid",
                "kp": 0.3,
                "ki": [0.01, 0.02, 0.03],
                "kd": [0.0, 0.0, 0.0],
            }
        )
        self.assertIsInstance(controller, TaskSpacePIDController)
        self.assertEqual(controller.kp, (0.3, 0.3, 0.3))
        self.assertEqual(controller.ki, (0.01, 0.02, 0.03))

    def test_pid_rejects_backend_without_task_space_goals(self) -> None:
        controller = TaskSpacePIDController()
        with self.assertRaises(ValueError):
            controller.reset(
                ControllerContext(
                    dt_s=0.1,
                    cable_count=8,
                    supported_command_kinds=frozenset({"cable_displacement"}),
                )
            )


if __name__ == "__main__":
    unittest.main()
