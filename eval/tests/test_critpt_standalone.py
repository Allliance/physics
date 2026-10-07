import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from eval import backends
from eval.pre_audit import critpt
from eval.pre_audit.pipeline import JudgeSettings, _judge_args, load_benchmark
from eval.pre_audit.__main__ import parser
from eval.pre_audit.runner import run


JUDGMENT = {
    "correct": "yes", "extracted_final_answer": "2",
    "reasoning": "Equivalent.", "confidence": 100,
}


class CritPtStandaloneTests(unittest.TestCase):
    def test_pre_audit_preserves_prompt_schema_and_no_tool_transport(self):
        captured = {}

        def complete(prompt, *, output_schema, **kwargs):
            captured["prompt"] = prompt
            captured["schema"] = json.loads(output_schema.read_text())
            return SimpleNamespace(text=json.dumps(JUDGMENT), usage={},
                                   events=[{"type": "turn.completed"}])

        client = MagicMock()
        client.complete.side_effect = complete
        with patch.object(backends, "CodexLLM", return_value=client) as constructor:
            pipeline = load_benchmark("critpt", judge_settings=JudgeSettings(codex_bin="test-codex"))
            problem = pipeline.problems[0]
            result = pipeline.evaluate(problem.id, "candidate")
        expected = (critpt.PROMPTS / "critpt_judge.txt").read_text().strip() + "\n"
        expected += json.dumps({"problem": problem.question,
                               "ground_truth": problem.reference_answer,
                               "model_solution": "candidate"}, ensure_ascii=False)
        self.assertEqual(captured["prompt"], expected)
        self.assertEqual(captured["schema"], json.loads(
            (critpt.PROMPTS / "critpt_judge_schema.json").read_text()))
        self.assertEqual(result.details["judgment"], JUDGMENT)
        self.assertTrue(result.correct)
        self.assertTrue(constructor.call_args.kwargs["strict_no_tools"])
        self.assertEqual(constructor.call_args.kwargs["web_search"], "disabled")

    def test_pre_audit_fable_validates_judgments_and_keeps_failures_pending(self):
        client = MagicMock()
        message = client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value
        raw = {"model": "claude-fable-5", "stop_reason": "end_turn", "usage": {},
               "content": [{"type": "text", "text": json.dumps(JUDGMENT)}]}
        settings = JudgeSettings(model="claude-fable-5", fable_model="claude-fable-5")
        with patch.object(backends, "make_fable_client", return_value=client):
            pipeline = load_benchmark("critpt", judge_settings=settings)
            problem = pipeline.problems[0]
            message.model_dump.return_value = raw
            self.assertTrue(pipeline.evaluate(problem.id, "candidate").correct)
            request = client.messages.stream.call_args.kwargs
            self.assertEqual(request["system"],
                             (critpt.PROMPTS / "critpt_judge_system.txt").read_text().strip())
            self.assertNotIn("tools", request)
            for judgment in ({}, {**JUDGMENT, "strict": True}, {**JUDGMENT, "confidence": True}):
                message.model_dump.return_value = {
                    **raw, "content": [{"type": "text", "text": json.dumps(judgment)}]}
                with self.assertRaises(ValueError):
                    pipeline.evaluate(problem.id, "candidate")
            message.model_dump.return_value = {
                **raw, "content": [{"type": "text", "text": json.dumps({**JUDGMENT, "correct": "no"})}]}
            self.assertFalse(pipeline.evaluate(problem.id, "candidate").correct)

    def test_corrected_judge_still_requires_strict_schema(self):
        with self.assertRaises(ValueError):
            backends.validate_judgment(JUDGMENT)
        backends.validate_judgment({**JUDGMENT, "strict": True})

    def test_pre_audit_refusal_uses_its_schema_without_calling_judge(self):
        client = MagicMock()
        with patch.object(backends, "CodexLLM", return_value=client):
            judge = critpt.make_judge(_judge_args(JudgeSettings()))
            result = judge({"question": "Q", "reference_answer": "2"},
                           {"response": "", "refused": True})
        self.assertFalse(result["judge_called"])
        self.assertEqual(result["judgment"]["correct"], "no")
        self.assertNotIn("strict", result["judgment"])
        client.complete.assert_not_called()

    def test_pre_audit_resume_rejects_changed_judge_contract(self):
        identity = critpt.provenance()
        with tempfile.TemporaryDirectory() as directory:
            args = parser().parse_args([
                "run", "--dataset", "critpt", "--output", directory, "--stage", "prepare",
                "--model", "gpt-5.6-sol", "--judge-model", "gpt-6-astra"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(args), 0)
                changed = {**identity, "prompts_sha256": {"critpt_judge.txt": "changed"}}
                with patch.object(critpt, "provenance", return_value=changed):
                    with self.assertRaisesRegex(ValueError, "Inputs/configuration changed"):
                        run(args)

    def test_both_protocols_complete_and_resume_without_analysis_or_model_evals(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "artifacts", "reproduction", "tests")
            for package in ("eval", "utils"):
                shutil.copytree(root / package, target / package, ignore=ignore)
            script = r'''
import contextlib, io, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from eval import backends, post_audit
from eval.pre_audit import runner
from eval.pre_audit.__main__ import parser

assert not Path('analysis').exists() and not Path('model_evals').exists()
judgment = {'correct': 'yes', 'extracted_final_answer': '2',
            'reasoning': 'Equivalent.', 'confidence': 100}
def predict(question):
    assert 'reference_answer' not in question and 'ground_truth' not in question
    return {'response': 'candidate', 'refused': False}
def complete(prompt, *, output_schema, **kwargs):
    schema = json.loads(output_schema.read_text())
    result = {**judgment, **({'strict': True} if 'strict' in schema['required'] else {})}
    return SimpleNamespace(text=json.dumps(result), usage={}, events=[{'type': 'turn.completed'}])
client = MagicMock()
client.complete.side_effect = complete
common = ['--dataset', 'critpt', '--model', 'gpt-5.6-sol', '--judge-model', 'gpt-6-astra', '--workers', '1']
pre = parser().parse_args(['run', *common, '--output', 'pre', '--score-workers', '1'])
post = post_audit.parser().parse_args([*common, '--output', 'post'])
with patch.object(backends, 'CodexLLM', return_value=client), \
     patch.object(runner, 'make_predictor', return_value=predict), \
     patch.object(post_audit, 'make_predictor', return_value=predict), \
     patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network request')), \
     contextlib.redirect_stdout(io.StringIO()):
    assert runner.run(pre) == 0
    assert post_audit.run_one(post) == 0
    calls = client.complete.call_count
    assert calls == 55 + 54
    assert runner.run(pre) == 0 and post_audit.run_one(post) == 0
    assert client.complete.call_count == calls
pre_summary = json.loads(Path('pre/critpt/attempt-1/summary.json').read_text())
post_summary = json.loads(Path('post/summary.json').read_text())
assert pre_summary['complete'] and pre_summary['scored'] == 55
assert post_summary['complete'] and post_summary['judgments'] == 54
print('Standalone CritPt: 55 pre-audit and 54 post-audit rows completed and resumed')
'''
            result = subprocess.run([sys.executable, "-c", script], cwd=target,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
