import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_verdicts import build_verdicts


class BuildVerdictsTests(unittest.TestCase):
    def fixture(self, base):
        # Multiple rows for one challenge must produce only one verdict.
        annotations = base / "annotations.csv"
        annotations.write_text("Challenge ID,Notes\n1,first\n1,clarification\n2,unclear\n")
        data = {
            "source_sha256": {"annotations.csv": hashlib.sha256(annotations.read_bytes()).hexdigest()},
            "challenges": {
                "01": {"verdict": {"problem": "clean", "model": "correct"}, "reason": "Verified."},
                "02": {"reason": "Only conditionally verified.", "question_for_expert": "Is it correct?"},
            },
        }
        (base / "verdict_review.json").write_text(json.dumps(data))
        return data

    def test_pending_and_duplicate_reviews_do_not_become_evaluation_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            verdicts, csv_text, pending = build_verdicts(base)
            self.assertEqual(verdicts, {"01": {"problem": "clean", "model": "correct"}})
            self.assertEqual(pending, 1)
            self.assertIn("Is it correct?", csv_text)
            self.assertFalse((base / "verdicts.json").exists())

    def test_changed_reviews_require_readjudication(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            (base / "annotations.csv").write_text("Challenge ID,Notes\n1,now incorrect\n2,unclear\n")
            with self.assertRaisesRegex(ValueError, "Reviewed source changed"):
                build_verdicts(base)

    def test_enforces_label_relationships_and_repair_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            data = self.fixture(base)
            for problem, model in (("clean", "none"), ("clean", None),
                                   ("repairable", "correct"), ("unrepairable", "incorrect")):
                data["challenges"]["01"]["verdict"] = {"problem": problem, "model": model}
                (base / "verdict_review.json").write_text(json.dumps(data))
                with self.subTest(problem=problem, model=model), self.assertRaisesRegex(ValueError, "combination"):
                    build_verdicts(base)
            data["challenges"]["01"]["verdict"] = {"problem": "repairable", "model": "none"}
            (base / "verdict_review.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "corrected statement"):
                build_verdicts(base)

    def test_requires_complete_reviewed_challenge_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            data = self.fixture(base)
            del data["challenges"]["02"]
            (base / "verdict_review.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "cover every reviewed challenge"):
                build_verdicts(base)


if __name__ == "__main__":
    unittest.main()
