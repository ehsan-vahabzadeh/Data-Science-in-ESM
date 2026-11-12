import unittest
from datetime import date, timedelta
import numpy as np
from scripts.daily_year_comparison import daily_means, pair_relative_differences


class DailyComparisonTests(unittest.TestCase):
    def test_relative_differences_pair_same_calendar_day_and_exclude_leap_day(self):
        rows=[]
        for year in (2024, 2025):
            day=date(year,1,1)
            while day.year == year:
                for region in ('onshore', 'offshore'):
                    rows.append({'valid_date':str(day),'region':region,'wind_m_s':2. if year==2024 else 3.,'net_solar_w_m2':10.})
                day+=timedelta(days=1)
        pairs=pair_relative_differences(rows)
        self.assertEqual(len(pairs),730)
        self.assertEqual(pairs[0]['wind_percent'],50.)
        self.assertTrue(np.isnan(pairs[0]['solar_percent']))
        self.assertFalse(any(r['month_day']=='02-29' for r in pairs))

    def test_daily_wind_and_full_day_solar_for_selected_points(self):
        u=[np.array([3.,100.]) for _ in range(4)]
        v=[np.array([4.,100.]) for _ in range(4)]
        wind,solar=daily_means(u,v,np.array([86400.,0.]),np.array([259200.,0.]),np.array([True,False]))
        self.assertAlmostEqual(wind,5.)
        self.assertAlmostEqual(solar,2.)

    def test_missing_times_are_rejected(self):
        with self.assertRaises(ValueError):
            daily_means([],[],np.array([0]),np.array([1]),np.array([True]))


if __name__=='__main__':unittest.main()
