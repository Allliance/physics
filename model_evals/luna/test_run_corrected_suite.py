import tempfile
import unittest
from pathlib import Path

from model_evals.luna.run_corrected_suite import MODEL, ORDER, commands


class CorrectedSuiteTests(unittest.TestCase):
    def test_order_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs = commands(Path(directory), 7)
        self.assertEqual(tuple(jobs), ORDER)
        for benchmark, command in jobs.items():
            self.assertEqual(command[command.index('--model') + 1], MODEL)
            self.assertEqual(command[command.index('--judge-model') + 1], 'claude-fable-5')
            self.assertEqual(command[command.index('--reasoning-effort') + 1], 'high')
            self.assertEqual(command[command.index('--judge-reasoning-effort') + 1], 'high')
            self.assertEqual(command[command.index('--workers') + 1] if '--workers' in command
                             else command[command.index('--num-workers') + 1], '7')
        self.assertNotIn('--rounds', jobs['phybench'])
        for benchmark in ORDER[:3]:
            self.assertIn('--data', jobs[benchmark])
            self.assertTrue(jobs[benchmark][jobs[benchmark].index('--data') + 1].endswith(
                f'{benchmark}/corrected/dataset.json'))
        for benchmark in ORDER[3:]:
            self.assertEqual(jobs[benchmark][jobs[benchmark].index('--rounds') + 1], '4')
            self.assertIn('--no-use-tools', jobs[benchmark])


if __name__ == '__main__':
    unittest.main()
