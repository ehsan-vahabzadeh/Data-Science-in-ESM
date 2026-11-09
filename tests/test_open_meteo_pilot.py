import json
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import OpenMeteoPilot as pilot


def response():
    start = datetime(2025, 10, 16)
    times = [(start + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(25)]
    return {'url': 'https://example.test', 'response': {
        'utc_offset_seconds': 0, 'latitude': 52.5, 'longitude': 1.5,
        'hourly_units': {'wind_speed_100m': 'm/s', 'shortwave_radiation': 'W/m²'},
        'hourly': {'time': times, 'wind_speed_100m': [5.0] * 25, 'shortwave_radiation': [100.0] * 25},
    }}


class PilotTests(unittest.TestCase):
    def test_solar_day_needs_midnight_at_end_of_day(self):
        payload = {'hourly': {'time': [f'2025-01-16T{hour:02}:00' for hour in range(24)],
                              'shortwave_radiation': [0] * 24}}
        self.assertEqual(pilot.target_values(payload, 'shortwave_radiation', date(2025, 1, 16))['missing_hours'], 1)
        payload['hourly']['time'].append('2025-01-17T00:00')
        payload['hourly']['shortwave_radiation'].append(0)
        self.assertEqual(pilot.target_values(payload, 'shortwave_radiation', date(2025, 1, 16))['missing_hours'], 0)

    def test_rejects_duplicate_times(self):
        payload = response()['response']
        payload['hourly']['time'][1] = payload['hourly']['time'][0]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            pilot.target_values(payload, 'wind_speed_100m', date(2025, 10, 16))

    def test_command_writes_audited_samples_without_overwriting(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / 'pilot.json'
            with (patch.object(pilot, 'OUTPUT', output),
                  patch.object(pilot, 'RUN_DATES', [date(2025, 10, 15)]),
                  patch.object(pilot, 'fetch', side_effect=lambda *args: response()) as fetch,
                  patch.object(sys, 'argv', ['OpenMeteoPilot.py'])):
                pilot.main()
                self.assertEqual(fetch.call_count, 4)
                saved = json.loads(output.read_text())
                self.assertEqual(len(saved['samples']), 2)
                sample = saved['samples'][0]
                self.assertEqual(sample['run_utc'], '2025-10-15T12:00Z')
                self.assertEqual(sample['target_day_utc'], '2025-10-16')
                self.assertEqual(sample['audit']['reference']['shortwave_radiation']['missing_hours'], 0)
                original = output.read_bytes()
                with self.assertRaisesRegex(SystemExit, 'Refusing to overwrite'):
                    pilot.main()
                self.assertEqual(output.read_bytes(), original)

    def test_command_rejects_incorrect_units(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / 'pilot.json'
            bad = response()
            bad['response']['hourly_units']['wind_speed_100m'] = 'km/h'
            with (patch.object(pilot, 'OUTPUT', output),
                  patch.object(pilot, 'RUN_DATES', [date(2025, 10, 15)]),
                  patch.object(pilot, 'fetch', return_value=bad),
                  patch.object(sys, 'argv', ['OpenMeteoPilot.py'])):
                with self.assertRaisesRegex(ValueError, 'units'):
                    pilot.main()
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
