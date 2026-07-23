import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from eval.llm import Completion, OpenAICompatibleLLM
from utils.codex_cli import CodexLLM

from eval.__main__ import resolve_dataset_path
from eval.parsing import detect_part_ids, extract_boxes, map_separated_boxes, parse_json_object
from eval.prompts import MERGED_JUDGE_SYSTEM
from eval.pipeline import (
    MERGED_SCHEMA, GenerationConfig, RunConfig, _attempt_key, _key,
    artifact_dir, candidate_answers, load_ground_truths, model_artifact_dir, normalize_row,
    resolve_ground_truth, run,
)


class ParsingTests(unittest.TestCase):
    def test_dataset_selection(self):
        self.assertEqual(resolve_dataset_path("FrontierPhysics", "test").name, "test.parquet")
        self.assertEqual(resolve_dataset_path("Physics", "validation").name, "validation.parquet")
        with self.assertRaisesRegex(ValueError, "no validation split"):
            resolve_dataset_path("FrontierPhysics", "validation")
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / "custom.parquet"
            dataset.touch()
            self.assertEqual(resolve_dataset_path("Physics", "test", dataset), dataset)

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

    def test_legacy_prepared_row_is_normalized(self):
        row = normalize_row({
            "id": "legacy",
            "questions": "(a) Q1 (b) Q2",
            "solutions": "(a) A1 (b) A2",
            "final_answers": '["A1", "A2"]',
        })
        self.assertEqual(row["question"], "(a) Q1 (b) Q2")
        self.assertEqual(row["solution"], "(a) A1 (b) A2")
        self.assertEqual(row["ground_truths"], {"a": "A1", "b": "A2"})
        self.assertTrue(row["is_multi_part"])


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


class MediaCheckingLLM(SequenceLLM):
    def __init__(self, *texts):
        super().__init__(*texts)
        self.media_counts = []
        self.media_paths_existed = []

    def complete(self, *args, **kwargs):
        image_paths = kwargs.get("image_paths") or []
        self.media_counts.append(len(image_paths))
        self.media_paths_existed.append(all(Path(path).is_file() for path in image_paths))
        return super().complete(*args, **kwargs)


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

    def test_codex_command_attaches_images(self):
        client = CodexLLM(model="gpt-5.5")
        cmd = client._build_command(Path("/tmp/work"), None, [Path("/tmp/one.png"), Path("/tmp/two.jpg")])
        self.assertIn("--image", cmd)
        self.assertEqual(cmd[cmd.index("--image") + 1], "/tmp/one.png")
        self.assertEqual(cmd[cmd.index("--image", cmd.index("--image") + 1) + 1], "/tmp/two.jpg")


class JudgmentCacheTests(unittest.TestCase):
    def test_judge_schemas_require_reasons(self):
        part_schema = MERGED_SCHEMA["properties"]["parts"]["items"]
        self.assertEqual(set(part_schema["properties"]), {"part", "score", "reason"})
        self.assertEqual(set(part_schema["required"]), {"part", "score", "reason"})

    def test_generation_cache_tag_changes_with_sampling(self):
        greedy = GenerationConfig("model", temperature=0.0)
        sampled = GenerationConfig("model", temperature=1.0, top_p=1.0)
        self.assertNotEqual(greedy.cache_tag(), sampled.cache_tag())

    def test_repeat_runs_generation_and_judgment_per_attempt(self):
        row = {"id": "sample", "question": "question", "solution": "final answer yes"}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            row_key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge", repeat=4, max_workers=1)
            generator = SequenceLLM(
                r"\boxed{yes}",
                r"\boxed{no}",
                r"\boxed{yes}",
                r"\boxed{yes}",
            )
            judge = SequenceLLM(
                '{"parts": [{"part": "a", "score": 1, "reason": "attempt 1"}]}',
                '{"parts": [{"part": "a", "score": 0, "reason": "attempt 2"}]}',
                '{"parts": [{"part": "a", "score": 1, "reason": "attempt 3"}]}',
                '{"parts": [{"part": "a", "score": 1, "reason": "attempt 4"}]}',
            )
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, generator, judge)

            self.assertEqual(len(generator.calls), 4)
            self.assertEqual(len(judge.calls), 4)
            response_keys = [
                json.loads(line)["key"]
                for line in model_artifact_dir(root / "artifacts", dataset, config)
                .joinpath("responses.jsonl").read_text().splitlines()
            ]
            self.assertEqual(response_keys, [_attempt_key(row_key, attempt)
                                             for attempt in range(1, 5)])
            summary = json.loads((result / "summary.json").read_text())
            self.assertEqual(summary["repeat"], 4)
            self.assertEqual(summary["num_rows"], 1)
            self.assertEqual(summary["num_attempts"], 4)
            self.assertEqual(summary["mean_score"], 1.0)
            self.assertEqual(summary["mean@4"], 0.75)
            self.assertEqual(summary["best@4"], 1.0)
            self.assertEqual(summary["mean_at_4"], 0.75)
            self.assertEqual(summary["best_at_4"], 1.0)
            self.assertEqual(summary["num_rows_with_all_4_attempts_scored"], 1)

    def test_merged_multimodal_run_attaches_row_media_to_generator_and_judge(self):
        image_data_url = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6X"
            "7q2sAAAAASUVORK5CYII="
        )
        row = {
            "id": "sample",
            "question": "Use the attached graph. What is shown?",
            "solution": "final answer yes",
            "graphs": json.dumps([{"image_url": {"url": image_data_url}}]),
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            config = RunConfig(mode="merged",
                               generation=GenerationConfig("generator", include_media=True),
                               judge_name="judge", max_workers=1)
            generator = MediaCheckingLLM(r"\boxed{yes}")
            judge = MediaCheckingLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "The answer matches."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, generator, judge)

            self.assertEqual(generator.media_counts, [1])
            self.assertEqual(judge.media_counts, [1])
            self.assertEqual(generator.media_paths_existed, [True])
            self.assertEqual(judge.media_paths_existed, [True])
            response = json.loads(
                (model_artifact_dir(root / "artifacts", dataset, config) / "responses.jsonl")
                .read_text().splitlines()[-1]
            )
            summary = json.loads((result / "summary.json").read_text())
            self.assertEqual(response["media_count"], 1)
            self.assertEqual(response["missing_media"], [])
            self.assertEqual(summary["media_rows"], 1)
            self.assertEqual(summary["missing_media_rows"], 0)

    def test_repeat_reuses_legacy_first_attempt_cache(self):
        row = {"id": "sample", "question": "question", "solution": "final answer yes"}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            row_key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge", repeat=2, max_workers=1)
            out = model_artifact_dir(root / "artifacts", dataset, config)
            judge_out = out / "judge_judge"
            judge_out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": row_key, "id": "sample", "part_ids": [],
                "extracted_answer": "yes",
            }) + "\n")
            (judge_out / "judgments.jsonl").write_text(json.dumps({
                "key": row_key, "id": "sample", "part_ids": ["a"],
                "correct": ["a"], "score": 1.0,
                "parts": {"a": {"score": 1, "reason": "cached first attempt"}},
            }) + "\n")
            generator = SequenceLLM(r"\boxed{no}")
            judge = SequenceLLM('{"parts": [{"part": "a", "score": 0, "reason": "new second attempt"}]}')
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, generator, judge)

            self.assertEqual(len(generator.calls), 1)
            self.assertEqual(len(judge.calls), 1)
            judgments = [json.loads(line) for line in (result / "judgments.jsonl").read_text().splitlines()]
            self.assertEqual([item["key"] for item in judgments],
                             [row_key, _attempt_key(row_key, 2)])
            summary = json.loads((result / "summary.json").read_text())
            self.assertEqual(summary["mean_score"], 1.0)
            self.assertEqual(summary["mean@2"], 0.5)
            self.assertEqual(summary["best@2"], 1.0)

    def test_separated_mode_is_deprecated(self):
        row = {"id": "sample", "question": "question", "solution": "final answer yes"}
        config = RunConfig(mode="separated", generation=GenerationConfig("generator"),
                           judge_name="judge")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            with patch("eval.pipeline.read_rows", return_value=[row]):
                with self.assertRaisesRegex(ValueError, "separated mode is deprecated"):
                    run(dataset, root / "artifacts", config, FailingLLM(), FailingLLM())

    def test_reason_free_cached_judgment_is_refreshed(self):
        row = {"id": "sample", "question": "question", "solution": "final answer yes"}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            judge_out = out / "judge_judge"
            judge_out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": [],
                "extracted_answer": "yes",
            }) + "\n")
            (judge_out / "judgments.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a"],
                "correct": ["a"], "score": 1.0,
                "parts": {"a": {"score": 1}},
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "The answer matches the reference."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            self.assertEqual(len(judge.calls), 1)
            refreshed = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(refreshed["parts"]["a"]["reason"], "The answer matches the reference.")

    def test_merged_single_part_judgment_records_reason(self):
        row = {"id": "sample", "question": "question", "solution": "final answer yes"}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": [],
                "extracted_answer": "yes",
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "The candidate states yes."}]
            }))
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
                    {"part": "a", "score": 1, "reason": "Part a matches."},
                    {"part": "b", "score": 0, "reason": "Part b does not match."},
                ]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(judgment["correct"], ["a"])
            self.assertEqual(judgment["score"], 0.5)
            self.assertEqual(judgment["parts"]["a"]["score"], 1)
            self.assertEqual(judgment["parts"]["b"]["score"], 0)
            self.assertEqual(judgment["parts"]["a"]["reason"], "Part a matches.")
            self.assertEqual(judgment["parts"]["b"]["reason"], "Part b does not match.")

    def test_merged_target_parts_are_prompted_and_used_as_denominator(self):
        row = {
            "id": "sample",
            "question": "(a) answer yes. (b) answer no. (c) answer maybe.",
            "solution": "(a) yes. (b) no. (c) See the book.",
            "is_multi_part": True,
            "target_parts": ["a", "c"],
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
                "key": key, "id": "sample", "part_ids": ["a", "c"],
                "extracted_answer": "(a) yes; (b) no; (c) maybe",
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [
                    {"part": "a", "score": 1, "reason": "Part a matches."},
                    {"part": "b", "score": 1, "reason": "Extra part should be ignored."},
                    {"part": "c", "score": None, "reason": "Reference points to inaccessible material."},
                ]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)

            prompt = judge.calls[0][0][0]
            system_prompt = judge.calls[0][1]["system_prompt"]
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertIn("Target parts to judge", prompt)
            self.assertIn('["a", "c"]', prompt)
            self.assertIn("Reference solution policy", prompt)
            self.assertNotIn("target parts", system_prompt.lower())
            self.assertEqual(judgment["part_ids"], ["a", "c"])
            self.assertEqual(judgment["target_parts"], ["a", "c"])
            self.assertEqual(judgment["score_denominator"], "target_parts")
            self.assertEqual(judgment["score"], 0.5)
            self.assertEqual(judgment["correct"], ["a"])
            self.assertEqual(judgment["num_scored_parts"], 1)
            self.assertEqual(judgment["num_unscored_parts"], 1)
            self.assertEqual(set(judgment["parts"]), {"a", "c"})

    def test_merged_target_parts_refresh_old_inferred_cache(self):
        row = {
            "id": "sample",
            "question": "(a) answer yes. (b) answer no.",
            "solution": "(a) yes. (b) no.",
            "is_multi_part": True,
            "target_parts": ["a"],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            judge_out = out / "judge_judge"
            judge_out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": [],
                "extracted_answer": "(a) yes; (b) wrong",
            }) + "\n")
            (judge_out / "judgments.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a", "b"],
                "correct": ["a"], "score": 0.5,
                "parts": {
                    "a": {"score": 1, "reason": "cached part a"},
                    "b": {"score": 0, "reason": "cached part b"},
                },
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "Targeted part a matches."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)

            self.assertEqual(len(judge.calls), 1)
            judgments = [json.loads(line) for line in (result / "judgments.jsonl").read_text().splitlines()]
            self.assertEqual(len(judgments), 2)
            self.assertEqual(judgments[-1]["part_ids"], ["a"])
            self.assertEqual(judgments[-1]["target_parts"], ["a"])
            self.assertEqual(judgments[-1]["score"], 1.0)

    def test_strict_reference_judge_prompt_uses_separate_artifact_dir(self):
        row = {
            "id": "sample",
            "question": "question",
            "solution": "reference answer",
            "target_parts": ["a"],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge", judge_prompt="strict-reference")
            out = model_artifact_dir(root / "artifacts", dataset, config)
            out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": ["a"],
                "extracted_answer": "candidate answer",
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 0, "reason": "Does not match reference."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)

            prompt = judge.calls[0][0][0]
            system_prompt = judge.calls[0][1]["system_prompt"]
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(result, artifact_dir(root / "artifacts", dataset, config))
            self.assertIn("prompt_strict-reference-gold", result.name)
            self.assertIn("Reference solution policy", prompt)
            self.assertIn("gold standard", prompt)
            self.assertIn("Do not override", prompt)
            self.assertEqual(system_prompt, MERGED_JUDGE_SYSTEM)
            self.assertEqual(judgment["judge_prompt"], "strict-reference")

    def test_merged_judgment_does_not_require_ground_truths(self):
        row = {
            "id": "sample",
            "question": "question",
            "solution": "final answer yes",
            "is_multi_part": False,
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
                "key": key, "id": "sample", "part_ids": [],
                "extracted_answer": "yes",
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "The candidate states yes."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(judgment["part_ids"], ["a"])
            self.assertEqual(judgment["score"], 1.0)

    def test_merged_generation_uses_last_box_without_format_error(self):
        row = {
            "id": "sample",
            "question": "question",
            "solution": "final answer yes",
            "is_multi_part": False,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge", max_workers=1)
            generator = SequenceLLM(r"work \boxed{no} more work \boxed{yes}")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "The candidate states yes."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, generator, judge)

            response = json.loads(
                (model_artifact_dir(root / "artifacts", dataset, config) / "responses.jsonl")
                .read_text().splitlines()[-1]
            )
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(response["boxes"], ["no", "yes"])
            self.assertEqual(response["extracted_answer"], "yes")
            self.assertEqual(response["format_errors"], [])
            self.assertEqual(judgment["score"], 1.0)

    def test_merged_cached_multi_box_response_is_rejudged_with_last_box(self):
        row = {
            "id": "sample",
            "question": "question",
            "solution": "final answer yes",
            "is_multi_part": False,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "Dataset" / "test.parquet"
            key = _key(dataset, row)
            config = RunConfig(mode="merged", generation=GenerationConfig("generator"),
                               judge_name="judge", max_workers=1)
            out = model_artifact_dir(root / "artifacts", dataset, config)
            out.mkdir(parents=True)
            (out / "responses.jsonl").write_text(json.dumps({
                "key": key, "id": "sample", "part_ids": [],
                "boxes": ["no", "yes"],
                "extracted_answer": "",
                "format_errors": ["expected 1 box, found 2"],
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [{"part": "a", "score": 1, "reason": "The candidate states yes."}]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)

            prompt = judge.calls[0][0][0]
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            summary = json.loads((result / "summary.json").read_text())
            self.assertIn("Candidate final answer", prompt)
            self.assertIn("yes", prompt)
            self.assertEqual(judgment["score"], 1.0)
            self.assertEqual(summary["format_error_rows"], 0)

    def test_merged_null_part_scores_are_excluded_from_denominator(self):
        row = {
            "id": "sample",
            "question": "(a) answer yes. (b) answer no.",
            "solution": "(a) yes. (b) See the book.",
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
                "key": key, "id": "sample", "part_ids": [],
                "extracted_answer": "(a) yes; (b) no",
            }) + "\n")
            judge = SequenceLLM(json.dumps({
                "parts": [
                    {"part": "a", "score": 1, "reason": "Part a matches."},
                    {"part": "b", "score": None, "reason": "Reference points to inaccessible material."},
                ]
            }))
            with patch("eval.pipeline.read_rows", return_value=[row]):
                result = run(dataset, root / "artifacts", config, FailingLLM(), judge)
            judgment = json.loads((result / "judgments.jsonl").read_text().splitlines()[-1])
            self.assertEqual(judgment["score"], 1.0)
            self.assertEqual(judgment["num_scored_parts"], 1)
            self.assertEqual(judgment["num_unscored_parts"], 1)
            summary = json.loads((result / "summary.json").read_text())
            self.assertEqual(summary["mean_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
