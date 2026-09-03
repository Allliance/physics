import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from llm_judge.eval import (
    AnthropicJudge,
    Completion,
    DEFAULT_DATASET,
    JUDGMENT_SCHEMA,
    JUDGMENT_SCHEMA_FINGERPRINT,
    RunConfig,
    classification_metrics,
    parse_judgment,
    read_jsonl,
    run_evaluation,
    select_rows,
    _anthropic_messages_url,
)
from llm_judge.prompts import PROMPTS, get_prompt


def sample_row(meta_eval_id="sample:0", final_grade=1):
    return {
        "meta_eval_id": meta_eval_id,
        "dataset": "sample",
        "source_index": 0,
        "problem_id": "problem-0",
        "problem_statement": "What is 1 + 1?",
        "reference_solution": "The answer is 2.",
        "model_response": "2",
        "final_grade": final_grade,
        "AI_audit": {"verdict": "grader_failure"},
    }


class FakeJudge:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def complete(self, system_prompt, user_prompt):
        self.calls += 1
        self.last_prompts = system_prompt, user_prompt
        return Completion(self.response, {"total_tokens": 10})


class PromptTests(unittest.TestCase):
    def test_only_default_prompt_is_available(self):
        self.assertEqual(set(PROMPTS), {"default"})
        with self.assertRaisesRegex(ValueError, "choose one of: default"):
            get_prompt("strict-reference")

    def test_prompt_does_not_leak_meta_evaluation_labels(self):
        system, user = get_prompt("default").render(sample_row())
        self.assertNotIn("final_grade", system + user)
        self.assertNotIn("AI_audit", system + user)
        self.assertIn("What is 1 + 1?", user)


class ParsingTests(unittest.TestCase):
    def test_schema_caps_reason_and_is_fingerprinted(self):
        self.assertEqual(JUDGMENT_SCHEMA["properties"]["reason"]["maxLength"], 1000)
        self.assertEqual(len(JUDGMENT_SCHEMA_FINGERPRINT), 12)

    def test_parse_plain_and_fenced_json(self):
        self.assertEqual(
            parse_judgment('{"grade": 1, "reason": "Equivalent."}'),
            (1, "Equivalent."),
        )
        self.assertEqual(
            parse_judgment('```json\n{"grade": 0, "reason": "Wrong."}\n```'),
            (0, "Wrong."),
        )

    def test_parse_rejects_nonbinary_or_empty_values(self):
        with self.assertRaisesRegex(ValueError, "integer 0 or 1"):
            parse_judgment('{"grade": true, "reason": "No."}')
        with self.assertRaisesRegex(ValueError, "non-empty"):
            parse_judgment('{"grade": 1, "reason": ""}')


class AnthropicTests(unittest.TestCase):
    def test_messages_url_accepts_root_v1_and_full_endpoint(self):
        self.assertEqual(
            _anthropic_messages_url("https://api.anthropic.com"),
            "https://api.anthropic.com/v1/messages",
        )
        self.assertEqual(
            _anthropic_messages_url("https://example.test/v1"),
            "https://example.test/v1/messages",
        )
        self.assertEqual(
            _anthropic_messages_url("https://example.test/v1/messages"),
            "https://example.test/v1/messages",
        )

    def test_request_body_uses_native_system_and_structured_output(self):
        client = AnthropicJudge(
            model="Claude Opus 5",
            base_url="https://example.test",
            api_key="secret",
            timeout=30,
            response_format="json-schema",
            max_tokens=2048,
        )
        body = client.request_body("system text", "user text")
        self.assertEqual(body["system"], "system text")
        self.assertEqual(body["messages"], [{"role": "user", "content": "user text"}])
        self.assertEqual(body["output_config"]["format"]["schema"], JUDGMENT_SCHEMA)
        self.assertNotIn("api_key", body)


class SelectionTests(unittest.TestCase):
    def test_filter_and_limit(self):
        first = sample_row("one:0")
        second = {**sample_row("two:0"), "dataset": "two"}
        self.assertEqual(select_rows([first, second], {"two"}, 1), [second])
        with self.assertRaisesRegex(ValueError, "unknown dataset"):
            select_rows([first], {"missing"}, None)

    def test_seeded_random_sample_is_reproducible(self):
        rows = [sample_row(f"sample:{index}") for index in range(20)]
        first = select_rows(rows, None, None, sample_size=6, sample_seed=123)
        repeated = select_rows(rows, None, None, sample_size=6, sample_seed=123)
        different = select_rows(rows, None, None, sample_size=6, sample_seed=456)
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, different)
        self.assertEqual(len(first), 6)
        self.assertEqual(
            [rows.index(row) for row in first],
            sorted(rows.index(row) for row in first),
        )

    def test_random_sample_validates_size_and_limit_exclusivity(self):
        rows = [sample_row(f"sample:{index}") for index in range(3)]
        with self.assertRaisesRegex(ValueError, "exceeds 3 available"):
            select_rows(rows, None, None, sample_size=4)
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            select_rows(rows, None, 1, sample_size=1)


class DatasetContractTests(unittest.TestCase):
    def test_meta_evaluation_dataset_contract(self):
        rows = read_jsonl(DEFAULT_DATASET)
        selected = select_rows(rows, None, None)
        self.assertEqual(len(selected), 384)
        self.assertEqual(len({row["meta_eval_id"] for row in selected}), 384)
        self.assertEqual(
            {grade: sum(row["final_grade"] == grade for row in selected) for grade in (0, 1)},
            {0: 8, 1: 376},
        )
        self.assertTrue(
            all(
                (row.get("AI_audit") or {}).get("verdict")
                not in {"benchmark_failure", "problem_failure"}
                for row in selected
            )
        )

    def test_static_sample_contract(self):
        rows = read_jsonl(DEFAULT_DATASET)
        sampled = select_rows(
            rows, None, None, sample_size=20, sample_seed=20260903
        )
        selection_hash = hashlib.sha256(
            "\n".join(row["meta_eval_id"] for row in sampled).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            selection_hash,
            "7eaa8b4c964e3993cd9a0263dd04106e0e035498fc6da2216f49febbda28b0fa",
        )


class MetricsTests(unittest.TestCase):
    def test_confusion_matrix_and_balanced_accuracy(self):
        records = [
            {"status": "completed", "final_grade": 1, "predicted_grade": 1},
            {"status": "completed", "final_grade": 1, "predicted_grade": 0},
            {"status": "completed", "final_grade": 0, "predicted_grade": 0},
        ]
        metrics = classification_metrics(records)
        self.assertEqual(metrics["accuracy"], 2 / 3)
        self.assertEqual(metrics["balanced_accuracy"], 0.75)


class PipelineTests(unittest.TestCase):
    def test_run_writes_and_resumes_judgments(self):
        prompt = get_prompt("default")
        config = RunConfig("fake", "judge", prompt.name, prompt.fingerprint, "json-schema")
        judge = FakeJudge('{"grade": 1, "reason": "The answers agree."}')
        with TemporaryDirectory() as directory:
            output = Path(directory) / "judgments.jsonl"
            first = run_evaluation([sample_row()], judge, prompt, config, output, 1)
            second = run_evaluation([sample_row()], judge, prompt, config, output, 1)
            records = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(judge.calls, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(first["metrics"]["accuracy"], 1.0)
        self.assertEqual(second["num_cached"], 1)


if __name__ == "__main__":
    unittest.main()
