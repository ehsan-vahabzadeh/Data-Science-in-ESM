"""Behavior checks for the retained ERA5-only historical ML prototype."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import xarray as xr

import UKDayAheadWeatherML as ml


class LegacyMLTests(unittest.TestCase):
    def test_chronological_holdout_does_not_overlap_training(self):
        times = pd.date_range('2025-01-01', periods=24 * 100 + 1, freq='h')
        start, last_day, stop = ml.choose_periods(times, None, 10)
        self.assertEqual(last_day, pd.Timestamp('2025-04-10'))
        self.assertEqual(start, pd.Timestamp('2025-04-01'))
        self.assertEqual(times[stop], start)
        self.assertLess(times[stop - 1], start)

    def test_rejects_short_history_and_nonpositive_test_period(self):
        times = pd.date_range('2025-01-01', periods=24 * 20 + 1, freq='h')
        with self.assertRaisesRegex(SystemExit, 'at least 1'):
            ml.choose_periods(times, None, 0)
        with self.assertRaisesRegex(SystemExit, 'not enough history'):
            ml.choose_periods(times, None, 5)

    def test_wind_features_use_only_prior_values_for_lags(self):
        times = pd.date_range('2025-01-01', periods=200, freq='h')
        weather = ml.SiteWeather(pd.DataFrame(), pd.DataFrame({'grid_longitude': [1.0], 'grid_latitude': [52.0]}), np.arange(200, dtype=float).reshape(-1, 1), {})
        features, names = ml.make_features(weather, times, np.array([168]), np.array([0]), 'wind')
        self.assertEqual(names[:3], ['target_lag_24h', 'target_lag_48h', 'target_lag_168h'])
        np.testing.assert_array_equal(features[0, :3], [144, 120, 0])

    def test_wind_and_solar_test_periods_use_correct_hour_labels(self):
        times = pd.date_range('2025-01-01', periods=49, freq='h')
        day = pd.Timestamp('2025-01-02')
        wind = ml.test_indices(times, day, day, 'wind')
        solar = ml.test_indices(times, day, day, 'solar')
        self.assertEqual((times[wind[0]], times[wind[-1]]), (day, day + pd.Timedelta(hours=23)))
        self.assertEqual((times[solar[0]], times[solar[-1]]), (day + pd.Timedelta(hours=1), day + pd.Timedelta(days=1)))

    def test_legacy_model_trains_and_scores_a_synthetic_holdout(self):
        times = pd.date_range('2025-01-01', periods=400, freq='h')
        target = (5 + np.sin(np.arange(400) / 7)).reshape(-1, 1)
        weather = ml.SiteWeather(pd.DataFrame(), pd.DataFrame({'grid_longitude': [1.0], 'grid_latitude': [52.0]}), target, {})
        _, predicted, persistence, metrics = ml.fit_and_evaluate(weather, times, 'wind', 350, np.arange(350, 374), 1000)
        self.assertEqual((metrics['training_rows'], metrics['test_rows']), (182, 24))
        self.assertTrue(np.isfinite(predicted).all())
        self.assertAlmostEqual(metrics['mae'], float(np.mean(np.abs(target[350:374, 0] - predicted))), places=6)
        np.testing.assert_allclose(persistence, target[326:350, 0])

    def test_cutout_rejects_missing_hour(self):
        times = pd.to_datetime(['2025-01-01T00:00', '2025-01-01T02:00'])
        variables = {name: ('time', [1.0, 2.0]) for name in ('wnd100m', 'influx_direct', 'influx_diffuse', 'influx_toa', 'solar_altitude')}
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'gap.nc'
            xr.Dataset(variables, coords={'time': times}).to_netcdf(path, engine='scipy')
            with self.assertRaisesRegex(SystemExit, 'continuous hourly'):
                ml.open_cutout(path)


if __name__ == '__main__':
    unittest.main()
