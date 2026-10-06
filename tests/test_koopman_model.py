"""Pure-Python checks for registered Koopman model fitting and evaluation."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import numpy as np

from modeling.koopman_dataset import ACTION_COLUMNS, STATE_COLUMNS
from modeling.koopman_model import (
    EvaluationConfig,
    KoopmanModelDefinition,
    RffCandidate,
    evaluate_model,
    fit_models,
    resolve_model_definition,
)


class KoopmanModelTest(unittest.TestCase):
    def _definition(self) -> KoopmanModelDefinition:
        return KoopmanModelDefinition(
            model_id="test_fixed_lift",
            dataset_id="koopman_v1",
            config_rel="configs/koopman_model_v1.json",
            minimum_scale=1e-6,
            baseline_ridge=1e-4,
            rff_candidates=(
                RffCandidate(name="edmd_rff", ridge=1e-4, feature_count=12, bandwidth=2.0, seed=17),
            ),
            evaluation=EvaluationConfig(
                rollout_horizons=(1, 4), rollout_start_stride=3, max_starts_per_episode=8
            ),
        )

    def _episode(self, count: int = 48) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        time = np.arange(count, dtype=np.float64)[:, None]
        state = np.concatenate(
            [np.sin(0.03 * time * (index + 1)) + 0.01 * index for index in range(len(STATE_COLUMNS))],
            axis=1,
        )
        action = np.concatenate(
            [np.cos(0.05 * time * (index + 1)) for index in range(len(ACTION_COLUMNS))], axis=1
        )
        action_effect = np.concatenate(
            [action[:, index % len(ACTION_COLUMNS) : (index % len(ACTION_COLUMNS)) + 1]
             for index in range(len(STATE_COLUMNS))],
            axis=1,
        )
        next_state = 0.97 * state + 0.02 * action_effect
        return state, action, next_state

    def test_models_fit_and_rollout_on_finite_registered_shapes(self) -> None:
        definition = self._definition()
        episode = self._episode()
        normalization, models = fit_models(definition, (episode,))

        self.assertEqual(set(models), {"linear_affine", "edmd_rff"})
        self.assertEqual(models["linear_affine"].lift.feature_dimension, len(STATE_COLUMNS))
        self.assertEqual(
            models["edmd_rff"].lift.feature_dimension, len(STATE_COLUMNS) + 12
        )
        prediction = models["edmd_rff"].predict_step(episode[0][:3], episode[1][:3])
        self.assertEqual(prediction.shape, (3, len(STATE_COLUMNS)))
        self.assertTrue(np.all(np.isfinite(prediction)))
        self.assertTrue(np.all(normalization.state_scale >= definition.minimum_scale))

        metrics = evaluate_model(models["edmd_rff"], (episode,), definition.evaluation)
        self.assertEqual(metrics["primary_horizon_steps"], 4)
        one_step = metrics["one_step"]
        primary = metrics["primary_rollout"]
        self.assertEqual(one_step["samples"], len(episode[0]))
        self.assertGreater(primary["samples"], 0)
        self.assertTrue(math.isfinite(float(primary["state_normalized_rmse"])))
        self.assertTrue(math.isfinite(float(primary["tip_rmse_mm"])))

    def test_rff_lift_is_deterministic_for_a_fixed_seed(self) -> None:
        definition = self._definition()
        episode = self._episode()
        _, first = fit_models(definition, (episode,))
        _, second = fit_models(definition, (episode,))
        self.assertTrue(
            np.array_equal(
                first["edmd_rff"].lift.frequencies, second["edmd_rff"].lift.frequencies
            )
        )
        self.assertTrue(
            np.array_equal(first["edmd_rff"].lift.phases, second["edmd_rff"].lift.phases)
        )

    def test_registered_v2_candidate_family_is_resolved_from_versioned_config(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        definition = resolve_model_definition(
            "koopman_v2_rff_candidates", "koopman_v1", project_root
        )
        self.assertEqual(
            tuple(candidate.name for candidate in definition.rff_candidates),
            ("edmd_rff_48_b1", "edmd_rff_96_b2", "edmd_rff_192_b3"),
        )
        self.assertEqual(definition.evaluation.rollout_horizons, (1, 10, 50, 100))


if __name__ == "__main__":
    unittest.main()
