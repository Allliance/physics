import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_conflict_report as report


def conflict(dataset="test", problem="same", display_id="1", status="unresolved"):
    audits = [
        dict(dataset=dataset, source_problem_id=problem, display_id=display_id,
             annotation_id=f"audit-{number}", category="physics", **{"pass": str(number)},
             label=label, note=f"Pass {number} note")
        for number, label in enumerate(["MODEL_FAILURE", "PROBLEM_FAILURE", "GRADER_FAILURE"], 1)
    ]
    return dict(dataset=dataset, source_problem_id=problem, display_id=display_id,
                status=status, audits=audits, reason="All three labels disagree.")


class ConflictReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conflicts = self.root / "conflicts.json"
        self.selected = self.root / "selected"

    def write_conflicts(self, entries):
        self.conflicts.write_text(json.dumps({"conflicts": entries}), encoding="utf-8")

    def write_response(self, entry, **changes):
        directory = self.selected / entry["dataset"]
        directory.mkdir(parents=True, exist_ok=True)
        response = dict(problem_id=entry["source_problem_id"], display_id=entry["display_id"],
                        problem_statement="Question $E=mc^2$ & 50%", reference_solution="Reference",
                        model_response="Model response")
        response.update(changes)
        with (directory / "responses.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(response) + "\n")

    def load(self):
        return report.load_conflicts(self.conflicts, self.selected)

    def test_only_unresolved_entries_are_joined_and_all_passes_rendered(self):
        unresolved = conflict()
        self.write_conflicts([conflict(problem="resolved-only", status="resolved"), unresolved])
        self.write_response(unresolved)
        entries = self.load()
        self.assertEqual(len(entries), 1)
        tex = report.build_tex(entries, self.conflicts)
        self.assertNotIn("resolved-only", tex)
        for number in range(1, 4):
            self.assertIn(f"Human auditor — pass {number}", tex)
            self.assertIn(f"Pass {number} note", tex)
        self.assertIn(r"\(E=mc^2\) \& 50\%", tex)
        self.assertIn("No AI-audit rationale supplied", tex)
        self.assertIn("Expert decision", tex)

    def test_join_uses_dataset_and_source_id_and_sorts_display_ids_numerically(self):
        first, second = conflict(display_id="12"), conflict(dataset="other", display_id="2")
        self.write_conflicts([first, second])
        self.write_response(first, model_response="First dataset")
        self.write_response(second, model_response="Other dataset")
        entries = self.load()
        self.assertEqual([e["display_id"] for e in entries], ["2", "12"])
        self.assertEqual(entries[0]["response"]["model_response"], "Other dataset")
        self.assertEqual(entries[1]["response"]["model_response"], "First dataset")

    def test_missing_duplicate_and_mismatched_responses_are_errors(self):
        entry = conflict()
        self.write_conflicts([entry])
        with self.assertRaisesRegex(ValueError, "Missing selected"):
            self.load()
        self.write_response(entry, display_id="99")
        with self.assertRaisesRegex(ValueError, "display ID mismatch"):
            self.load()
        (self.selected / "test" / "responses.jsonl").unlink()
        self.write_response(entry)
        self.write_response(entry)
        with self.assertRaisesRegex(ValueError, "Duplicate selected"):
            self.load()

    def test_empty_review_queue_needs_no_selected_records(self):
        self.write_conflicts([conflict(status="resolved")])
        self.assertEqual(self.load(), [])
        self.assertIn("0 unresolved problems", report.build_tex([], self.conflicts))

    def test_unknown_status_and_inconsistent_audit_identity_are_errors(self):
        self.write_conflicts([conflict(status="typo")])
        with self.assertRaisesRegex(ValueError, "Unknown conflict status"):
            self.load()
        entry = conflict()
        entry["audits"][0]["dataset"] = "wrong"
        self.write_conflicts([entry])
        with self.assertRaisesRegex(ValueError, "Audit identity"):
            self.load()

    def test_malformed_math_can_fall_back_to_original_source(self):
        entry = conflict()
        self.write_conflicts([entry])
        self.write_response(entry, reference_solution=r"Broken $\unknowncommand{a}$")
        entries = self.load()
        tex = report.build_tex(entries, self.conflicts)
        line_number = next(i for i, line in enumerate(tex.splitlines(), 1) if "unknowncommand" in line)
        self.assertEqual(report.failed_block(tex, line_number), "Q1-reference_solution")
        fallback = report.build_tex(entries, self.conflicts, {"Q1-reference_solution"})
        self.assertIn("\\begin{ReportText}\nBroken $\\unknowncommand{a}$", fallback)
        self.assertIsNone(report.failed_block(tex, 1))
        self.assertIsNone(report.failed_block(tex, None))


if __name__ == "__main__":
    unittest.main()
