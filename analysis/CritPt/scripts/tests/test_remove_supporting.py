import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from normalize_solution_roles import normalize_roles
from remove_supporting import remove_supporting


class RemoveSupportingTests(unittest.TestCase):
    def fixture(self, root, missing=False):
        folder = root / "02" / "supporting"
        folder.mkdir(parents=True)
        (folder / "solution - Reviewer.tex").write_text(
            r"\includegraphics{figs/plot.png}" + "\n" + r"\bibliography{refs}")
        if not missing:
            (folder / "Submission/figs").mkdir(parents=True)
            (folder / "Submission/figs/plot.png").write_bytes(b"figure")
        (folder / "Submission").mkdir(exist_ok=True)
        (folder / "Submission/refs.bib").write_text("references")
        (folder / "unused.pdf").write_bytes(b"unneeded")
        (root / "manifest.json").write_text(json.dumps({
            "files": [], "source_subdirectory": "supporting"}))
        normalize_roles(root, records=[])
        (root / "02/expert_review.txt").write_text("review")

    def test_preserves_assets_and_canonicals_across_cleanup_and_regeneration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "solutions"
            self.fixture(root)
            self.assertEqual(remove_supporting(root), 1)
            text = (root / "02/solution.tex").read_text()
            self.assertNotIn("supporting/", text)
            self.assertEqual((root / "02/figs/plot.png").read_bytes(), b"figure")
            self.assertEqual((root / "02/refs.bib").read_text(), "references")
            self.assertEqual((root / "02/expert_review.txt").read_text(), "review")
            report = json.loads((root.parent / "solution_normalization_report.json").read_text())
            self.assertEqual(normalize_roles(root, records=[]), report)
            self.assertFalse(list(root.glob("*/supporting")))
            # Simulate a subsequent download and regeneration.
            supporting = root / "02/supporting"
            (supporting / "figs").mkdir(parents=True)
            (supporting / "figs/plot.png").write_bytes(b"figure")
            (supporting / "refs.bib").write_text("references")
            (supporting / "solution - Reviewer.tex").write_text(text + "\nNew derivation")
            refreshed = normalize_roles(root, records=[])
            self.assertIn("New derivation", (root / "02/solution.tex").read_text())
            self.assertFalse(list(root.glob("*/supporting")))
            item = refreshed["challenges"][2]["files"]["solution"]
            self.assertEqual(item["sha256"], hashlib.sha256((root / item["path"]).read_bytes()).hexdigest())

    def test_missing_asset_aborts_before_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "solutions"
            self.fixture(root, missing=True)
            with self.assertRaisesRegex(ValueError, "Missing referenced asset"):
                remove_supporting(root)
            self.assertTrue((root / "02/supporting/unused.pdf").exists())
            self.assertIn("supporting/", (root / "02/solution.tex").read_text())


if __name__ == "__main__":
    unittest.main()
