import unittest

from simulation.forward_data import (
    CABLE_COUNT,
    CableActionSafetyLayer,
    ForwardDataConfig,
    MultiSineExcitation,
)


def make_config(**overrides: object) -> ForwardDataConfig:
    values: dict[str, object] = {
        "dt_s": 0.01,
        "duration_s": 10.0,
        "settle_duration_s": 1.0,
        "seed": 7,
        "cable_max_displacements_mm": (70.0,) * 4 + (40.0,) * 4,
        "max_command_delta_mm": 0.5,
        "excitation_amplitudes_mm": (6.0,) * 4 + (3.0,) * 4,
        "base_frequency_hz": 0.13,
        "frequency_step_hz": 0.03,
        "centerline_z_mm": (25.0, 85.0, 145.0, 195.0),
        "csv_flush_interval_steps": 25,
    }
    values.update(overrides)
    return ForwardDataConfig(**values)  # type: ignore[arg-type]


class ForwardDataConfigTest(unittest.TestCase):
    def test_configuration_derives_exact_episode_steps(self) -> None:
        self.assertEqual(make_config().total_steps, 1000)

    def test_configuration_rejects_non_integral_duration(self) -> None:
        with self.assertRaises(ValueError):
            make_config(duration_s=10.005)

    def test_configuration_rejects_excessive_amplitude(self) -> None:
        with self.assertRaises(ValueError):
            make_config(excitation_amplitudes_mm=(71.0,) + (1.0,) * (CABLE_COUNT - 1))


class CableActionSafetyLayerTest(unittest.TestCase):
    def test_project_limits_bounds_and_per_step_change(self) -> None:
        layer = CableActionSafetyLayer((2.0,) * CABLE_COUNT, 0.5)
        first = layer.project((5.0,) * CABLE_COUNT)
        self.assertEqual(first.applied_mm, (0.5,) * CABLE_COUNT)
        self.assertTrue(first.limited)
        second = layer.project((5.0,) * CABLE_COUNT)
        self.assertEqual(second.applied_mm, (1.0,) * CABLE_COUNT)
        for _ in range(3):
            final = layer.project((5.0,) * CABLE_COUNT)
        self.assertEqual(final.applied_mm, (2.0,) * CABLE_COUNT)

    def test_reset_returns_to_zero_action(self) -> None:
        layer = CableActionSafetyLayer((2.0,) * CABLE_COUNT, 1.0)
        layer.project((1.0,) * CABLE_COUNT)
        layer.reset()
        self.assertEqual(layer.current_mm, (0.0,) * CABLE_COUNT)


class MultiSineExcitationTest(unittest.TestCase):
    def test_settle_phase_is_zero_and_signal_is_seeded(self) -> None:
        config = make_config(seed=19)
        first = MultiSineExcitation(config)
        second = MultiSineExcitation(config)
        self.assertEqual(first.sample(0.5), ("settle", (0.0,) * CABLE_COUNT))
        self.assertEqual(first.sample(1.5), second.sample(1.5))

    def test_signal_remains_within_configured_amplitudes(self) -> None:
        config = make_config()
        _phase, commands = MultiSineExcitation(config).sample(4.0)
        self.assertEqual(len(commands), CABLE_COUNT)
        self.assertTrue(
            all(0.0 <= value <= maximum for value, maximum in zip(commands, config.excitation_amplitudes_mm))
        )


if __name__ == "__main__":
    unittest.main()
