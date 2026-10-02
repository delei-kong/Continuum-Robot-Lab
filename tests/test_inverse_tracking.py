import unittest

from simulation.inverse_tracking import (
    InverseTargetSignal,
    InverseTrackingConfig,
    percentile,
    summarize_step_times,
)


class InverseTargetSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = InverseTrackingConfig(
            dt=0.04,
            control_rate_hz=25.0,
            start_target_mm=(0.0, -5.0, 185.0),
            target_mm=(20.0, -5.0, 180.0),
            settle_duration_s=1.0,
            transition_duration_s=2.0,
            hold_duration_s=5.0,
            deadline_ms=40.0,
            benchmark_warmup_steps=25,
        )
        self.signal = InverseTargetSignal(self.config)

    def test_schedule_has_200_steps_at_25_hz(self) -> None:
        self.assertEqual(self.signal.total_steps(), 200)

    def test_schedule_phases_and_linear_transition(self) -> None:
        self.assertEqual(self.signal.sample(0.96).phase, "settle")
        midpoint = self.signal.sample(2.0)
        self.assertEqual(midpoint.phase, "transition")
        self.assertEqual(midpoint.position_mm, (10.0, -5.0, 182.5))
        self.assertEqual(self.signal.sample(3.0).phase, "hold")
        self.assertEqual(self.signal.sample(3.0).position_mm, self.config.target_mm)

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


if __name__ == "__main__":
    unittest.main()
