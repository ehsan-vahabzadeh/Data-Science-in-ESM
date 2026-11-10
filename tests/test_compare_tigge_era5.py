import unittest
import numpy as np
from scripts.compare_tigge_era5 import absolute_relative_error, on_grid, six_hour_solar


class CompareTests(unittest.TestCase):
    def test_relative_difference_uses_mean_reference_and_masks_small_values(self):
        result = absolute_relative_error(np.array([[0., 1.], [0., 1.]]), np.array([[2., 0.], [4., 0.]]), 1.)
        self.assertAlmostEqual(result[0], 100.)
        self.assertTrue(np.isnan(result[1]))

    def test_solar_compares_six_hour_intervals(self):
        forecast, reference = six_hour_solar(np.array([540000.]), np.array([108000.]), [np.array([54000.])] * 6)
        np.testing.assert_allclose(forecast, [20.])
        np.testing.assert_allclose(reference, [15.])
        with self.assertRaises(ValueError):
            six_hour_solar(np.array([1.]), np.array([0.]), [])

    def test_grid_matches_coordinates_not_array_position(self):
        field = (np.array([51., 50.]), np.array([-1., -1.]), np.array([7., 3.]))
        np.testing.assert_array_equal(on_grid(field, [50., 51.], [-1., -1.]), [3., 7.])
        with self.assertRaises(ValueError):
            on_grid(field, [52.], [-1.])


if __name__ == '__main__':
    unittest.main()
