import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from eval.llm import Completion, OpenAICompatibleLLM

from eval.__main__ import resolve_dataset_path
from eval.parsing import detect_part_ids, extract_boxes, map_separated_boxes, parse_json_object
from eval.pipeline import (
    MERGED_SCHEMA, SEPARATED_SCHEMA, GenerationConfig, RunConfig, _key, candidate_answers,
    load_ground_truths, model_artifact_dir, resolve_ground_truth, run,
)


class ParsingTests(unittest.TestCase):
    def test_dataset_selection(self):
        self.assertEqual(resolve_dataset_path("FrontierPhysics", "test").name, "test.parquet")
        self.assertEqual(resolve_dataset_path("Physics", "validation").name, "validation.parquet")
        with self.assertRaisesRegex(ValueError, "no validation split"):
            resolve_dataset_path("FrontierPhysics", "validation")

    def test_parts_are_ground_truth_keys_in_order(self):
        self.assertEqual(detect_part_ids({"b": "one", "d": "two", "f": "three"}), ["b", "d", "f"])

    def test_parts_require_nonempty_ground_truths(self):
        with self.assertRaisesRegex(ValueError, "at least one part"):
            detect_part_ids({})

    def test_balanced_boxes(self):
        text = r"work \boxed{(a) \frac{x}{y}} then \boxed{(b) z}"
        self.assertEqual(extract_boxes(text), [r"(a) \frac{x}{y}", "(b) z"])

    def test_empty_and_whitespace_boxes(self):
        self.assertEqual(extract_boxes(r"\boxed{} \boxed   { (b) answer }"), ["", "(b) answer"])

    def test_escaped_braces_do_not_affect_balance(self):
        self.assertEqual(extract_boxes(r"\boxed{(a) \{x\} and \text{set {A}}}"),
                         [r"(a) \{x\} and \text{set {A}}"])

    def test_deeply_nested_box_content(self):
        text = r"\boxed{(a) \frac{1}{1+\frac{x}{1+\frac{y}{z}}}}"
        self.assertEqual(extract_boxes(text), [r"(a) \frac{1}{1+\frac{x}{1+\frac{y}{z}}}"])

    def test_no_box_returns_empty_list(self):
        self.assertEqual(extract_boxes("There is no final answer box."), [])

    def test_unclosed_box_is_ignored(self):
        self.assertEqual(extract_boxes(r"reasoning \boxed{(a) unfinished"), [])

    def test_map_boxes(self):
        mapped, errors = map_separated_boxes(["(a) 1", "(b): 2"], ["a", "b"])
        self.assertEqual(mapped, {"a": "1", "b": "2"})
        self.assertEqual(errors, [])

    def test_formula_letter_is_not_mistaken_for_part_label(self):
        mapped, errors = map_separated_boxes([r"V=1", r"\,(b) 2"], ["a", "b"])
        self.assertEqual(mapped, {"b": "2", "a": "V=1"})
        self.assertEqual(errors, ["box 1 lacked a valid label; assigned by position"])

    def test_explicit_label_wins_over_earlier_positional_fallback(self):
        mapped, errors = map_separated_boxes(["(a) wrong part", "(b) requested"], ["b"])
        self.assertEqual(mapped, {"b": "requested"})
        self.assertEqual(errors, ["expected 1 boxes, found 2"])

    def test_preserved_single_subquestion_box_is_canonicalized_to_a(self):
        mapped, errors = map_separated_boxes(["(c) final answer"], ["a"])
        self.assertEqual(mapped, {"a": "final answer"})
        self.assertEqual(errors, ["box 1 lacked a valid label; assigned by position"])

    def test_cached_single_subquestion_answer_is_canonicalized_to_a(self):
        row = {"is_multi_part": False}
        response = {"extracted_answers": {"b": "(b) final answer"}}
        self.assertEqual(candidate_answers(row, response, ["a"]), {"a": "final answer"})

    def test_true_multipart_answer_keys_are_not_canonicalized(self):
        row = {"is_multi_part": True}
        response = {"extracted_answers": {"b": "final answer"}}
        self.assertEqual(candidate_answers(row, response, ["a"]), {"b": "final answer"})

    def test_json_fenced(self):
        self.assertEqual(parse_json_object('```json\n{"correct": ["a"]}\n```')["correct"], ["a"])

    def test_ground_truths(self):
        value, source = resolve_ground_truth({"ground_truths": '{"a":"final"}'}, ["a"])
        self.assertEqual((value, source), ({"a": "final"}, "ground_truths"))

    def test_null_ground_truth_parts_are_excluded(self):
        row = {"ground_truths": {"a": "answer", "b": None, "c": "None"}}
        self.assertEqual(load_ground_truths(row), {"a": "answer", "c": "None"})
        value, source = resolve_ground_truth(row, ["a", "c"])
        self.assertEqual((value, source), ({"a": "answer", "c": "None"}, "ground_truths"))

    def test_ground_truths_is_required(self):
        with self.assertRaisesRegex(ValueError, "no ground_truths"):
            resolve_ground_truth({"id": "missing"}, ["a"])
        with self.assertRaisesRegex(ValueError, "missing parts"):
            resolve_ground_truth({"id": "partial", "ground_truths": '{"a":"x"}'}, ["a", "b"])


class FailingLLM:
    def complete(self, *args, **kwargs):
        raise AssertionError("cached judgments should not invoke an LLM")


class SequenceLLM:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = []

    def complete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.texts:
            raise AssertionError("unexpected LLM call")
        return Completion(self.texts.pop(0), usage={"prompt_tokens": 1, "completion_tokens": 1})


class LLMTests(unittest.TestCase):
    def test_null_final_content_becomes_empty_answer(self):
        raw = {"choices": [{"message": {"content": None}}], "usage": {}}
        response = BytesIO(json.dumps(raw).encode())
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *args: None
        with patch("urllib.request.urlopen", return_value=response):
            completion = OpenAICompatibleLLM("model", "http://localhost").complete(
                "prompt", system_prompt="system")
        self.assertEqual(completion.text, "")

    def test_model_specific_extra_body_is_sent(self):
        raw = {"choices": [{"message": {"content": "answer"}}]}
        response = BytesIO(json.dumps(raw).encode())
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *args: None
        with patch("urllib.request.urlopen", return_value=response) as request:
            OpenAICompatibleLLM(
                "model", "http://localhost",
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            ).complete("prompt", system_prompt="system")
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})


class JudgmentCacheTests(unittest.TestCase):
    def test_judge_schemas_require_reasons(self):
        self.assertEqual(set(SEPARATED_SCHEMA["properties"]), {"correct", "reason"})
        self.assertEqual(set(SEPARATED_SCHEMA["required"]), {"correct", "reason"})
        part_schema = MERGED_SCHEMA["properties"]["parts"]["items"]
        self.assertEqual(set(part_schema["properties"]), {"part", "correct", "reason"})
        self.assertEqual(set(part_schema["required"]), {"part", "correct", "reason"})

    def test_generation_cache_tag_changes_with_sampling(self):
        greedy = GenerationConfig("model", temperature=0.0)
        sampled = GenerationConfig("model", temperature=1.0, top_p=1.0)
        self.assertNotEqual(greedy.cache_tag(), sampled.cache_tag())

    def test_cached_judgment_drops_null_parts_without_llm_call(self):
        row = {"id": "sample", "question": "question", "ground_truths": {"a": "yes", "b": None}}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="separated", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            judge_out = out / "judge_judge"
            judge_out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a", "b"],
                "extracted_answers": {"a": "yes", "b": ""},
            }) + "\n")
            (judge_out / "judgments.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a", "b"],
                "correct": ["a", "b"], "score": 1.0,
                "parts": {
                    "a": {"correct": True, "reason": "part a is correct"},
                    "b": {"correct": True, "reason": "part b is correct"},
                },
            }) + "\n")
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), FailingLLM())
            migrated = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(migrated["part_ids"], ["a"])
            self.assertEqual(migrated["correct"], ["a"])
            self.assertEqual(migrated["score"], 1.0)
            self.assertEqual(list(migrated["parts"]), ["a"])
            self.assertEqual(migrated["parts"]["a"]["reason"], "part a is correct")
            summary = json.loads((result / "summary.json").read_text())
            self.assertNotIn("correct_parts", summary)
            self.assertNotIn("total_parts", summary)
            self.assertNotIn("micro_part_score", summary)

    def test_reason_free_cached_judgment_is_refreshed(self):
        row = {"id": "sample", "question": "question", "ground_truths": {"a": "yes"}}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="separated", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            judge_out = out / "judge_judge"
            judge_out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a"],
                "extracted_answers": {"a": "yes"},
            }) + "\n")
            (judge_out / "judgments.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a"],
                "correct": ["a"], "score": 1.0,
                "parts": {"a": {"correct": True}},
            }) + "\n")
            judge = SequenceLLM('{"correct": true, "reason": "The answer matches the reference."}')
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            self.assertEqual(len(judge.calls), 1)
            refreshed = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(refreshed["parts"]["a"]["reason"], "The answer matches the reference.")

    def test_separated_judgment_records_reason(self):
        row = {"id": "sample", "question": "question", "ground_truths": {"a": "yes"}}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="separated", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a"],
                "extracted_answers": {"a": "yes"},
            }) + "\n")
            judge = SequenceLLM('{"correct": true, "reason": "The candidate states yes."}')
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(judgment["correct"], ["a"])
            self.assertEqual(judgment["parts"]["a"]["reason"], "The candidate states yes.")

    def test_merged_judgment_records_reason_per_part(self):
        row = {
            "id": "sample",
            "question": "question",
            "solution": "part a yes; part b no",
            "ground_truths": {"a": "yes", "b": "no"},
            "is_multi_part": True,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a", "b"],
                "extracted_answer": "(a) yes; (b) maybe",
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [
                    {"part": "a", "correct": True, "reason": "Part a matches."},
                    {"part": "b", "correct": False, "reason": "Part b does not match."},
                ]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(judgment["correct"], ["a"])
            self.assertEqual(judgment["score"], 0.5)
            self.assertEqual(judgment["parts"]["a"]["reason"], "Part a matches.")
            self.assertEqual(judgment["parts"]["b"]["reason"], "Part b does not match.")


if __name__ == "__main__":
    unittest.main()
