import unittest
from math import dist, sqrt

from simulation.inverse_tracking import (
    InverseTargetSignal,
    InverseTrackingConfig,
    PeriodicRandomTargetSignal,
    PeriodicRandomTrackingConfig,
    crosshair_marker_geometry,
    generate_random_waypoints,
    octahedron_marker_geometry,
    percentile,
    summarize_step_times,
    translate_marker,
)


class InverseTargetSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = InverseTrackingConfig(
            dt=0.04,
            control_rate_hz=25.0,
            start_target_mm=(0.0, -5.0, 185.0),
            target_mm=(65.0, -25.0, 145.0),
            settle_duration_s=1.0,
            transition_duration_s=5.0,
            hold_duration_s=2.0,
            deadline_ms=40.0,
            benchmark_warmup_steps=25,
        )
        self.signal = InverseTargetSignal(self.config)

    def test_schedule_has_200_steps_at_25_hz(self) -> None:
        self.assertEqual(self.signal.total_steps(), 200)

    def test_schedule_phases_and_linear_transition(self) -> None:
        self.assertEqual(self.signal.sample(0.96).phase, "settle")
        midpoint = self.signal.sample(3.5)
        self.assertEqual(midpoint.phase, "transition")
        self.assertEqual(midpoint.position_mm, (32.5, -15.0, 165.0))
        self.assertEqual(self.signal.sample(6.0).phase, "hold")
        self.assertEqual(self.signal.sample(6.0).position_mm, self.config.target_mm)

    def test_rate_must_match_step_period(self) -> None:
        with self.assertRaises(ValueError):
            InverseTrackingConfig(
                0.01,
                25.0,
                (0.0, 0.0, 195.0),
                (20.0, 0.0, 190.0),
                1.0,
                2.0,
                5.0,
                40.0,
                25,
            )

    def test_timing_summary_excludes_warmup_and_checks_p99(self) -> None:
        summary = summarize_step_times([100.0, 10.0, 20.0, 30.0, 40.0], 40.0, 1)
        self.assertEqual(summary["measured_steps"], 4)
        self.assertEqual(summary["deadline_misses"], 0)
        self.assertTrue(summary["p99_deadline_met"])
        self.assertAlmostEqual(percentile([10.0, 20.0, 30.0], 0.5), 20.0)

    def test_target_marker_geometry_and_translation(self) -> None:
        vertices, triangles, edges = octahedron_marker_geometry(6.0)
        crosshair, crosshair_edges = crosshair_marker_geometry(9.0)
        self.assertEqual((len(vertices), len(triangles), len(edges)), (6, 8, 12))
        self.assertEqual((len(crosshair), len(crosshair_edges)), (6, 3))
        translated = translate_marker(vertices, (20.0, -5.0, 180.0))
        self.assertEqual(translated[0], [26.0, -5.0, 180.0])
        self.assertEqual(translated[4], [20.0, -5.0, 186.0])

    def test_target_marker_rejects_invalid_size(self) -> None:
        with self.assertRaises(ValueError):
            octahedron_marker_geometry(0.0)
        with self.assertRaises(ValueError):
            crosshair_marker_geometry(float("nan"))


class PeriodicRandomTargetSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = PeriodicRandomTrackingConfig(
            dt=0.04,
            control_rate_hz=25.0,
            start_target_mm=(0.0, 0.0, 180.0),
            random_seed=7,
            waypoint_count=2,
            cycle_count=2,
            workspace_bounds_mm=((-70.0, 70.0), (-60.0, 30.0), (145.0, 170.0)),
            min_start_distance_mm=20.0,
            min_waypoint_separation_mm=20.0,
            min_base_distance_mm=140.0,
            max_base_distance_mm=195.0,
            settle_duration_s=1.0,
            transition_duration_s=2.0,
            hold_duration_s=1.0,
            deadline_ms=40.0,
            benchmark_warmup_steps=25,
            max_generation_attempts=1000,
        )
        self.waypoints = ((30.0, 0.0, 170.0), (-30.0, 0.0, 170.0))
        self.signal = PeriodicRandomTargetSignal(self.config, self.waypoints)

    def test_periodic_schedule_repeats_waypoints(self) -> None:
        self.assertEqual(self.signal.total_steps(), 325)
        self.assertEqual(self.signal.sample(0.5).phase, "settle")
        first_midpoint = self.signal.sample(2.0)
        self.assertEqual(first_midpoint.position_mm, (15.0, 0.0, 175.0))
        self.assertEqual((first_midpoint.cycle_index, first_midpoint.waypoint_index), (0, 0))
        first_hold = self.signal.sample(3.0)
        self.assertEqual(first_hold.phase, "hold")
        self.assertEqual(first_hold.position_mm, self.waypoints[0])
        second_cycle_start = self.signal.sample(7.0)
        self.assertEqual((second_cycle_start.cycle_index, second_cycle_start.waypoint_index), (1, 0))
        self.assertEqual(second_cycle_start.position_mm, self.waypoints[1])

    def test_random_waypoints_are_deterministic_and_constrained(self) -> None:
        first = generate_random_waypoints(self.config)
        second = generate_random_waypoints(self.config)
        self.assertEqual(first, second)
        self.assertEqual(len(first), self.config.waypoint_count)
        for point in first:
            self.assertGreaterEqual(dist(point, self.config.start_target_mm), 20.0)
            self.assertGreaterEqual(sqrt(sum(axis * axis for axis in point)), 140.0)
            self.assertLessEqual(sqrt(sum(axis * axis for axis in point)), 195.0)
        self.assertGreaterEqual(dist(first[0], first[1]), 20.0)

    def test_random_waypoint_generation_rejects_impossible_constraints(self) -> None:
        impossible = PeriodicRandomTrackingConfig(
            **{
                **self.config.__dict__,
                "min_waypoint_separation_mm": 1000.0,
                "max_generation_attempts": 10,
            }
        )
        with self.assertRaises(ValueError):
            generate_random_waypoints(impossible)


if __name__ == "__main__":
    unittest.main()
