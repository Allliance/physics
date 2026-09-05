from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rlvr import prepare_data
from rlvr.prepare_data import _all_training, _split_exact


class PrepareDataTests(unittest.TestCase):
    def test_split_is_deterministic_and_disjoint(self) -> None:
        def rows():
            return [
                (str(index), {"extra_info": {"problem_id": str(index)}})
                for index in range(100)
            ]

        train_a, validation_a = _split_exact(rows(), 20, 7)
        train_b, validation_b = _split_exact(rows(), 20, 7)
        train_ids = {row["extra_info"]["problem_id"] for row in train_a}
        validation_ids = {row["extra_info"]["problem_id"] for row in validation_a}
        self.assertEqual(train_a, train_b)
        self.assertEqual(validation_a, validation_b)
        self.assertFalse(train_ids & validation_ids)
        self.assertEqual(len(train_ids | validation_ids), 100)
        self.assertEqual(len(validation_ids), 20)

    def test_all_training_keeps_every_row(self) -> None:
        rows = [
            (str(index), {"extra_info": {"problem_id": str(index)}})
            for index in range(10)
        ]
        train = _all_training(rows)
        self.assertEqual(len(train), 10)
        self.assertTrue(all(row["extra_info"]["split"] == "train" for row in train))

    def test_ugphysics_uses_audit_population_and_excludes_benchmark_failures(self) -> None:
        audited = [
            {
                "problem_id": "ClassicalMechanics/en/1",
                "problem_statement": "Good problem",
                "reference_solution": "Good reference",
                "AI_audit": {"verdict": "model_failure"},
            },
            {
                "problem_id": "QuantumMechanics/en/2",
                "problem_statement": "Broken problem",
                "reference_solution": "Broken reference",
                "AI_audit": {"verdict": "benchmark_failure"},
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            audit_root = Path(temporary)
            source = audit_root / "ugphysics" / "responses.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                "".join(json.dumps(row) + "\n" for row in audited), encoding="utf-8"
            )
            with mock.patch.object(prepare_data, "AUDIT_ROOT", audit_root):
                rows, counts = prepare_data._ugphysics_rows(exclude_failures=True)

        self.assertEqual(counts, {"audit_source": 2, "audited_failure": 1})
        self.assertEqual(len(rows), 1)
        item_id, row = rows[0]
        self.assertEqual(item_id, "ClassicalMechanics/en/1")
        self.assertEqual(row["prompt"][0]["content"], "Good problem")
        truth = json.loads(row["reward_model"]["ground_truth"])
        self.assertEqual(truth["reference_answer"], "Good reference")


if __name__ == "__main__":
    unittest.main()
