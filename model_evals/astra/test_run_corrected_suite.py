import tempfile
import unittest
from pathlib import Path

from model_evals.astra.run_corrected_suite import MODEL, ORDER, build_inputs, commands


class AstraCorrectedSuiteTests(unittest.TestCase):
    def test_protocol_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            hle, cmt = build_inputs(output)
            jobs = commands(output, 12, hle, cmt)
        self.assertEqual(ORDER, ("hle", "critpt", "cmt"))
        self.assertEqual(MODEL, "gpt-6-astra")
        self.assertEqual(set(jobs), {"hle", "cmt"})
        for command in jobs.values():
            self.assertEqual(command[command.index("--reasoning-effort") + 1], "max")
            self.assertEqual(command[command.index("--judge-model") + 1], "claude-fable-5")
            self.assertEqual(command[command.index("--judge-reasoning-effort") + 1], "high")
            self.assertEqual(command[command.index("--rounds") + 1], "4")
            self.assertIn("--use-tools", command)
            self.assertEqual(command[command.index("--web-search") + 1], "live")

    def test_frozen_denominators(self):
        with tempfile.TemporaryDirectory() as directory:
            hle, cmt = build_inputs(Path(directory))
            import json
            self.assertEqual(len(json.loads(hle.read_text())), 116)
            self.assertEqual(len(json.loads(cmt.read_text())), 49)


if __name__ == "__main__":
    unittest.main()
