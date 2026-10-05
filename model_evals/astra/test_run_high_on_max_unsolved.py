import tempfile
import unittest
from pathlib import Path

from model_evals.astra.run_high_on_max_unsolved import (
    EXPECTED_COUNTS,
    ORDER,
    build_target_ids,
    commands,
)
from model_evals.astra.run_corrected_suite import build_inputs, read_json


class AstraHighTargetedTests(unittest.TestCase):
    def test_selection_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            hle_data, _ = build_inputs(output)
            ids = build_target_ids(output)
            jobs = commands(output, 16, hle_data, ids)
            self.assertEqual({name: len(read_json(path)) for name, path in ids.items()}, EXPECTED_COUNTS)
        self.assertEqual(tuple(jobs), ORDER)
        for command in jobs.values():
            self.assertEqual(command[command.index("--reasoning-effort") + 1], "high")
            self.assertEqual(command[command.index("--rounds") + 1], "4")
            self.assertEqual(command[command.index("--judge-model") + 1], "claude-fable-5")
            self.assertIn("--use-tools", command)
            self.assertEqual(command[command.index("--web-search") + 1], "live")


if __name__ == "__main__":
    unittest.main()
