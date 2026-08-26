import tempfile
import unittest
from pathlib import Path

import evaluate


class EvaluateTest(unittest.TestCase):
    def test_load_physics_filters_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "olympiad.jsonl"
            path.write_text('{"subject":"physics","task_group_id":"p"}\n{"subject":"biology","task_group_id":"b"}\n')
            self.assertEqual(["p"], [r["task_group_id"] for r in evaluate.load_physics(Path(directory), "olympiad")])

    def test_load_physics_disambiguates_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.jsonl"
            path.write_text('{"subject":"physics","task_group_id":"p"}\n{"subject":"physics","task_group_id":"p"}\n')
            self.assertEqual(
                ["p", "p:duplicate:2"],
                [r["_eval_id"] for r in evaluate.load_physics(Path(directory), "research")],
            )

    def test_summary_uses_research_threshold(self):
        config = evaluate.Config("m", "high", "j", "high", 1)
        judgments = [
            {"track": "olympiad", "score": 1, "success": True},
            {"track": "research", "score": 7, "success": True},
            {"track": "research", "score": 6.5, "success": False},
        ]
        summary = evaluate.summarize([], judgments, config)
        self.assertEqual(0.5, summary["tracks"]["research"]["accuracy"])
        self.assertEqual(6.75, summary["tracks"]["research"]["mean_rubric_score"])


if __name__ == "__main__":
    unittest.main()
