from __future__ import annotations

import json
import unittest
from unittest import mock

from rlvr import reward


class RewardTests(unittest.TestCase):
    def test_prism_nonforking_match_and_dependency_propagation(self) -> None:
        standard = [
            {"index": 1, "formula": "$$x=1$$", "dependency": []},
            {"index": 2, "formula": "$$y=2$$", "dependency": [1], "is_final_answer": True},
        ]

        def compare_formula(expected: str, actual: str, **_kwargs):
            return expected == actual, "exact"

        tools = (lambda _solution: ["y=2"], lambda _formula: 0.0, compare_formula)
        with mock.patch.object(reward, "_load_prism_tools", return_value=tools):
            process_score, final_score = reward._prism_components(
                "$$y=2$$", {"grading_standard": standard}
            )
        self.assertEqual(process_score, 1.0)
        self.assertEqual(final_score, 1.0)

    def test_prism_shaping_and_metrics(self) -> None:
        with mock.patch.dict("os.environ", {"RLVR_PRISM_ISOLATE": "0"}), mock.patch.object(
            reward, "_prism_components", return_value=(0.5, 1.0)
        ):
            result = reward.compute_score(
                reward.PRISM_SOURCE,
                "Reasoning. $$E = mc^2$$",
                json.dumps({"grading_standard": []}),
            )
        self.assertAlmostEqual(result["score"], 0.885)
        self.assertEqual(result["acc"], 1.0)
        self.assertEqual(result["format_score"], 1.0)
        self.assertEqual(result["reward_timeout"], 0.0)
        self.assertEqual(result["reward_resource_limit"], 0.0)
        self.assertEqual(result["reward_error"], 0.0)

    def test_prism_uses_isolated_worker_by_default(self) -> None:
        expected = {"score": 0.25, "acc": 0.0, "format_score": 1.0}
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
            reward, "_score_prism_isolated", return_value=expected
        ) as isolated:
            result = reward.compute_score(
                reward.PRISM_SOURCE,
                "$$x=1$$",
                json.dumps({"grading_standard": []}),
                timeout_seconds=7,
            )
        self.assertEqual(result, expected)
        isolated.assert_called_once_with("$$x=1$$", {"grading_standard": []}, 7)

    def test_prism_failures_have_the_same_metric_schema(self) -> None:
        success = reward.score_prism
        with mock.patch.object(reward, "_prism_components", return_value=(0.0, 0.0)):
            success_keys = set(success("$$x=0$$", {"grading_standard": []}))
        for metric in ("reward_timeout", "reward_resource_limit", "reward_error"):
            failure = reward._isolated_prism_failure(metric)
            self.assertEqual(set(failure), success_keys)
            self.assertEqual(failure[metric], 1.0)

    def test_ugphysics_binary_reward_and_format_floor(self) -> None:
        judger = mock.Mock()
        judger.auto_judge.return_value = False
        with mock.patch.dict("os.environ", {"RLVR_UGPHYSICS_ISOLATE": "0"}), mock.patch.object(
            reward, "_load_ugphysics_judger", return_value=judger
        ):
            result = reward.compute_score(
                reward.UGPHYSICS_SOURCE,
                r"So the final answer is \boxed{2}.",
                json.dumps({"answers": r"\boxed{3}"}),
            )
        self.assertEqual(result["score"], 0.05)
        self.assertEqual(result["acc"], 0.0)
        judger.auto_judge.assert_called_once()

    def test_ugphysics_accepts_a_worked_reference_answer(self) -> None:
        judger = mock.Mock()
        judger.auto_judge.return_value = True
        reference = r"The result follows from conservation. \\boxed{3}"
        with mock.patch.dict("os.environ", {"RLVR_UGPHYSICS_ISOLATE": "0"}), mock.patch.object(
            reward, "_load_ugphysics_judger", return_value=judger
        ):
            result = reward.compute_score(
                reward.UGPHYSICS_SOURCE,
                r"\\boxed{3}",
                json.dumps({"reference_answer": reference}),
            )
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["acc"], 1.0)
        judger.auto_judge.assert_called_once_with(r"\\boxed{3}", reference, precision=1e-2)

    def test_ugphysics_uses_isolated_worker_by_default(self) -> None:
        expected = {"score": 1.0, "acc": 1.0, "format_score": 1.0}
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
            reward, "_score_ugphysics_isolated", return_value=expected
        ) as isolated:
            result = reward.compute_score(
                reward.UGPHYSICS_SOURCE,
                r"\\boxed{3}",
                json.dumps({"reference_answer": r"\\boxed{3}"}),
                timeout_seconds=7,
            )
        self.assertEqual(result, expected)
        isolated.assert_called_once_with(
            r"\\boxed{3}", {"reference_answer": r"\\boxed{3}"}, 7
        )

    def test_bad_ground_truth_fails_closed(self) -> None:
        result = reward.compute_score(reward.PRISM_SOURCE, "answer", "not-json")
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["reward_error"], 1.0)

    def test_unknown_source_fails_closed(self) -> None:
        result = reward.compute_score("unknown", "answer", "{}")
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["reward_error"], 1.0)


if __name__ == "__main__":
    unittest.main()
