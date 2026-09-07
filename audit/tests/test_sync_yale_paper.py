"""Network-free tests for the paper export's counting and coverage checks."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sync_yale_paper.py"
SPEC = importlib.util.spec_from_file_location("sync_yale_paper", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv_path = self.root / "audits.csv"
        self.template = {"benchmarks": [{"key": key, "name": name} for key, name in sync.DATASETS.items()]}
        self.rows = []
        manifest = {"benchmarks": {}}
        for dataset in sync.DATASETS.values():
            folder = self.root / dataset
            folder.mkdir()
            # Identical problem IDs in different datasets are valid.
            records = [{"problem_id": "a", "rule_based_binary_score": 1},
                       {"problem_id": "b", "rule_based_binary_score": 0}]
            content = "".join(json.dumps(row) + "\n" for row in records).encode()
            (folder / "responses.jsonl").write_bytes(content)
            manifest["benchmarks"][dataset] = {
                "selected_sha256": sync.digest(content), "selected_count": 2,
                "selected_problem_ids": ["a", "b"], "selected_counts": {"solved": 1, "unsolved": 1},
            }
            self.rows.append({"dataset": dataset, "source_problem_id": "b", "label": "GRADER_FAILURE", "note": "line one\nline two"})
        (self.root / "selection-manifest.json").write_text(json.dumps(manifest))

    def collect(self):
        with self.csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["dataset", "source_problem_id", "label", "note"])
            writer.writeheader()
            writer.writerows(self.rows)
        return sync.collect_results(self.csv_path, self.root, self.template)

    def test_counts_denominators_and_provenance(self):
        original = copy.deepcopy(self.template)
        data = self.collect()
        for row in data["benchmarks"]:
            self.assertEqual((row["evaluated"], row["rejected"], row["problem"], row["grader"], row["model"]), (2, 1, 0, 1, 0))
        self.assertEqual(data["source"]["audit_csv_sha256"], sync.digest(self.csv_path.read_bytes()))
        for dataset in sync.DATASETS.values():
            self.assertEqual(data["source"]["selected_responses_sha256"][dataset],
                             sync.digest((self.root / dataset / "responses.jsonl").read_bytes()))
        self.assertNotIn('evaluation_file', data['source'])
        self.assertEqual(self.template, original)

    def test_duplicate_unresolved_audit(self):
        self.rows.append(dict(self.rows[0], label="MODEL_FAILURE"))
        with self.assertRaisesRegex(ValueError, "Duplicate/unresolved"):
            self.collect()

    def test_preserves_additional_paper_benchmarks(self):
        extra = {"key": "CritPt", "name": "CritPt", "evaluated": 55, "rejected": 22,
                 "problem": 22, "grader": 0, "model": 0}
        self.template["benchmarks"].append(extra)
        data = self.collect()
        self.assertEqual(data["benchmarks"][-1], extra)
        self.assertEqual(set(data["source"]["validated_datasets"]), set(sync.DATASETS.values()))

    def test_duplicate_paper_benchmark(self):
        self.template["benchmarks"].append(dict(self.template["benchmarks"][0]))
        with self.assertRaisesRegex(ValueError, "unique benchmark keys"):
            self.collect()

    def test_all_three_label_mappings(self):
        self.rows[0]["label"] = "PROBLEM_FAILURE"
        self.rows[1]["label"] = "MODEL_FAILURE"
        data = self.collect()
        self.assertEqual(data["benchmarks"][0]["problem"], 1)
        self.assertEqual(data["benchmarks"][0]["grader"], 0)
        self.assertEqual(data["benchmarks"][1]["model"], 1)

    def test_generation_failure_preserves_paper_assets(self):
        self.collect()
        paper = self.root / "paper"
        for folder in ("code", "results", "tables", "figures"):
            (paper / folder).mkdir(parents=True)
        counts = paper / "results/audit_counts.json"
        counts.write_text(json.dumps(self.template))
        figure = paper / "figures/benchmark_accuracy.pdf"
        figure.write_bytes(b"original figure")
        original = counts.read_bytes()
        with patch.object(sync.subprocess, "run", side_effect=OSError("plot dependency missing")):
            with self.assertRaisesRegex(OSError, "plot dependency"):
                sync.sync(self.csv_path, self.root, paper, build_paper=False)
        self.assertEqual(counts.read_bytes(), original)
        self.assertEqual(figure.read_bytes(), b"original figure")
        self.assertFalse((paper / "results/audits_processed.csv").exists())

    def test_missing_audit(self):
        self.rows.pop()
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            self.collect()

    def test_audit_of_accepted_item(self):
        self.rows[0]["source_problem_id"] = "a"
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            self.collect()

    def test_unknown_label_or_dataset(self):
        for field in ("label", "dataset"):
            with self.subTest(field=field):
                old = self.rows[0][field]
                self.rows[0][field] = "unknown"
                with self.assertRaisesRegex(ValueError, "Invalid dataset"):
                    self.collect()
                self.rows[0][field] = old

    def test_changed_selection_export(self):
        path = self.root / "hle-physics/responses.jsonl"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.collect()


if __name__ == "__main__":
    unittest.main()
