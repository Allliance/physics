import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from normalize_solution_roles import normalize_roles


class NormalizeSolutionRolesTests(unittest.TestCase):
    def test_moves_originals_and_publishes_three_roles_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "solutions"
            folder = root / "02"
            folder.mkdir(parents=True)
            entries = []
            for role in ("problem", "solution", "final_answer"):
                source = folder / f"{role} - Reviewer.tex"
                source.write_text(role)
                path = source.relative_to(root).as_posix()
                entries.append({"file_id": role, "path": path, "paths": [path],
                                "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
            (root / "manifest.json").write_text(json.dumps({"files": entries}))
            result = normalize_roles(root, records=[])
            self.assertEqual(result["complete_challenges"], 1)
            self.assertEqual(result["canonical_files"], 3)
            for role in ("problem", "solution", "final_answer"):
                self.assertEqual((folder / f"{role}.tex").read_text(), role)
                self.assertEqual((folder / "supporting" / f"{role} - Reviewer.tex").read_text(), role)
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(manifest["source_subdirectory"], "supporting")
            self.assertTrue(all("/supporting/" in entry["path"] for entry in manifest["files"]))
            self.assertEqual(normalize_roles(root, records=[]), result)

    def test_latest_submission_is_selected_and_edits_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "solutions"
            folder = root / "02"
            folder.mkdir(parents=True)
            entries = []
            records = []
            for suffix, content, timestamp in (("new", "revised", "8/29/2026 5:02:04"),
                                                ("old", "original", "8/28/2026 23:41:03")):
                source = folder / f"solution - Reviewer__{suffix}.tex"
                source.write_text(content)
                path = source.relative_to(root).as_posix()
                entries.append({"file_id": suffix, "path": path, "paths": [path]})
                records.append({"Timestamp": timestamp, "File uploads": f"https://drive.google.com/open?id={suffix}"})
            (root / "manifest.json").write_text(json.dumps({"files": entries}))
            result = normalize_roles(root, records=records)
            self.assertEqual((folder / "solution.tex").read_text(), "revised")
            self.assertEqual(result["challenges"][2]["missing"], ["problem.tex", "final_answer.tex"])
            (folder / "solution.tex").write_text("local edit")
            with self.assertRaisesRegex(ValueError, "Canonical file was edited"):
                normalize_roles(root, records=records)
            self.assertEqual((folder / "solution.tex").read_text(), "local edit")

    def test_dry_run_makes_no_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "solutions"
            root.mkdir()
            result = normalize_roles(root, records=[], dry_run=True)
            self.assertEqual(result["canonical_files"], 0)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
