"""Exercise the upstream contract through the canonical, network-free routes."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from eval import backends
from eval.post_audit import parser as post_parser
from eval.pre_audit import hle
from eval.pre_audit.pipeline import JudgeSettings, _make_adapted_judge, load_benchmark
from eval.pre_audit.__main__ import parser as pre_parser
from eval.pre_audit.runner import run
from utils.fable_backend import GenerationLimitError, parse_fable_response


JUDGMENT = {"extracted_final_answer": "2", "reasoning": "Equivalent.",
            "correct": "yes", "confidence": 100, "strict": True}


class HLEUpstreamTests(unittest.TestCase):
    def test_contract_loading_does_not_execute_the_upstream_cli(self):
        source = hle.JUDGE_SOURCE.read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "judge.py"
            path.write_text('raise RuntimeError("must not execute upstream CLI")\n' + source)
            prompt, schema = hle.load_contract(path)
        self.assertIn("do not attempt to solve the problem", prompt)
        self.assertEqual(schema["properties"]["correct"],
                         {"type": "string", "enum": ["yes", "no"]})
        self.assertEqual(schema["properties"]["strict"], {"type": "boolean", "const": True})
        self.assertEqual(set(schema["required"]), set(JUDGMENT))

    def test_missing_checkout_and_schema_drift_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "judge.py"
            with self.assertRaisesRegex(FileNotFoundError, "git submodule update"):
                hle.load_contract(path)
            path.write_text(hle.JUDGE_SOURCE.read_text().replace("confidence: int", "confidence: float"))
            with self.assertRaisesRegex(ValueError, "schema changed"):
                hle.load_contract(path)

    def test_pre_audit_codex_receives_the_exact_upstream_prompt(self):
        captured = {}

        def complete(prompt, *, output_schema, image_paths):
            captured.update(prompt=prompt, schema=json.loads(output_schema.read_text()))
            return SimpleNamespace(text=json.dumps(JUDGMENT), usage={}, attempts=1,
                                   events=[{"type": "turn.completed"}])

        client = MagicMock()
        client.complete.side_effect = complete
        with patch.object(backends, "CodexLLM", return_value=client) as constructor:
            pipeline = load_benchmark("hle", judge_settings=JudgeSettings(codex_bin="test-codex"))
            problem = pipeline.problems[0]
            result = pipeline.evaluate(problem.id, "candidate")
        prompt, schema = hle.load_contract()
        self.assertTrue(result.correct)
        self.assertEqual(captured["prompt"], prompt.format(
            question=problem.question, correct_answer=problem.reference_answer, response="candidate"))
        self.assertEqual(captured["schema"], schema)
        self.assertEqual(constructor.call_args.kwargs["codex_bin"], "test-codex")
        self.assertTrue(constructor.call_args.kwargs["strict_no_tools"])

    def test_pre_audit_fable_uses_upstream_and_retries_invalid_judgments(self):
        raw = {"model": "claude-fable-5", "stop_reason": "end_turn", "usage": {},
               "content": [{"type": "text", "text": json.dumps(JUDGMENT)}]}
        client = MagicMock()
        message = client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value
        message.model_dump.return_value = raw
        settings = JudgeSettings(model="claude-fable-5", fable_model="claude-fable-5")
        with patch.object(backends, "make_fable_client", return_value=client):
            pipeline = load_benchmark("hle", judge_settings=settings)
            problem = pipeline.problems[0]
            self.assertTrue(pipeline.evaluate(problem.id, "candidate").correct)
            request = client.messages.stream.call_args.kwargs
            prompt, _ = hle.load_contract()
            expected = prompt.format(question=problem.question,
                                     correct_answer=problem.reference_answer, response="candidate")
            self.assertTrue(request["messages"][0]["content"][0]["text"].startswith(expected))
            self.assertNotIn("tools", request)
            message.model_dump.return_value = {**raw, "content": [{"type": "text", "text": "{}"}]}
            with self.assertRaises(ValueError):
                pipeline.evaluate(problem.id, "candidate")

    def test_corrected_judge_does_not_use_the_upstream_contract(self):
        args = post_parser().parse_args([
            "--dataset", "hle", "--output", "unused", "--model", "claude-fable-5",
            "--judge-model", "gpt-5.6-sol"])
        client = MagicMock()
        client.complete.return_value = SimpleNamespace(
            text=json.dumps(JUDGMENT), usage={}, events=[{"type": "turn.completed"}])
        with patch.object(hle, "load_contract", side_effect=AssertionError("unexpected upstream access")), \
                patch.object(backends, "CodexLLM", return_value=client):
            result = backends.make_judge(args)({"question": "Q", "reference_answer": "2"},
                                              {"response": "candidate"})
        self.assertEqual(result["judgment"], JUDGMENT)
        self.assertEqual(client.complete.call_args.args[0], backends.JUDGE.format(
            question="Q", correct_answer="2", response="candidate"))

    def test_canonical_critpt_does_not_import_the_discarded_hle_package(self):
        forbidden = {name: None for name in (
            "hle_eval", "hle_eval.backends", "hle_eval.claude", "hle_eval.errors",
            "benchmarks.hle.hle_eval.backends", "benchmarks.hle.hle_eval.scoring")}
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "utils"))
        import codex_cli

        with patch.dict(sys.modules, forbidden), patch.object(codex_cli, "CodexLLM"):
            judge = _make_adapted_judge("critpt", JudgeSettings(fable_model="claude-fable-5"))
        self.assertTrue(callable(judge))

    def test_pre_audit_checkpoint_rejects_changed_upstream_provenance(self):
        identity = hle.provenance()
        self.assertEqual(identity["source_sha256"], hashlib.sha256(hle.JUDGE_SOURCE.read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            args = pre_parser().parse_args([
                "run", "--dataset", "hle", "--output", directory, "--stage", "prepare",
                "--model", "gpt-5.6-sol", "--judge-model", "gpt-6-astra"])
            with contextlib.redirect_stdout(io.StringIO()), patch.object(hle, "provenance", return_value=identity):
                self.assertEqual(run(args), 0)
            manifest = json.loads((Path(directory) / "hle-physics/attempt-1/manifest.json").read_text())
            self.assertEqual(manifest["evaluator_source"], identity)
            with patch.object(hle, "provenance", return_value={**identity, "commit": "changed"}):
                with self.assertRaisesRegex(ValueError, "Inputs/configuration changed"):
                    run(args)

    def test_shared_fable_parser_preserves_limit_and_refusal_handling(self):
        raw = {"model": "claude-fable-5", "content": []}
        with self.assertRaises(GenerationLimitError):
            parse_fable_response({**raw, "stop_reason": "max_tokens"}, "claude-fable-5")
        result = parse_fable_response({**raw, "stop_reason": "refusal"}, "claude-fable-5")
        self.assertTrue(result["refused"])
        self.assertIn("Answer: None", result["response"])
