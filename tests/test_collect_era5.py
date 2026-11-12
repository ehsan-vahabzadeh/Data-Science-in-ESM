import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock
from scripts.collect_era5 import fetch_result, monthly_requests, update_plan


class Era5PlanningTests(unittest.TestCase):
    def test_months_and_frequency_cover_leap_year_and_partial_last_month(self):
        jobs = dict(monthly_requests(date(2024, 2, 3)))
        self.assertEqual(len(jobs), 4)
        self.assertEqual(len(jobs['2024-01-wind']['day']), 31)
        self.assertEqual(jobs['2024-02-wind']['day'], ['01', '02', '03'])
        self.assertEqual(jobs['2024-01-wind']['time'], ['00:00', '06:00', '12:00', '18:00'])
        self.assertEqual(len(jobs['2024-01-solar']['time']), 24)
        self.assertEqual(len(dict(monthly_requests(date(2024, 2, 29)))['2024-02-solar']['day']), 29)

    def test_dates_before_project_period_are_rejected(self):
        with self.assertRaises(ValueError):
            list(monthly_requests(date(2023, 12, 31)))

    def test_pending_partial_month_can_extend_without_changing_submitted_jobs(self):
        manifest={'jobs':{}}
        update_plan(manifest,date(2024, 1, 4))
        update_plan(manifest,date(2024, 1, 5))
        self.assertEqual(manifest['jobs']['2024-01-wind']['request']['day'][-1], '05')
        manifest['jobs']['2024-01-wind']['state']='accepted'
        with self.assertRaises(ValueError):
            update_plan(manifest,date(2024, 1, 6))

    def test_download_verifies_checksum_and_preserves_conflicting_existing_file(self):
        metadata = Mock()
        metadata.json.return_value = {'asset': {'value': {'file:size': 3, 'file:checksum': '900150983cd24fb0d6963f7d28e17f72', 'href': 'https://example.invalid/file'}}}
        content = MagicMock()
        content.__enter__ = Mock(return_value=content)
        content.__exit__ = Mock(return_value=False)
        content.iter_content.return_value = [b'abc']
        session = Mock()
        session.get.side_effect = [metadata, content]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'batch.grib'
            self.assertEqual(fetch_result(session, 'https://example.invalid', 'job', path)[0], 3)
            self.assertEqual(path.read_bytes(), b'abc')
            path.write_bytes(b'different')
            session.get.side_effect = [metadata]
            with self.assertRaises(ValueError):
                fetch_result(session, 'https://example.invalid', 'job', path)
            self.assertEqual(path.read_bytes(), b'different')

    def test_download_accepts_provider_md5_with_omitted_leading_zero(self):
        metadata = Mock()
        metadata.json.return_value = {'asset': {'value': {'file:size': 1, 'file:checksum': 'cc175b9c0f1b6a831c399e269772661', 'href': 'https://example.invalid/file'}}}
        content = MagicMock()
        content.__enter__.return_value = content
        content.iter_content.return_value = [b'a']
        session = Mock()
        session.get.side_effect = [metadata, content]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'batch.grib'
            fetch_result(session, 'https://example.invalid', 'job', path)
            self.assertEqual(path.read_bytes(), b'a')


if __name__ == '__main__':
    unittest.main()
