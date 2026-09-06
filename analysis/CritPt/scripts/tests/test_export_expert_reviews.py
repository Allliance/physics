import tempfile
from pathlib import Path
import unittest

from export_expert_reviews import build_expert_reviews, write_expert_reviews
from update_annotations import FORM_ID_COLUMN, parse_rows


class ExpertReviewTests(unittest.TestCase):
    def test_all_answers_and_duplicate_submissions_are_preserved(self):
        note = 'First line, "quoted"\nSecond line: α = 2.  '
        headers, records = parse_rows([
            ["Timestamp", FORM_ID_COLUMN, "Notes?", "New question?", "final_grade"],
            ["first", "18", note, "", "local-only"],
            ["second", "18", "Later answer", "Yes", "local-only"],
        ])
        reviews = build_expert_reviews(headers, records)
        text = reviews["18"].decode()
        self.assertEqual(len(reviews), 71)
        self.assertIn(note, text)
        self.assertIn("Question: " + FORM_ID_COLUMN, text)
        self.assertIn("Question: New question?\nAnswer:\n[No answer provided]", text)
        self.assertIn("Submission 2 (annotations.csv row 3)", text)
        self.assertLess(text.index(note), text.index("Later answer"))
        self.assertNotIn("final_grade", text)
        self.assertNotIn("local-only", text)
        self.assertIn(b"No form submission available", reviews["00"])

    def test_invalid_id_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            build_expert_reviews(["Challenge ID"], [{"Challenge ID": "../71"}])

    def test_refresh_replaces_obsolete_submissions_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "01").mkdir()
            solution = directory / "01" / "solution.tex"
            solution.write_text("existing solution")
            headers = ["Challenge ID", "Notes?"]
            write_expert_reviews(directory, build_expert_reviews(
                headers, [{"Challenge ID": "1", "Notes?": "Old answer"}]))
            reviews = build_expert_reviews(headers, [{"Challenge ID": "2", "Notes?": "New answer"}])
            write_expert_reviews(directory, reviews)
            self.assertEqual(len(list(directory.glob("*/expert_review.txt"))), 71)
            self.assertIn("No form submission available", (directory / "01/expert_review.txt").read_text())
            self.assertEqual((directory / "02/expert_review.txt").read_bytes(), reviews["02"])
            self.assertEqual(solution.read_text(), "existing solution")


if __name__ == "__main__":
    unittest.main()
