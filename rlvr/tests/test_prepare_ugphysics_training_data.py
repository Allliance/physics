from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rlvr.prepare_ugphysics_training_data import collect_rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class PrepareUgphysicsTrainingDataTests(unittest.TestCase):
    def test_embedded_unicode_line_separator_is_not_a_record_boundary(self) -> None:
        from rlvr.prepare_ugphysics_training_data import _read_jsonl

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.jsonl"
            _write_jsonl(path, [{"problem": "before\u0085after"}])

            rows = _read_jsonl(path)

        self.assertEqual(rows, [{"problem": "before\u0085after"}])

    def test_combines_valid_seed_with_new_judge_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audit = root / "audit.jsonl"
            sample = root / "sample.jsonl"
            judgments = root / "judgments.jsonl"
            _write_jsonl(
                audit,
                [
                    {
                        "problem_id": "A/en/0",
                        "problem_statement": "p0",
                        "reference_solution": "r0",
                        "AI_audit": {"verdict": "grader_failure"},
                    },
                    {
                        "problem_id": "A/en/1",
                        "problem_statement": "p1",
                        "reference_solution": "r1",
                        "AI_audit": {"verdict": "benchmark_failure"},
                    },
                ],
            )
            _write_jsonl(
                sample,
                [
                    {"_eval_id": "A/en/0", "problem": "p0", "solution": "r0"},
                    {"_eval_id": "B/en/0", "problem": "p2", "solution": "r2"},
                    {"_eval_id": "B/en/1", "problem": "p3", "solution": "r3"},
                ],
            )
            _write_jsonl(
                judgments,
                [
                    {"uid": "B/en/0", "status": "completed", "grade": 1},
                    {"uid": "B/en/1", "status": "completed", "grade": 0},
                ],
            )

            rows, counts = collect_rows(audit, sample, judgments)

        self.assertEqual({item_id for item_id, _row in rows}, {"A/en/0", "B/en/0"})
        self.assertEqual(counts["seed_rows_kept"], 1)
        self.assertEqual(counts["seed_benchmark_failures_excluded"], 1)
        self.assertEqual(counts["new_rows_judged"], 2)
        self.assertEqual(counts["new_rows_kept"], 1)
        self.assertEqual(counts["new_rows_rejected"], 1)


if __name__ == "__main__":
    unittest.main()
