import unittest
import numpy as np
from scripts.bias_adjustment import fit_bias, score_forecast


class BiasAdjustmentTests(unittest.TestCase):
    def test_training_offset_corrects_new_forecasts_without_test_reference(self):
        offset = fit_bias(np.array([4., 6.]), np.array([6., 8.]))
        self.assertEqual(offset, 2.)
        result = score_forecast(np.array([8., 10.]), np.array([10., 12.]), offset)
        self.assertEqual(result['raw_mae'], 2.)
        self.assertEqual(result['adjusted_mae'], 0.)
        self.assertEqual(result['adjusted_bias'], 0.)

    def test_adjusted_weather_is_not_negative_and_invalid_values_fail(self):
        result = score_forecast(np.array([1.]), np.array([0.]), -3.)
        self.assertEqual(result['adjusted_mae'], 0.)
        with self.assertRaises(ValueError):
            fit_bias(np.array([np.nan]), np.array([1.]))
        with self.assertRaises(ValueError):
            fit_bias(np.array([1., 2.]), np.array([1.]))


if __name__ == '__main__':
    unittest.main()
