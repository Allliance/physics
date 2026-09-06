import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from solution_layout import challenge_folder, organize_files


def write_legacy_manifest(root, specs):
    entries = []
    for file_id, challenge_ids, content in specs:
        path = f"{file_id}/solution.tex"
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        entries.append({"file_id": file_id, "challenge_ids": challenge_ids,
                        "path": path, "name": "solution.tex",
                        "sha256": hashlib.sha256(content).hexdigest()})
    (root / "manifest.json").write_text(json.dumps({"files": entries}))
    return entries


class SolutionLayoutTests(unittest.TestCase):
    def test_reorganization_preserves_collisions_and_shared_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_legacy_manifest(root, [("abc", ["1"], b"first"),
                                         ("xyz", ["1", "2"], b"second")])
            self.assertEqual(organize_files(root), 2)
            self.assertEqual((root / "01/solution.tex").read_bytes(), b"first")
            self.assertEqual((root / "01/solution__xyz.tex").read_bytes(), b"second")
            self.assertEqual((root / "02/solution.tex").read_bytes(), b"second")
            self.assertFalse((root / "abc").exists())
            self.assertFalse((root / "xyz").exists())
            self.assertEqual({p.name for p in root.iterdir() if p.is_dir()},
                             {f"{number:02d}" for number in range(71)})
            manifest = (root / "manifest.json").read_bytes()
            self.assertEqual(organize_files(root), 2)
            # Paths and contents must remain stable when organizing again.
            self.assertEqual((root / "manifest.json").read_bytes(), manifest)

    def test_conflicting_destination_preserves_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_legacy_manifest(root, [("abc", ["1"], b"original")])
            (root / "01").mkdir()
            (root / "01/solution.tex").write_bytes(b"unrelated")
            old_manifest = (root / "manifest.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "different file"):
                organize_files(root)
            self.assertEqual((root / "abc/solution.tex").read_bytes(), b"original")
            self.assertEqual((root / "01/solution.tex").read_bytes(), b"unrelated")
            self.assertEqual((root / "manifest.json").read_bytes(), old_manifest)

    def test_modified_source_is_not_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_legacy_manifest(root, [("abc", ["1"], b"original")])
            (root / "abc/solution.tex").write_bytes(b"edited")
            with self.assertRaisesRegex(ValueError, "changed source"):
                organize_files(root)
            self.assertFalse((root / "01").exists())
            self.assertEqual((root / "abc/solution.tex").read_bytes(), b"edited")

    def test_invalid_challenge_ids_are_rejected(self):
        self.assertEqual(challenge_folder("1"), "01")
        self.assertEqual(challenge_folder("00"), "00")
        for value in ("../1", "-1", "71", "example"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                challenge_folder(value)


if __name__ == "__main__":
    unittest.main()
