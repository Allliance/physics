import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
import zipfile

from normalize_solutions import extraction_is_valid, normalize_archives
from download_drive_files import sync_files


def make_archive(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


class NormalizeSolutionsTests(unittest.TestCase):
    def test_extracts_nested_archives_updates_manifest_and_removes_zips(self):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr("solution.tex", "solution")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01/submission.zip"
            make_archive(source, {"problem.tex": "problem", "nested.zip": nested.getvalue()})
            entry = {"file_id": "abc", "path": "01/submission.zip", "paths": ["01/submission.zip"]}
            (root / "manifest.json").write_text(json.dumps({"files": [entry]}))
            result = normalize_archives(root)
            self.assertEqual(result["archives"], 2)
            self.assertFalse(list(root.rglob("*.zip")))
            self.assertEqual((root / "01/problem.tex").read_text(), "problem")
            self.assertEqual((root / "01/solution.tex").read_text(), "solution")
            entry = json.loads((root / "manifest.json").read_text())["files"][0]
            self.assertTrue(extraction_is_valid(entry, root))
            self.assertEqual({i["path"] for i in entry["extracted_files"]},
                             {"01/problem.tex", "01/solution.tex"})
            self.assertEqual(normalize_archives(root)["archives"], 0)

    def test_conflict_leaves_archive_and_existing_files_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01/submission.zip"
            make_archive(source, {"new.tex": "new", "solution.tex": "incoming"})
            (root / "01/solution.tex").write_text("local edit")
            with self.assertRaisesRegex(ValueError, "conflicts"):
                normalize_archives(root)
            self.assertTrue(source.exists())
            self.assertFalse((root / "01/new.tex").exists())
            self.assertEqual((root / "01/solution.tex").read_text(), "local edit")

    def test_path_traversal_leaves_archive_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01/submission.zip"
            make_archive(source, {"../escape.tex": "bad"})
            with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
                normalize_archives(root)
            self.assertTrue(source.exists())
            self.assertFalse((root / "escape.tex").exists())

    def test_corrupt_archive_is_not_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01/submission.zip"
            make_archive(source, {"solution.tex": "payload"})
            source.write_bytes(source.read_bytes().replace(b"payload", b"payloae"))
            with self.assertRaises(zipfile.BadZipFile):
                normalize_archives(root)
            self.assertTrue(source.exists())
            self.assertFalse((root / "01/solution.tex").exists())

    def test_sync_reuses_verified_extraction_without_downloading_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "01/submission.zip"
            make_archive(source, {"solution.tex": "solution"})
            blob = source.read_bytes()
            metadata = {"id": "abc", "name": "submission.zip", "mimeType": "application/zip",
                        "version": "1", "size": str(len(blob)),
                        "md5Checksum": hashlib.md5(blob).hexdigest()}
            fingerprint = {key: metadata.get(key) for key in
                           ("version", "modifiedTime", "md5Checksum", "size", "mimeType")}
            entry = {"file_id": "abc", "name": "submission.zip", "path": "01/submission.zip",
                     "paths": ["01/submission.zip"], "fingerprint": fingerprint,
                     "sha256": hashlib.sha256(blob).hexdigest()}
            (root / "manifest.json").write_text(json.dumps({"files": [entry]}))
            normalize_archives(root)
            response = MagicMock()
            response.__enter__.return_value = response
            response.status_code = 200
            response.json.return_value = metadata
            session = MagicMock()
            session.get.return_value = response
            result = sync_files(session, [{"Challenge ID": "1", "File uploads":
                                          "https://drive.google.com/open?id=abc"}], root)
            self.assertEqual(result, {"files": 1, "downloaded": 0, "cached": 1})
            self.assertEqual(session.get.call_count, 1)
            self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
