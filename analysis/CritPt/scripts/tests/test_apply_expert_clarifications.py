import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from apply_expert_clarifications import apply_clarifications
from normalize_solution_roles import normalize_roles


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ExpertClarificationTests(unittest.TestCase):
    def fixture(self, base):
        (base / "solutions/02").mkdir(parents=True)
        (base / "annotations.csv").write_text("Challenge ID,Notes\n2,original review\n")
        (base / "solutions/02/solution.tex").write_text("accepted derivation")
        (base / "solutions/manifest.json").write_text(json.dumps({
            "files": [], "remove_supporting": True, "source_subdirectory": "supporting"}))
        sources = ["annotations.csv", "solutions/02/solution.tex"]
        (base / "verdict_review.json").write_text(json.dumps({
            "policy": {}, "source_sha256": {p: sha((base / p).read_bytes()) for p in sources},
            "challenges": {"02": {"reason": "unclear", "question_for_expert": "clarify?"}}}))
        plan = {
            "authority": "user-relayed expert clarification", "comments": {"02": "accept this repair"},
            "review_appendices": {"02": "accepted follow-up"},
            "verdict_policy": {"model": "Assess original model answer independently."},
            "decisions": {"02": {"verdict": {"problem": "repairable", "model": "correct"}, "reason": "expert-authorized repair; model verified"}},
            "files": {"solutions/02/problem.tex": {
                "before_sha256": None, "content": "corrected problem", "source": "expert clarification",
                "source_sha256": sha(b"expert clarification"), "action": "repaired"}},
        }
        (base / "expert_clarifications.json").write_text(json.dumps(plan))

    def test_idempotent_and_preserves_curation_without_recreating_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            apply_clarifications(base)
            first = (base / "solutions/02/expert_review.txt").read_bytes()
            first_review = (base / "verdict_review.json").read_bytes()
            apply_clarifications(base)
            self.assertEqual((base / "verdict_review.json").read_bytes(), first_review)
            self.assertEqual((base / "solutions/02/expert_review.txt").read_bytes(), first)
            self.assertEqual(first.count(b"accepted follow-up"), 1)
            self.assertEqual(json.loads((base / "verdicts.json").read_text())["02"],
                             {"problem": "repairable", "model": "correct"})
            self.assertEqual(json.loads((base / "verdict_review.json").read_text())["policy"]["model"],
                             "Assess original model answer independently.")
            # Simulate a fresh download that must not overwrite the accepted repair.
            source = base / "solutions/02/supporting/problem - Reviewer.tex"
            source.parent.mkdir()
            source.write_text("old downloaded prompt")
            normalize_roles(base / "solutions", records=[])
            self.assertEqual((base / "solutions/02/problem.tex").read_text(), "corrected problem")
            self.assertFalse(source.parent.exists())
            self.assertFalse((base / "solution_normalization_report.json").exists())
            self.assertFalse((base / "solution_normalization_exceptions.csv").exists())

    def test_unreviewed_edits_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            (base / "solutions/02/problem.tex").write_text("local edit")
            with self.assertRaisesRegex(ValueError, "Unreviewed edit"):
                apply_clarifications(base)
            self.assertEqual((base / "solutions/02/problem.tex").read_text(), "local edit")
            self.assertFalse((base / "verdicts.json").exists())

    def test_reopening_ambiguity_removes_previous_verdict_on_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            apply_clarifications(base)
            path = base / "expert_clarifications.json"
            plan = json.loads(path.read_text())
            plan["decisions"]["02"] = {
                "reason": "Repair changes the task's scope.",
                "question_for_expert": "What is the intended task?",
            }
            path.write_text(json.dumps(plan))
            for _ in range(2):
                apply_clarifications(base)
                self.assertEqual(json.loads((base / "verdicts.json").read_text()), {})
                self.assertIn("What is the intended task?", (base / "verdict_ambiguities.csv").read_text())

    def test_dry_run_does_not_mutate_any_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            before = {p.relative_to(base): p.read_bytes() for p in base.rglob("*") if p.is_file()}
            apply_clarifications(base, dry_run=True)
            after = {p.relative_to(base): p.read_bytes() for p in base.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
