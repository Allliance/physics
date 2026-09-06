import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "aggregate_original_challenges.py"
SPEC = importlib.util.spec_from_file_location("aggregate_original_challenges", SCRIPT)
aggregate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aggregate)


class OriginalChallengesTests(unittest.TestCase):
    def test_challenge_zero_uses_original_json_prompt_and_template(self):
        record = aggregate.build_example_record()
        source = aggregate.DATA_DIR / "example_challenges/json/quantum_error_correction_main.json"
        problem = json.loads(source.read_text())["problems"][0]
        self.assertEqual(record["challenge_id"], "Challenge_0")
        self.assertEqual(record["problem_id"], "Challenge_0_main")
        self.assertEqual(record["problem_description"], problem["problem_description"])
        self.assertEqual(record["code_template"], problem["code_template"])
        self.assertEqual(record["problem_setup"], problem["metadata"]["problem_setup"])

    def test_aggregate_contains_zero_through_seventy_and_all_notebooks(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(aggregate, "OUTPUT_DIR", Path(directory)), contextlib.redirect_stdout(io.StringIO()):
                aggregate.main()
            records = [json.loads(line) for line in
                       (Path(directory) / "original_challenges.jsonl").read_text().splitlines()]
        self.assertEqual([r["challenge_id"] for r in records], [f"Challenge_{i}" for i in range(71)])
        self.assertEqual(sum(r["split"] == "example" for r in records), 1)
        for record in records:
            self.assertEqual(list(record), list(records[1]))
            self.assertEqual([type(value) for value in record.values()],
                             [type(value) for value in records[1].values()])
        sources = [source for r in records for source in [r, *r["alternate_sources"]]]
        self.assertEqual(len({s["source_notebook"] for s in sources}), 72)


if __name__ == "__main__":
    unittest.main()
