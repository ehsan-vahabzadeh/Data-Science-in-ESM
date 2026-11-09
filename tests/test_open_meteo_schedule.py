"""Checks for the prepared macOS schedule (no installation or network)."""
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ScheduleTests(unittest.TestCase):
    def test_prepare_daily_resumable_job_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'job.plist'
            command = [sys.executable, str(ROOT / 'scripts/create_openmeteo_schedule.py'), '--output', str(path)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with path.open('rb') as f:
                job = plistlib.load(f)
            self.assertEqual(job['WorkingDirectory'], str(ROOT))
            self.assertEqual(job['StartCalendarInterval'], {'Hour': 2, 'Minute': 15})
            self.assertEqual(job['ProgramArguments'][-2:], ['--max-days', '5'])
            original = path.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
