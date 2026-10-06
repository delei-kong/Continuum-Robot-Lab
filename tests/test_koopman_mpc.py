"""Pure-Python safety and persistence checks for constrained Koopman-MPC."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from control.koopman_mpc_controller import (
    KoopmanMpcConfig,
    KoopmanMpcController,
    koopman_state_from_observation,
)
from modeling.koopman_dataset import ACTION_COLUMNS, STATE_COLUMNS
from modeling.koopman_model import (
    FixedLift,
    Normalization,
    TrainedDynamicsModel,
    load_finalized_koopman_model,
)


class KoopmanMpcControllerTest(unittest.TestCase):
    def _model(self) -> TrainedDynamicsModel:
        state_dimension = len(STATE_COLUMNS)
        action_dimension = len(ACTION_COLUMNS)
        tip_x = STATE_COLUMNS.index("tip_x_mm")
        lift = FixedLift(
            kind="linear_affine",
            state_dimension=state_dimension,
            frequencies=np.empty((state_dimension, 0), dtype=np.float64),
            phases=np.empty((0,), dtype=np.float64),
        )
        normalization = Normalization(
            state_mean=np.zeros(state_dimension),
            state_scale=np.ones(state_dimension),
            action_mean=np.zeros(action_dimension),
            action_scale=np.ones(action_dimension),
        )
        action_transition = np.zeros((action_dimension, state_dimension), dtype=np.float64)
        action_transition[0, tip_x] = 1.0
        return TrainedDynamicsModel(
            name="synthetic_linear",
            lift=lift,
            normalization=normalization,
            lift_transition=np.eye(state_dimension),
            action_transition=action_transition,
            bias=np.zeros(state_dimension),
            ridge=1e-4,
        )

    def _config(self) -> KoopmanMpcConfig:
        return KoopmanMpcConfig(
            horizon_steps=4,
            tip_position_weights=(1.0, 1.0, 1.0),
            terminal_weight_scale=2.0,
            action_weight=0.01,
            action_delta_weight=0.1,
            projected_gradient_iterations=80,
            maximum_displacements_mm=(1.0,) * len(ACTION_COLUMNS),
            max_command_delta_mm=0.2,
        )

    def test_solver_tracks_the_reachable_axis_without_violating_bounds(self) -> None:
        controller = KoopmanMpcController(self._model(), self._config())
        controller.reset()
        state = np.zeros(len(STATE_COLUMNS), dtype=np.float64)
        references = ((5.0, 0.0, 0.0),) * 4
        first = controller.compute(state, references)
        self.assertGreater(first.action_mm[0], 0.0)
        self.assertLessEqual(first.action_mm[0], 0.2 + 1e-12)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in first.action_mm))
        self.assertLess(first.predicted_terminal_error_mm, 5.0)

        controller.commit_applied_action(first.action_mm)
        second = controller.compute(state, references)
        self.assertTrue(
            all(
                abs(current - previous) <= 0.2 + 1e-12
                for current, previous in zip(second.action_mm, first.action_mm)
            )
        )

    def test_live_observation_uses_the_dataset_centerline_column_order(self) -> None:
        state = koopman_state_from_observation(
            cable_displacements_mm=tuple(float(index) for index in range(8)),
            cable_forces=tuple(float(10 + index) for index in range(8)),
            tip_position_mm=(100.0, 101.0, 102.0),
            centerline_positions_mm=tuple(
                (float(1000 + index), float(2000 + index), float(3000 + index))
                for index in range(10)
            ),
            centerline_velocities_mm_s=tuple(
                (float(4000 + index), float(5000 + index), float(6000 + index))
                for index in range(10)
            ),
        )
        point = 4
        self.assertEqual(state[STATE_COLUMNS.index(f"centerline_{point}_x_mm")], 1000.0 + point)
        self.assertEqual(state[STATE_COLUMNS.index(f"centerline_{point}_y_mm")], 2000.0 + point)
        self.assertEqual(state[STATE_COLUMNS.index(f"centerline_{point}_z_mm")], 3000.0 + point)
        self.assertEqual(state[STATE_COLUMNS.index(f"centerline_{point}_vx_mm_s")], 4000.0 + point)
        self.assertEqual(state[STATE_COLUMNS.index(f"centerline_{point}_vy_mm_s")], 5000.0 + point)
        self.assertEqual(state[STATE_COLUMNS.index(f"centerline_{point}_vz_mm_s")], 6000.0 + point)

    def test_final_model_loader_uses_the_validation_selected_candidate(self) -> None:
        model = self._model()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "outputs" / "koopman_models" / "final_v1"
            output_dir.mkdir(parents=True)
            (output_dir / "COMPLETE").touch()
            (output_dir / "selection.json").write_text(
                json.dumps(
                    {"evaluation_stage": "validation", "selected_by_validation": model.name}
                ),
                encoding="utf-8",
            )
            (output_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "evaluation_stage": "final",
                        "test_evaluated": True,
                        "selected_by_validation": model.name,
                        "models": {
                            model.name: {"lift": "linear_affine", "ridge": model.ridge}
                        },
                    }
                ),
                encoding="utf-8",
            )
            np.savez_compressed(
                output_dir / "models.npz",
                state_mean=model.normalization.state_mean,
                state_scale=model.normalization.state_scale,
                action_mean=model.normalization.action_mean,
                action_scale=model.normalization.action_scale,
                **model.to_npz(model.name),
            )
            loaded = load_finalized_koopman_model(root, "final_v1")
        self.assertEqual(loaded.name, model.name)
        self.assertEqual(loaded.lift.kind, "linear_affine")
        self.assertTrue(np.array_equal(loaded.action_transition, model.action_transition))


if __name__ == "__main__":
    unittest.main()
