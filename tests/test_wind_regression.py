from datetime import date, datetime
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from eccodes import codes_grib_new_from_samples, codes_release, codes_set, codes_write
from scripts.wind_regression import match, read_fields, run_model, scores, split


class WindRegressionTests(unittest.TestCase):
    def test_grib_forecasts_select_requested_run_and_reject_duplicates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'forecast.grib'
            def write(step, mode):
                message = codes_grib_new_from_samples('regular_ll_sfc_grib2')
                try:
                    codes_set(message, 'shortName', '10u')
                    codes_set(message, 'dataDate', 20240101)
                    codes_set(message, 'dataTime', 1200)
                    codes_set(message, 'step', step)
                    with path.open(mode) as stream:
                        codes_write(message, stream)
                finally:
                    codes_release(message)
            write(6, 'wb')
            write(12, 'ab')
            _, fields = read_fields([path], forecast=True)
            self.assertEqual(set(fields), {(datetime(2024, 1, 2), '10u')})
            write(12, 'ab')
            with self.assertRaisesRegex(ValueError, 'Duplicate field'):
                read_fields([path], forecast=True)

    def test_speed_scores_use_reference_speed(self):
        reference = np.array([[1., 0.], [3., 0.]])
        raw = np.array([[2., 0.], [2., 0.]])
        corrected = reference.copy()
        result = scores(corrected, reference, raw, np.array([0, 1]))['all']
        self.assertEqual(result['raw']['speed_mae'], 1.)
        self.assertEqual(result['raw']['speed_rmse'], 1.)
        self.assertEqual(result['raw']['speed_r2'], 0.)
        self.assertEqual(result['corrected']['speed_r2'], 1.)

    def test_provisional_mask_cannot_score_final_test(self):
        result = subprocess.run([sys.executable, '-m', 'scripts.wind_regression', '--forecast', 'x', '--era5', 'y',
                                 '--grid', 'z', '--output', 'unused', '--provisional-mask'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('final test requires a verified geographic mask', result.stderr)

    def test_chronological_split_boundaries(self):
        self.assertEqual(split(date(2025, 6, 30)), 'train')
        self.assertEqual(split(date(2025, 7, 1)), 'validation')
        self.assertEqual(split(date(2025, 12, 31)), 'validation')
        self.assertEqual(split(date(2026, 1, 1)), 'test')

    def test_matching_coordinates_and_reporting_missing_times(self):
        forecast_grid = np.array([[50., -1.], [51., -1.]])
        reference_grid = forecast_grid[::-1]
        when = datetime(2024, 1, 1)
        fc = {(when, '10u'): np.array([1., 2.]), (when, '10v'): np.array([3., 4.])}
        ref = {(when, '10u'): np.array([12., 11.]), (when, '10v'): np.array([24., 23.])}
        with TemporaryDirectory() as tmp:
            mask = Path(tmp) / 'mask.csv'
            mask.write_text('latitude,longitude,region\n50,-1,onshore\n51,-1,offshore\n')
            data, missing, points = match(forecast_grid, fc, reference_grid, ref, mask, end=date(2024, 1, 1))
        np.testing.assert_allclose(data['train'][0][3], [[10., 20.], [10., 20.]])
        self.assertEqual(len(missing['train']), 3)
        self.assertEqual(points, {'onshore': 1, 'offshore': 1})

    def test_mask_rejects_invalid_region_and_duplicate_coordinates(self):
        grid = np.array([[50., -1.], [51., -1.]])
        with TemporaryDirectory() as tmp:
            mask = Path(tmp) / 'mask.csv'
            for rows in ('50,-1,onshore\n51,-1,offshore\n52,-1,offshroe\n',
                         '50,-1,onshore\n50,-1,offshore\n51,-1,offshore\n'):
                with self.subTest(rows=rows):
                    mask.write_text('latitude,longitude,region\n' + rows)
                    with self.assertRaises(ValueError):
                        match(grid, {}, grid, {}, mask, end=date(2024, 1, 1))

    def test_reference_coordinate_rounding_collision_is_rejected(self):
        grid = np.array([[50., -1.], [51., -1.]])
        reference_grid = np.array([[50., -1.], [50.00001, -1.], [51., -1.]])
        with TemporaryDirectory() as tmp:
            mask = Path(tmp) / 'mask.csv'
            mask.write_text('latitude,longitude,region\n50,-1,onshore\n51,-1,offshore\n')
            with self.assertRaisesRegex(ValueError, 'coordinates'):
                match(grid, {}, reference_grid, {}, mask, end=date(2024, 1, 1))

    def test_constant_reference_has_undefined_r_squared(self):
        reference = np.array([[1., 0.], [1., 0.]])
        result = scores(reference, reference, reference, np.array([0, 1]))
        self.assertIsNone(result['all']['corrected']['speed_r2'])

    def test_validation_selects_without_using_test_targets(self):
        def part(correction):
            base = np.array([[1, 0, 1, 12, 50, -1, 0], [2, 0, 2, 12, 51, -1, 1]], float)
            target = np.tile([correction, 0.], (2, 1))
            return [(base, np.zeros(2), np.zeros(2), target, base[:, :2] + target, np.array([0., 1.]))]
        ds = {'train': part(1), 'validation': part(1), 'test': part(50)}
        result = run_model(ds)
        self.assertAlmostEqual(result['validation'][result['selected_season_encoding']]['all']['corrected']['speed_mae'], 0.)
        self.assertAlmostEqual(result['test']['all']['corrected']['speed_mae'], 49.)
        self.assertAlmostEqual(result['test']['all']['raw']['speed_mae'], 50.)
        self.assertNotIn('test', run_model(ds, include_test=False))


if __name__ == '__main__': unittest.main()
