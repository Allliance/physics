import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("evaluate.py")
SPEC = importlib.util.spec_from_file_location("scale_physics_evaluate", MODULE_PATH)
evaluate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = evaluate
SPEC.loader.exec_module(evaluate)


class EvaluationTests(unittest.TestCase):
    def test_sample_is_reproducible_and_without_replacement(self):
        rows = [{"id": index} for index in range(1000)]
        first = evaluate.select_rows(rows, 100, 5600)
        self.assertEqual(first, evaluate.select_rows(rows, 100, 5600))
        self.assertEqual(len({row["id"] for row in first}), 100)

    def test_sample_rejects_invalid_size(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            evaluate.select_rows([{"id": 1}], 2, 1)

    def test_judge_json_parser_accepts_fence(self):
        self.assertEqual(evaluate.parse_json_object(
            '```json\n{"correct": true, "reason": "ok"}\n```'),
            {"correct": True, "reason": "ok"})


if __name__ == "__main__":
    unittest.main()
