from __future__ import annotations

import unittest
from unittest import mock

from rlvr import rule_train_binary_val_reward as hybrid


class RuleTrainBinaryValidationRewardTests(unittest.TestCase):
    def test_training_dispatches_to_native_reward(self) -> None:
        expected = {"score": 0.5}
        with mock.patch.object(hybrid.reward, "compute_score", return_value=expected) as native:
            result = hybrid.compute_score(
                hybrid.reward.PRISM_SOURCE, "answer", "truth", {"split": "train"}, 30
            )
        self.assertEqual(result, expected)
        native.assert_called_once()

    def test_validation_dispatches_to_binary_judge(self) -> None:
        expected = {"score": 1.0, "acc": 1.0, "judge_error": 0.0}
        with mock.patch.object(
            hybrid.llm_judge_reward, "compute_score", return_value=expected
        ) as judge:
            result = hybrid.compute_score(
                hybrid.llm_judge_reward.UGPHYSICS_SOURCE,
                "answer",
                "truth",
                {"split": "validation"},
                180,
            )
        self.assertEqual(result, expected)
        judge.assert_called_once()


if __name__ == "__main__":
    unittest.main()
