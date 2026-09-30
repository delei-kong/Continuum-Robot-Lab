import math
import unittest

from simulation.cyclic_control import CyclicControlConfig, CyclicControlSignal


class CyclicControlSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        config = CyclicControlConfig(
            amplitude_mm=20.0,
            period_s=4.0,
            settle_duration_s=1.0,
            cycles=3,
            release_duration_s=1.0,
            max_displacement_mm=70.0,
        )
        self.signal = CyclicControlSignal(config)

    def test_schedule_has_1400_steps(self) -> None:
        self.assertEqual(self.signal.config.total_duration_s, 14.0)
        self.assertEqual(self.signal.total_steps(0.01), 1400)

    def test_phase_boundaries(self) -> None:
        self.assertEqual(self.signal.sample(0.99).phase, "settle")
        self.assertEqual(self.signal.sample(1.0).phase, "cycle")
        self.assertEqual(self.signal.sample(12.99).phase, "cycle")
        self.assertEqual(self.signal.sample(13.0).phase, "release")

    def test_each_cycle_moves_from_zero_to_twenty_and_back(self) -> None:
        for cycle_index in range(3):
            start = 1.0 + cycle_index * 4.0
            self.assertAlmostEqual(self.signal.sample(start).displacement_mm, 0.0)
            self.assertAlmostEqual(self.signal.sample(start + 2.0).displacement_mm, 20.0)
            self.assertAlmostEqual(self.signal.sample(start + 4.0 - 1e-9).displacement_mm, 0.0)

    def test_intermediate_value_matches_formula(self) -> None:
        time_s = 2.25
        expected = 10.0 * (1.0 - math.cos(2.0 * math.pi * 1.25 / 4.0))
        self.assertAlmostEqual(self.signal.sample(time_s).displacement_mm, expected)

    def test_command_is_limited(self) -> None:
        limited = CyclicControlSignal(
            CyclicControlConfig(
                amplitude_mm=80.0,
                period_s=4.0,
                settle_duration_s=1.0,
                cycles=1,
                release_duration_s=1.0,
                max_displacement_mm=70.0,
            )
        )
        self.assertEqual(limited.sample(3.0).displacement_mm, 70.0)

    def test_invalid_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CyclicControlConfig(20.0, 0.0, 1.0, 3, 1.0, 70.0)
        with self.assertRaises(ValueError):
            self.signal.total_steps(0.03)


if __name__ == "__main__":
    unittest.main()
