import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import update_annotations as updater


class UpdateAnnotationsTests(unittest.TestCase):
    def test_live_form_challenge_heading_is_detected_and_normalized(self):
        values = [["Timestamp", updater.FORM_ID_COLUMN, "File uploads"],
                  ["2026-09-06", "48", "https://drive.google.com/open?id=abc"]]
        metadata = {"sheets": [{"properties": {"title": "Form Responses 1"}}]}
        with patch.object(updater, "get_json", side_effect=[metadata, {"values": values}]):
            title, fetched = updater.fetch_annotations(None, "test")
        self.assertEqual(title, "Form Responses 1")
        headers, records = updater.parse_rows(fetched)
        self.assertIn("Challenge ID", headers)
        self.assertNotIn(updater.FORM_ID_COLUMN, headers)
        self.assertEqual(records[0]["Challenge ID"], "48")

    def test_preserves_local_grades_and_multiline_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.csv"
            path.write_text("Challenge ID,final_grade\n1,correct\n2,model_failure\n")
            data, count = updater.build_csv([
                ["Challenge ID", "Solution review notes"],
                ["2", 'new note, with "quotes"\nand another line'],
                ["3"],
            ], path)
            rows = list(csv.DictReader(io.StringIO(data.decode())))
            self.assertEqual(count, 2)
            self.assertEqual(rows[0]["final_grade"], "model_failure")
            self.assertEqual(rows[0]["Solution review notes"], 'new note, with "quotes"\nand another line')
            self.assertEqual(rows[1]["final_grade"], "")

    def test_remote_grade_can_clear_local_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.csv"
            path.write_text("Challenge ID,final_grade\n1,correct\n")
            data, _ = updater.build_csv([["Challenge ID", "final_grade"], ["1"]], path)
            self.assertEqual(list(csv.DictReader(io.StringIO(data.decode())))[0]["final_grade"], "")

    def test_invalid_download_does_not_change_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.csv"
            path.write_text("original")
            for values in ([], [["Challenge ID"]], [["Wrong"], ["1"]],
                           [["Challenge ID", "Challenge ID"], ["1", "2"]],
                           [["Challenge ID", "notes"], ["", "missing ID"]]):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    updater.build_csv(values, path)
                self.assertEqual(path.read_text(), "original")

    def test_ambiguous_tabs_require_selection(self):
        metadata = {"sheets": [{"properties": {"title": title}} for title in ("A", "B")]}
        sheet = {"values": [["Challenge ID"], ["1"]]}
        with patch.object(updater, "get_json", side_effect=[metadata, sheet, sheet]):
            with self.assertRaisesRegex(ValueError, "--sheet-title"):
                updater.fetch_annotations(None, "test")
        with patch.object(updater, "get_json", side_effect=[metadata, sheet]):
            self.assertEqual(updater.fetch_annotations(None, "test", "B"), ("B", sheet["values"]))

    def test_failed_replace_keeps_existing_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.csv"
            path.write_bytes(b"original")
            with patch.object(Path, "replace", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    updater.atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
