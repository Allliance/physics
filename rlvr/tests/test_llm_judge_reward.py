from __future__ import annotations

import json
import unittest
from unittest import mock

from rlvr import llm_judge_reward as reward


class LLMJudgeRewardTests(unittest.TestCase):
    def test_probability_weighted_reward(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "score_probabilities": [0.0, 0.0, 0.1, 0.2, 0.7],
                                "candidate_conclusion": "x=1",
                                "reference_conclusion": "x=1",
                                "completion": "complete",
                                "error_severity": "none",
                                "critique": "Correct.",
                            }
                        )
                    }
                }
            ]
        }
        result = reward._score_rubric_response(response)
        self.assertAlmostEqual(result["score"], 0.9)
        self.assertAlmostEqual(result["rubric_soft_pass_probability"], 0.9)
        self.assertEqual(result["judge_error"], 0.0)

    def test_probabilities_are_normalized(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_conclusion":"x=1","reference_conclusion":"x=1","completion":"complete","error_severity":"none","score_probabilities":[0,0,0,1,1],"critique":"Minor uncertainty."}'
                    }
                }
            ]
        }
        result = reward._score_rubric_response(response)
        self.assertAlmostEqual(result["score"], 0.875)
        self.assertEqual(result["rubric_soft_pass_probability"], 1.0)

    def test_compute_score_builds_external_request(self) -> None:
        api_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_conclusion":"x=1","reference_conclusion":"x=1","completion":"complete","error_severity":"none","score_probabilities":[0,0,0,0,1],"critique":"Correct."}'
                    }
                }
            ]
        }
        truth = json.dumps({"problem": "Find x.", "reference_answer": "x=1."})
        with mock.patch.object(reward, "_post_json", return_value=api_response) as post:
            result = reward.compute_score(reward.PRISM_SOURCE, "x=1", truth)
        self.assertEqual(result["score"], 1.0)
        body = json.loads(post.call_args.args[0])
        self.assertEqual(body["model"], "Qwen/Qwen3.5-27B")
        self.assertFalse(body["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(body["messages"][0]["content"], reward.RUBRIC_SYSTEM_PROMPT)
        self.assertIn("<candidate>\nx=1\n</candidate>", body["messages"][1]["content"])
        self.assertEqual(body["response_format"]["json_schema"], reward.RUBRIC_SCORE_SCHEMA)

    def test_validation_uses_default_binary_prompt_and_grade(self) -> None:
        api_response = {
            "choices": [
                {"message": {"content": '{"grade":1,"reason":"The result is correct."}'}}
            ]
        }
        truth = json.dumps({"problem": "Find x.", "reference_answer": "x=1."})
        with mock.patch.object(reward, "_post_json", return_value=api_response) as post:
            result = reward.compute_score(
                reward.PRISM_SOURCE,
                "x=1",
                truth,
                extra_info={"split": "validation"},
            )
        self.assertEqual(result, {"score": 1.0, "acc": 1.0, "judge_error": 0.0})
        body = json.loads(post.call_args.args[0])
        self.assertEqual(body["messages"][0]["content"], reward.BINARY_PROMPT.system)
        self.assertIn(
            "<candidate_response>\nx=1\n</candidate_response>",
            body["messages"][1]["content"],
        )
        self.assertEqual(body["response_format"]["json_schema"], reward.BINARY_SCORE_SCHEMA)
        self.assertEqual(body["max_tokens"], 8192)
        self.assertEqual(body["temperature"], 0.6)
        self.assertEqual(body["top_p"], 0.95)
        self.assertTrue(body["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(body["thinking_token_budget"], 4096)
        self.assertEqual(body["top_k"], 20)
        self.assertEqual(body["min_p"], 0.0)

    def test_ugphysics_validation_uses_binary_judge(self) -> None:
        api_response = {
            "choices": [
                {"message": {"content": '{"grade":1,"reason":"Correct."}'}}
            ]
        }
        truth = json.dumps(
            {"problem": "Find the speed.", "reference_answer": "The speed is 3 m/s."}
        )
        with mock.patch.object(reward, "_post_json", return_value=api_response) as post:
            result = reward.compute_score(
                reward.UGPHYSICS_SOURCE,
                "3 m/s",
                truth,
                extra_info={"split": "validation"},
            )
        self.assertEqual(result, {"score": 1.0, "acc": 1.0, "judge_error": 0.0})
        body = json.loads(post.call_args.args[0])
        self.assertEqual(body["messages"][0]["content"], reward.BINARY_PROMPT.system)

    def test_ugphysics_cannot_be_used_with_training_rubric(self) -> None:
        truth = json.dumps(
            {"problem": "Find the speed.", "reference_answer": "The speed is 3 m/s."}
        )
        with mock.patch.dict("os.environ", {"LLM_JUDGE_RAISE_ERRORS": "1"}):
            with self.assertRaisesRegex(ValueError, "only as binary validation"):
                reward.compute_score(reward.UGPHYSICS_SOURCE, "3 m/s", truth)

    def test_binary_grade_survives_malformed_free_text_reason(self) -> None:
        response = {
            "choices": [
                {"message": {"content": '{"grade":0,"reason":"bad\x01reason"}'}}
            ]
        }
        self.assertEqual(
            reward._score_binary_response(response),
            {"score": 0.0, "acc": 0.0, "judge_error": 0.0},
        )

    def test_malformed_response_fails_closed(self) -> None:
        truth = json.dumps({"problem": "Find x.", "reference_answer": "x=1."})
        with mock.patch.object(reward, "_post_json", return_value={"choices": []}):
            result = reward.compute_score(reward.PRISM_SOURCE, "x=1", truth)
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["judge_error"], 1.0)

    def test_semantically_invalid_response_is_retried(self) -> None:
        invalid = {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_conclusion":"","reference_conclusion":"x=1","completion":"partial","error_severity":"major","score_probabilities":[0,0,0,0,0],"critique":"Unsure."}'
                    }
                }
            ]
        }
        valid = {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_conclusion":"x=1","reference_conclusion":"x=1","completion":"complete","error_severity":"none","score_probabilities":[0,0,0,1,0],"critique":"Minor issue."}'
                    }
                }
            ]
        }
        truth = json.dumps({"problem": "Find x.", "reference_answer": "x=1."})
        with mock.patch.object(reward, "_post_json", side_effect=[invalid, valid]) as post:
            result = reward.compute_score(reward.PRISM_SOURCE, "x=1", truth)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["score"], 0.75)
        self.assertEqual(result["judge_error"], 0.0)

    def test_incomplete_label_caps_contradictory_full_credit(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_conclusion":"","reference_conclusion":"x=1",'
                        '"completion":"partial","error_severity":"major",'
                        '"score_probabilities":[0,0,0,0,1],"critique":"Stops early."}'
                    }
                }
            ]
        }
        result = reward._score_rubric_response(response)
        self.assertEqual(result["score"], 0.5)
        self.assertEqual(result["rubric_complete"], 0.0)
        self.assertEqual(result["rubric_major_error"], 1.0)


if __name__ == "__main__":
    unittest.main()
