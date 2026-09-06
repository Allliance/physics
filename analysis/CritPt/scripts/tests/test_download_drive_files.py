import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

import download_drive_files as drive


def response(payload=None, content=b"hello", status=200, chunks=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.json.return_value = payload
    result.iter_content.return_value = [content] if chunks is None else chunks
    return result


def metadata(**updates):
    return {"id": "abc123", "name": "solution.pdf", "mimeType": "application/pdf",
            "version": "1", "size": "5", "md5Checksum": hashlib.md5(b"hello").hexdigest(),
            "capabilities": {"canDownload": True}, **updates}


RECORDS = [{"Challenge ID": "1", "File uploads": "https://drive.google.com/open?id=abc123"}]


class DownloadDriveTests(unittest.TestCase):
    def test_shared_file_is_cached_in_each_challenge_and_missing_copy_is_repaired(self):
        records = RECORDS + [{"Challenge ID": "2", "File uploads": RECORDS[0]["File uploads"]}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = MagicMock()
            session.get.side_effect = [response(metadata()), response()]
            self.assertEqual(drive.sync_files(session, records, root)["downloaded"], 1)
            self.assertEqual((root / "01/solution.pdf").read_bytes(), b"hello")
            self.assertEqual((root / "02/solution.pdf").read_bytes(), b"hello")
            (root / "01/solution.pdf").unlink()
            session.get.side_effect = [response(metadata())]
            self.assertEqual(drive.sync_files(session, records, root)["cached"], 1)
            self.assertEqual((root / "01/solution.pdf").read_bytes(), b"hello")

    def test_same_name_files_remain_distinct_and_reusable(self):
        records = [{"Challenge ID": "1", "File uploads":
                    "https://drive.google.com/open?id=abc123, https://drive.google.com/open?id=xyz"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = MagicMock()
            second = metadata(id="xyz", md5Checksum=hashlib.md5(b"world").hexdigest())
            session.get.side_effect = [response(metadata()), response(), response(second), response(content=b"world")]
            self.assertEqual(drive.sync_files(session, records, root)["downloaded"], 2)
            self.assertEqual((root / "01/solution.pdf").read_bytes(), b"hello")
            self.assertEqual((root / "01/solution__xyz.pdf").read_bytes(), b"world")
            session.get.side_effect = [response(metadata()), response(second)]
            self.assertEqual(drive.sync_files(session, records, root)["cached"], 2)

    def test_upload_notes_do_not_prevent_sync(self):
        records = [{"Challenge ID": "38", "File uploads": "I wrote in explanation.txt what the solution would look like."},
                   {"Challenge ID": "1", "File uploads": "See https://drive.google.com/open?id=abc123."}]
        self.assertEqual(set(drive.collect_files(records)), {"abc123"})
        self.assertIn("explanation.txt", records[0]["File uploads"])

    def test_comma_separated_google_form_uploads(self):
        files = drive.collect_files([{"Challenge ID": "48", "File uploads":
            "https://drive.google.com/open?id=abc123, https://drive.google.com/open?id=xyz"}])
        self.assertEqual(set(files), {"abc123", "xyz"})

    def test_links_deduplicate_and_preserve_challenge_mapping(self):
        records = RECORDS + [{"Challenge ID": "2", "File uploads":
            "https://drive.google.com/file/d/abc123/view;https://docs.google.com/document/d/xyz/edit?resourcekey=key-1"}]
        files = drive.collect_files(records)
        self.assertEqual(set(files), {"abc123", "xyz"})
        self.assertEqual(files["abc123"]["challenge_ids"], ["1", "2"])
        self.assertEqual(files["xyz"]["resource_key"], "key-1")
        with self.assertRaises(ValueError):
            drive.collect_files([{"Challenge ID": "1", "File uploads": "https://other.example/open?id=x"}])

    def test_download_cache_and_local_corruption_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = MagicMock()
            session.get.side_effect = [response(metadata()), response()]
            self.assertEqual(drive.sync_files(session, RECORDS, root)["downloaded"], 1)
            file_path = root / "01/solution.pdf"
            self.assertEqual(file_path.read_bytes(), b"hello")
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(manifest["files"][0]["challenge_ids"], ["1"])
            session.get.side_effect = [response(metadata())]
            self.assertEqual(drive.sync_files(session, RECORDS, root)["cached"], 1)
            file_path.write_bytes(b"corrupt")
            session.get.side_effect = [response(metadata()), response()]
            self.assertEqual(drive.sync_files(session, RECORDS, root)["downloaded"], 1)
            self.assertEqual(file_path.read_bytes(), b"hello")
            session.get.side_effect = [response(metadata(version="2")), response()]
            self.assertEqual(drive.sync_files(session, RECORDS, root)["downloaded"], 1)

    def test_native_document_export_and_safe_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = MagicMock()
            session.get.side_effect = [response(metadata(
                mimeType="application/vnd.google-apps.document", name="../../notes")), response()]
            drive.sync_files(session, RECORDS, root)
            call = session.get.call_args
            self.assertTrue(call.args[0].endswith("/abc123/export"))
            self.assertEqual(call.kwargs["params"], {"mimeType": "application/pdf"})
            entry = json.loads((root / "manifest.json").read_text())["files"][0]
            path = root / entry["path"]
            self.assertEqual(path.parent, root / "01")
            self.assertEqual(path.suffix, ".pdf")
            self.assertEqual(path.read_bytes(), b"hello")

    def test_dry_run_checks_metadata_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "solutions"
            session = MagicMock()
            session.get.side_effect = [response(metadata())]
            result = drive.sync_files(session, RECORDS, root, dry_run=True)
            self.assertEqual(result, {"files": 1, "downloaded": 0, "cached": 0})
            self.assertFalse(root.exists())
            self.assertEqual(session.get.call_count, 1)

    def test_incomplete_download_preserves_old_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing.pdf"
            destination.write_bytes(b"original")
            session = MagicMock()
            session.get.return_value = response(content=b"hi")
            with self.assertRaisesRegex(ValueError, "Incomplete download"):
                drive.download(session, "url", {"alt": "media"}, {}, destination, metadata())
            self.assertEqual(destination.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_checksum_failure_and_stream_failure_preserve_old_copy(self):
        def interrupted():
            yield b"he"
            raise OSError("connection lost")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing.pdf"
            destination.write_bytes(b"original")
            session = MagicMock()
            for download_response, error in [(response(content=b"wrong"), ValueError),
                                              (response(chunks=interrupted()), OSError)]:
                session.get.return_value = download_response
                with self.assertRaises(error):
                    drive.download(session, "url", {"alt": "media"}, {}, destination, metadata())
                self.assertEqual(destination.read_bytes(), b"original")
                self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_permission_failure_does_not_write_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            session = MagicMock()
            session.get.return_value = response(status=403)
            with self.assertRaisesRegex(ValueError, "share the file"):
                drive.sync_files(session, RECORDS, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
