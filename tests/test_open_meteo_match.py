"""Offline tests for pairing Open-Meteo forecasts and ERA5."""
import csv
import fcntl
import json
import sys
import tempfile
import urllib.parse
import unittest
from pathlib import Path
from datetime import date, datetime, timedelta
from unittest.mock import patch

import OpenMeteoMatch as match


def payload(lat, lon, wind=4.0, solar=100.0):
    start = datetime(2024, 3, 15)
    return {'latitude': lat, 'longitude': lon, 'utc_offset_seconds': 0,
            'hourly_units': {'wind_speed_100m': 'm/s', 'shortwave_radiation': 'W/m²'},
            'hourly': {'time': [(start + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(24)],
                       'wind_speed_100m': [wind] * 24, 'shortwave_radiation': [solar] * 24}}


class MatchingTests(unittest.TestCase):
    def test_same_times_leads_units_and_reference_minus_forecast(self):
        points = [{'latitude': 52.5, 'longitude': 1.0, 'region': 'onshore'}]
        rows = list(match.matched_rows(points, [payload(52.5, 1, 4, 100)], [payload(52.5, 1.25, 6, 120)], date(2024, 3, 15)))
        self.assertEqual(len(rows), 24)
        self.assertEqual((rows[0]['ifs_run_utc'], rows[0]['valid_time_utc'], rows[0]['forecast_lead_hours']), ('2024-03-14T12:00Z', '2024-03-15T00:00Z', 12))
        self.assertEqual((rows[-1]['valid_time_utc'], rows[-1]['forecast_lead_hours']), ('2024-03-15T23:00Z', 35))
        self.assertEqual(rows[0]['wind_reference_minus_forecast_ms'], 2.0)
        self.assertEqual(rows[0]['solar_reference_minus_forecast_wm2'], 20.0)
        self.assertGreater(rows[0]['grid_centre_distance_km'], 0)

    def test_missing_and_bad_units_are_not_silently_accepted(self):
        reference = payload(52.5, 1)
        reference['hourly']['shortwave_radiation'][0] = None
        rows = list(match.matched_rows([{'latitude': 52.5, 'longitude': 1, 'region': 'onshore'}], [payload(52.5, 1)], [reference], date(2024, 3, 15)))
        self.assertIsNone(rows[0]['solar_reference_minus_forecast_wm2'])
        reference['hourly_units']['wind_speed_100m'] = 'km/h'
        with self.assertRaisesRegex(ValueError, 'units'):
            list(match.matched_rows([{'latitude': 52.5, 'longitude': 1, 'region': 'onshore'}], [payload(52.5, 1)], [reference], date(2024, 3, 15)))

    def test_command_fetches_only_valid_era5_day_and_resumes(self):
        with tempfile.TemporaryDirectory() as temp:
            grid = Path(temp) / 'grid.csv'
            grid.write_text('latitude,longitude,region\n52.5,1.0,onshore\n')
            output = Path(temp) / 'out'
            output.mkdir()
            (output / 'matched-2024-03-15.part').write_text('stale partial output')
            calls = []
            def fake_request(endpoint, params):
                calls.append((endpoint, params))
                return {'url': 'https://example.test', 'retrieved_utc': '2024-03-16T00:00Z', 'data': payload(52.5, 1)}
            args = ['OpenMeteoMatch.py', '--start-date', '2024-03-15', '--end-date', '2024-03-15', '--output-dir', str(output)]
            with (patch.object(match, 'GRID', grid), patch.object(match, 'PREVIOUS_DATA', Path(temp) / 'none'), patch.object(match, 'request', side_effect=fake_request), patch.object(sys, 'argv', args)):
                match.main()
                match.main()
            self.assertEqual(len(calls), 2)
            forecast, reference = calls
            self.assertEqual((forecast[1]['run'], forecast[1]['forecast_hours']), ('2024-03-14T12:00', 36))
            self.assertEqual((reference[1]['start_date'], reference[1]['end_date']), ('2024-03-15', '2024-03-15'))
            with (output / 'matched-2024-03-15.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 24)
            self.assertEqual(rows[0]['valid_time_utc'], '2024-03-15T00:00Z')
            self.assertEqual(rows[-1]['valid_time_utc'], '2024-03-15T23:00Z')

    def test_multi_day_era5_block_is_reused_after_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            grid = base / 'grid.csv'
            grid.write_text('latitude,longitude,region\n52.5,1.0,onshore\n')
            output = base / 'out'
            calls = []
            interrupted = [False]
            def fake_request(endpoint, params):
                calls.append((endpoint, params.copy()))
                if endpoint == match.FORECAST and params['run'] == '2024-03-15T12:00' and not interrupted[0]:
                    interrupted[0] = True
                    raise RuntimeError('interrupted')
                value = payload(52.5, 1)
                start = date(2024, 3, 15)
                stamps = [(datetime.combine(start, datetime.min.time()) + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(48)]
                value['hourly'] = {'time': stamps, 'wind_speed_100m': [4.0] * 48, 'shortwave_radiation': [100.0] * 48}
                return {'url': endpoint + '?' + urllib.parse.urlencode(params), 'retrieved_utc': '2024-03-16T00:00Z', 'data': value}
            args = ['OpenMeteoMatch.py', '--start-date', '2024-03-15', '--end-date', '2024-03-16', '--output-dir', str(output)]
            with (patch.object(match, 'GRID', grid), patch.object(match, 'PREVIOUS_DATA', base / 'none'), patch.object(match, 'request', side_effect=fake_request), patch.object(sys, 'argv', args)):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    match.main()
                match.main()
            era5_calls = [params for endpoint, params in calls if endpoint == match.ARCHIVE]
            self.assertEqual(len(era5_calls), 1)
            self.assertEqual((era5_calls[0]['start_date'], era5_calls[0]['end_date']), ('2024-03-15', '2024-03-16'))
            for day in ('2024-03-15', '2024-03-16'):
                with (output / f'matched-{day}.csv').open() as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 24)
                self.assertTrue(all(row['valid_time_utc'].startswith(day) for row in rows))

    def test_era5_block_reused_across_daily_limited_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            grid = base / 'grid.csv'
            grid.write_text('latitude,longitude,region\n52.5,1.0,onshore\n')
            output = base / 'out'
            calls = []
            def fake_request(endpoint, params):
                calls.append((endpoint, params.copy()))
                value = payload(52.5, 1)
                start = datetime(2024, 3, 15)
                value['hourly'] = {'time': [(start + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(48)],
                                   'wind_speed_100m': [4.0] * 48, 'shortwave_radiation': [100.0] * 48}
                return {'url': endpoint + '?' + urllib.parse.urlencode(params), 'data': value}
            args = ['OpenMeteoMatch.py', '--start-date', '2024-03-15', '--end-date', '2024-03-16', '--max-days', '1', '--output-dir', str(output)]
            with (patch.object(match, 'GRID', grid), patch.object(match, 'PREVIOUS_DATA', base / 'none'), patch.object(match, 'request', side_effect=fake_request), patch.object(sys, 'argv', args)):
                match.main()
                match.main()
            self.assertEqual(sum(endpoint == match.ARCHIVE for endpoint, _ in calls), 1)
            self.assertEqual(sum(endpoint == match.FORECAST for endpoint, _ in calls), 2)
            self.assertTrue((output / 'matched-2024-03-15.csv').exists())
            self.assertTrue((output / 'matched-2024-03-16.csv').exists())

    def test_incomplete_latest_era5_day_does_not_cache_a_block(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            grid = base / 'grid.csv'
            grid.write_text('latitude,longitude,region\n52.5,1.0,onshore\n')
            output = base / 'out'
            def fake_request(endpoint, params):
                value = payload(52.5, 1)
                if endpoint == match.ARCHIVE:
                    start = datetime(2024, 3, 15)
                    value['hourly'] = {'time': [(start + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(48)],
                                       'wind_speed_100m': [4.0] * 24 + [None] * 24,
                                       'shortwave_radiation': [100.0] * 24 + [None] * 24}
                return {'url': endpoint + '?' + urllib.parse.urlencode(params), 'data': value}
            args = ['OpenMeteoMatch.py', '--start-date', '2024-03-15', '--end-date', '2024-03-16', '--output-dir', str(output)]
            with (patch.object(match, 'GRID', grid), patch.object(match, 'PREVIOUS_DATA', base / 'none'), patch.object(match, 'request', side_effect=fake_request), patch.object(sys, 'argv', args)):
                with self.assertRaisesRegex(SystemExit, '2024-03-16'):
                    match.main()
            self.assertFalse(list((output / 'raw/era5-blocks').glob('*.json')))
            self.assertFalse(list(output.glob('matched-*.csv')))

    def test_reuses_saved_source_data_before_requesting_new_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            grid = base / 'grid.csv'
            grid.write_text('latitude,longitude,region\n52.5,1.0,onshore\n')
            previous = base / 'previous' / '2024-03-15'
            previous.mkdir(parents=True)
            for label in ('ifs', 'era5'):
                params = 'models=ecmwf_ifs&run=2024-03-14T12%3A00' if label == 'ifs' else 'models=era5&start_date=2024-03-15&end_date=2024-03-15'
                url = 'https://example.test/?latitude=52.5&longitude=1.0&hourly=wind_speed_100m%2Cshortwave_radiation&wind_speed_unit=ms&timezone=GMT&cell_selection=nearest&elevation=nan&' + params
                (previous / f'{label}-000.json').write_text(json.dumps({'url': url, 'data': payload(52.5, 1)}))
            args = ['OpenMeteoMatch.py', '--start-date', '2024-03-15', '--end-date', '2024-03-15', '--output-dir', str(base / 'out')]
            with (patch.object(match, 'GRID', grid), patch.object(match, 'PREVIOUS_DATA', base / 'previous'), patch.object(match, 'request') as request, patch.object(sys, 'argv', args)):
                match.main()
            request.assert_not_called()
            self.assertTrue((base / 'out/raw/2024-03-15/reused-wider-area/ifs-000.json').exists())
            self.assertTrue((base / 'out/matched-2024-03-15.csv').exists())

    def test_overlapping_download_is_rejected_before_any_request(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            grid = base / 'grid.csv'
            grid.write_text('latitude,longitude,region\n52.5,1.0,onshore\n')
            output = base / 'out'
            output.mkdir()
            args = ['OpenMeteoMatch.py', '--start-date', '2024-03-15', '--end-date', '2024-03-15', '--output-dir', str(output)]
            with (output / '.download.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with (patch.object(match, 'GRID', grid), patch.object(match, 'request') as request, patch.object(sys, 'argv', args)):
                    with self.assertRaisesRegex(SystemExit, 'already running'):
                        match.main()
                    request.assert_not_called()

    def test_duplicate_times_fail_and_location_counts_must_match(self):
        bad = payload(52.5, 1)
        bad['hourly']['time'][1] = bad['hourly']['time'][0]
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            match.hourly(bad, date(2024, 3, 15))
        with self.assertRaisesRegex(ValueError, 'location count'):
            list(match.matched_rows([{'latitude': 52.5, 'longitude': 1, 'region': 'onshore'}], [], [], date(2024, 3, 15)))


if __name__ == '__main__':
    unittest.main()
