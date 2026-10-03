import unittest
from math import sqrt
from pathlib import Path
from tempfile import TemporaryDirectory

from control.reference_controller import ReferenceGoalController, controller_from_mapping
from control.tracking_contracts import (
    CableDisplacementCommand,
    ControlCommand,
    ControllerContext,
    ControllerOutput,
    TaskSpaceGoalCommand,
    TrackingObservation,
    TrajectoryReference,
)
from evaluation.recording import InMemoryTrackingRecorder
from evaluation.tracking_metrics import summarize_tracking_records, write_tracking_artifacts
from simulation.tracking_pipeline import (
    TrackingExperimentConfig,
    TrackingExperimentRunner,
)
from simulation.trajectory import (
    LinearTrajectory,
    PeriodicEllipseTrajectory,
    TimedLinearTrajectory,
    polyline_tube_geometry,
    sample_trajectory_polyline,
    trajectory_from_mapping,
)


class ExactTaskSpaceBackend:
    """A deterministic fake plant that reaches every task-space goal in one step."""

    def __init__(self, dt_s: float) -> None:
        self._context = ControllerContext(dt_s, 8, frozenset({"task_space_goal"}))
        self._observation = TrackingObservation(0.0, (0.0, 0.0, 0.0), (0.0,) * 8)
        self.closed = False

    @property
    def controller_context(self) -> ControllerContext:
        return self._context

    def reset(self, seed: int) -> TrackingObservation:
        self.closed = False
        self._observation = TrackingObservation(0.0, (0.0, 0.0, 0.0), (0.0,) * 8)
        return self._observation

    def step(self, command: ControlCommand, dt_s: float) -> TrackingObservation:
        if not isinstance(command, TaskSpaceGoalCommand):
            raise TypeError("fake backend accepts only task-space goals")
        self._observation = TrackingObservation(
            self._observation.time_s + dt_s,
            command.position_mm,
            (0.0,) * 8,
        )
        return self._observation

    def close(self) -> None:
        self.closed = True


class HoldTrajectory:
    duration_s = 0.08

    def reset(self, seed: int) -> None:
        self.seed = seed

    def sample(self, time_s: float) -> TrajectoryReference:
        return TrajectoryReference(time_s, (2.0, 0.0, 0.0), phase="hold")


class BiasedGoalController:
    def reset(self, context: ControllerContext) -> None:
        self.ready = True

    def compute(
        self,
        observation: TrackingObservation,
        reference: TrajectoryReference,
        dt_s: float,
    ) -> ControllerOutput:
        if not self.ready:
            raise RuntimeError("controller is not ready")
        goal = (reference.position_mm[0] + 1.0, *reference.position_mm[1:])
        return ControllerOutput(TaskSpaceGoalCommand(goal))

    def finalize(self) -> None:
        self.ready = False


class TrackingContractsTest(unittest.TestCase):
    def test_linear_trajectory_exposes_position_and_velocity(self) -> None:
        trajectory = LinearTrajectory((0.0, 0.0, 0.0), (10.0, -5.0, 20.0), 2.0)
        midpoint = trajectory.sample(1.0)
        self.assertEqual(midpoint.position_mm, (5.0, -2.5, 10.0))
        self.assertEqual(midpoint.velocity_mm_s, (5.0, -2.5, 10.0))
        endpoint = trajectory.sample(2.0)
        self.assertEqual(endpoint.position_mm, (10.0, -5.0, 20.0))
        self.assertEqual(endpoint.phase, "hold")

    def test_commands_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            TaskSpaceGoalCommand((float("nan"), 0.0, 0.0))
        with self.assertRaises(ValueError):
            CableDisplacementCommand(())

    def test_factories_reject_unknown_plugins(self) -> None:
        with self.assertRaises(ValueError):
            trajectory_from_mapping({"type": "unknown"})
        with self.assertRaises(ValueError):
            controller_from_mapping({"type": "sofa_inverse_qp"})

    def test_reference_goal_controller_factory(self) -> None:
        controller = controller_from_mapping({"type": "reference_goal"})
        self.assertIsInstance(controller, ReferenceGoalController)

    def test_linear_trajectory_factory(self) -> None:
        trajectory = trajectory_from_mapping(
            {
                "type": "linear",
                "start_mm": [0.0, 0.0, 0.0],
                "end_mm": [4.0, 2.0, 0.0],
                "duration_s": 2.0,
            }
        )
        self.assertEqual(trajectory.sample(1.0).position_mm, (2.0, 1.0, 0.0))

    def test_timed_linear_trajectory_has_explicit_phases(self) -> None:
        trajectory = TimedLinearTrajectory(
            (0.0, 0.0, 0.0), (10.0, -5.0, 0.0), 1.0, 2.0, 1.0
        )
        self.assertEqual(trajectory.duration_s, 4.0)
        self.assertEqual(trajectory.sample(0.5).phase, "settle")
        midpoint = trajectory.sample(2.0)
        self.assertEqual(midpoint.position_mm, (5.0, -2.5, 0.0))
        self.assertEqual(midpoint.velocity_mm_s, (5.0, -2.5, 0.0))
        self.assertEqual(trajectory.sample(3.5).phase, "hold")

    def test_periodic_ellipse_exposes_phases_and_derivatives(self) -> None:
        trajectory = PeriodicEllipseTrajectory(
            center_mm=(10.0, 20.0, 30.0),
            axis_cos_mm=(4.0, 0.0, 0.0),
            axis_sin_mm=(0.0, 2.0, 0.0),
            settle_duration_s=1.0,
            cycle_duration_s=4.0,
            cycle_count=1,
            hold_duration_s=1.0,
        )
        self.assertEqual(trajectory.start_mm, (14.0, 20.0, 30.0))
        self.assertEqual(trajectory.sample(0.5).phase, "settle")
        quarter = trajectory.sample(2.0)
        self.assertAlmostEqual(quarter.position_mm[0], 10.0)
        self.assertAlmostEqual(quarter.position_mm[1], 22.0)
        self.assertAlmostEqual(quarter.velocity_mm_s[0], -2.0 * 3.141592653589793)
        self.assertAlmostEqual(quarter.velocity_mm_s[1], 0.0, places=12)
        self.assertIsNotNone(quarter.acceleration_mm_s2)
        self.assertEqual(quarter.phase, "tracking")
        self.assertEqual(quarter.cycle_index, 0)
        self.assertEqual(trajectory.sample(5.5).position_mm, trajectory.start_mm)
        self.assertEqual(trajectory.sample(5.5).phase, "hold")

    def test_periodic_ellipse_factory(self) -> None:
        trajectory = trajectory_from_mapping(
            {
                "type": "periodic_ellipse",
                "center_mm": [10.0, 20.0, 30.0],
                "axis_cos_mm": [4.0, 0.0, 0.0],
                "axis_sin_mm": [0.0, 2.0, 0.0],
                "settle_duration_s": 1.0,
                "cycle_duration_s": 4.0,
                "cycle_count": 2,
                "hold_duration_s": 1.0,
            }
        )
        self.assertEqual(trajectory.duration_s, 10.0)
        self.assertEqual(trajectory.sample(5.5).cycle_index, 1)

    def test_trajectory_polyline_samples_reference_and_edges(self) -> None:
        trajectory = LinearTrajectory((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0)
        positions, edges = sample_trajectory_polyline(trajectory, 3)
        self.assertEqual(positions, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
        self.assertEqual(edges, [[0, 1], [1, 2]])

    def test_polyline_tube_skips_duplicate_points(self) -> None:
        vertices, quads = polyline_tube_geometry(
            [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 2.0)],
            radius_mm=0.5,
            radial_segments=4,
        )
        self.assertEqual(len(vertices), 8)
        self.assertEqual(len(quads), 4)
        radii = [sqrt(vertex[0] ** 2 + vertex[1] ** 2) for vertex in vertices]
        self.assertTrue(all(abs(radius - 0.5) < 1e-9 for radius in radii))

    def test_pipeline_composes_independent_components(self) -> None:
        backend = ExactTaskSpaceBackend(0.04)
        recorder = InMemoryTrackingRecorder()
        runner = TrackingExperimentRunner(
            trajectory=LinearTrajectory((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), 0.20),
            controller=ReferenceGoalController(),
            backend=backend,
            recorder=recorder,
        )
        records = runner.run(TrackingExperimentConfig(0.04, 0.20, 123))
        self.assertEqual(len(records), 5)
        self.assertEqual(records[-1].time_s, 0.20)
        self.assertEqual(records[-1].reference.position_mm, (10.0, 0.0, 0.0))
        self.assertEqual(records[-1].observation.tip_position_mm, (10.0, 0.0, 0.0))
        self.assertTrue(all(record.tracking_error_norm_mm == 0.0 for record in records))
        self.assertTrue(backend.closed)

    def test_pipeline_rejects_dt_and_duration_mismatches(self) -> None:
        backend = ExactTaskSpaceBackend(0.04)
        runner = TrackingExperimentRunner(
            trajectory=LinearTrajectory((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1.0),
            controller=ReferenceGoalController(),
            backend=backend,
            recorder=InMemoryTrackingRecorder(),
        )
        with self.assertRaises(ValueError):
            runner.run(TrackingExperimentConfig(0.02, 1.0, 1))
        with self.assertRaises(ValueError):
            runner.run(TrackingExperimentConfig(0.04, 1.2, 1))

    def test_pipeline_accepts_replacement_trajectory_and_controller(self) -> None:
        runner = TrackingExperimentRunner(
            trajectory=HoldTrajectory(),
            controller=BiasedGoalController(),
            backend=ExactTaskSpaceBackend(0.04),
            recorder=InMemoryTrackingRecorder(),
        )
        records = runner.run(TrackingExperimentConfig(0.04, 0.08, 99))
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record.tracking_error_norm_mm == 1.0 for record in records))

    def test_metrics_and_artifacts_are_independent_from_backend(self) -> None:
        runner = TrackingExperimentRunner(
            trajectory=LinearTrajectory((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 0.08),
            controller=ReferenceGoalController(),
            backend=ExactTaskSpaceBackend(0.04),
            recorder=InMemoryTrackingRecorder(),
        )
        records = runner.run(TrackingExperimentConfig(0.04, 0.08, 5))
        summary = summarize_tracking_records(records, deadline_ms=40.0, warmup_steps=0)
        self.assertEqual(summary["tracking"]["rmse_norm_mm"], 0.0)
        self.assertEqual(summary["tracking"]["all_steps"]["rmse_norm_mm"], 0.0)
        self.assertIn("transition", summary["tracking"]["by_phase"])
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            write_tracking_artifacts(
                run_dir,
                records,
                deadline_ms=40.0,
                warmup_steps=0,
            )
            self.assertTrue((run_dir / "trajectory.csv").is_file())
            self.assertTrue((run_dir / "performance.json").is_file())


if __name__ == "__main__":
    unittest.main()
