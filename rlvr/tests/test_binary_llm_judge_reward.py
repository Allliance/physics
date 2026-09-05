from __future__ import annotations

import unittest
from unittest import mock

from rlvr import binary_llm_judge_reward as binary_reward


class BinaryLlmJudgeRewardTest(unittest.TestCase):
    def test_forces_binary_mode_for_training_rows(self) -> None:
        expected = {"score": 1.0, "acc": 1.0, "judge_error": 0.0}
        with mock.patch.object(
            binary_reward.llm_judge_reward, "compute_score", return_value=expected
        ) as compute_score:
            actual = binary_reward.compute_score(
                binary_reward.llm_judge_reward.PRISM_SOURCE,
                "candidate",
                {"problem": "p", "reference_answer": "r"},
                extra_info={"split": "train", "uid": "abc"},
                timeout_seconds=17,
            )

        self.assertEqual(actual, expected)
        self.assertEqual(compute_score.call_args.kwargs["extra_info"], {
            "split": "validation",
            "uid": "abc",
        })
        self.assertEqual(compute_score.call_args.kwargs["timeout_seconds"], 17)

    def test_does_not_mutate_extra_info(self) -> None:
        extra_info = {"split": "train"}
        with mock.patch.object(
            binary_reward.llm_judge_reward,
            "compute_score",
            return_value={"score": 0.0, "acc": 0.0, "judge_error": 0.0},
        ):
            binary_reward.compute_score(
                binary_reward.llm_judge_reward.PRISM_SOURCE,
                "candidate",
                {"problem": "p", "reference_answer": "r"},
                extra_info=extra_info,
            )
        self.assertEqual(extra_info, {"split": "train"})


if __name__ == "__main__":
    unittest.main()
