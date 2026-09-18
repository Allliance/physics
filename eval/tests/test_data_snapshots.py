import hashlib
import json
from pathlib import Path
import unittest

from eval.datasets import DATA_ROOT, load_dataset
from eval.pre_audit import load_benchmark


class DataSnapshotTests(unittest.TestCase):
    def test_manifest_hashes_and_counts(self):
        manifest = json.loads((DATA_ROOT / "manifest.json").read_text())
        expected = {
            "phybench": (100, 87), "hle-physics": (202, 116),
            "prism": (100, 74), "ugphysics": (100, 82),
            "cmt": (50, 49), "critpt": (55, 54),
        }
        for name, (pre_count, post_count) in expected.items():
            with self.subTest(name=name):
                entries = manifest["benchmarks"][name]
                for entry in entries.values():
                    path = DATA_ROOT / entry["file"]
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                     entry["sha256"])
                self.assertEqual(len(load_benchmark(name).problems), pre_count)
                self.assertEqual(len(load_dataset(name)[0]), post_count)

    def test_cmt_and_critpt_explicit_post_audit_exclusions(self):
        manifest = json.loads((DATA_ROOT / "manifest.json").read_text())["benchmarks"]
        self.assertEqual(manifest["cmt"]["post_audit"]["excluded"],
                         [{"id": "14", "reason": "UNREPAIRABLE"}])
        self.assertEqual({item["id"] for item in
                          manifest["critpt"]["post_audit"]["excluded"]},
                         {"41", "46"})


if __name__ == "__main__":
    unittest.main()
