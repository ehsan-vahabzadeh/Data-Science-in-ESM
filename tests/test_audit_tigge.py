import unittest
from datetime import date
import numpy as np
from scripts.audit_tigge import expected_fields, summarize_values


class AuditTests(unittest.TestCase):
    def test_expected_fields_include_each_day_lead_and_parameter(self):
        fields = expected_fields(date(2024, 2, 28), date(2024, 3, 1))
        self.assertEqual(len(fields), 60)
        self.assertIn((date(2024, 2, 29), 24, '10u'), fields)
        with self.assertRaises(ValueError): expected_fields(date(2024, 3, 1), date(2024, 2, 28))

    def test_cloud_overshoots_are_reported_without_changing_values(self):
        r = summarize_values('tcc', [np.array([-0.001, 25, 100.001, 101, np.nan])])
        self.assertEqual(r['nonfinite'], 1)
        self.assertEqual(r['below_zero'], 1)
        self.assertEqual(r['above_100'], 2)
        self.assertEqual(r['materially_outside'], 1)
        self.assertEqual(r['max'], 101)


if __name__ == '__main__': unittest.main()

class ExplorationTests(unittest.TestCase):
    def test_group_mean_uses_only_selected_grid_points(self):
        from scripts.explore_tigge import group_mean
        self.assertEqual(group_mean([2., 100., 4.], [0, 2]), 3.)
        with self.assertRaises(ValueError):
            group_mean([2.], [])
