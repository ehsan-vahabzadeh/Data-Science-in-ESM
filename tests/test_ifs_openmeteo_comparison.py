"""Checks for the comparison command's public interface."""
import csv
import json
import os
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'IFSVsOpenMeteo.py'


class ComparisonCommandTests(unittest.TestCase):
    def test_help_describes_three_day_comparison(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--end-date', result.stdout)
        self.assertIn('--output-dir', result.stdout)

    @unittest.skipUnless(os.environ.get('IFS_COMPARISON_TEST_DATA'), 'needs the cached real-data sample')
    def test_cached_three_day_comparison_produces_matched_maps_and_values(self):
        # Independent worked example for 52°N, 1°E on 4 November 2026:
        # direct accumulated solar: 179.01037 W/m²; Open-Meteo hourly
        # means 141, 186, 201 W/m² => 176 W/m² over 09:00–12:00 UTC.
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(SCRIPT), '--end-date', '2026-11-06',
                '--data-dir', os.environ['IFS_COMPARISON_TEST_DATA'], '--output-dir', temp],
                capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(temp) / '2026-11-04_to_2026-11-06'
            meta = json.loads((output / 'metadata.json').read_text())
            self.assertEqual(meta['wind_valid_hour_utc'], 12)
            self.assertEqual(meta['solar_interval_utc'], '09:00–12:00')
            with (output / 'grid-points.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 3 * 134)
            row = next(r for r in rows if r['run_date_utc'] == '2026-11-04' and float(r['latitude']) == 52 and float(r['longitude']) == 1)
            self.assertAlmostEqual(float(row['ecmwf_wind_ms']), 10.634511, places=5)
            self.assertAlmostEqual(float(row['openmeteo_wind_ms']), 10.61, places=2)
            self.assertAlmostEqual(float(row['ecmwf_solar_wm2']), 179.01037, places=4)
            self.assertEqual(float(row['openmeteo_solar_wm2']), 176)
            for day in ('04', '05', '06'):
                self.assertEqual((output / f'comparison-2026-11-{day}.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')


if __name__ == '__main__':
    unittest.main()
