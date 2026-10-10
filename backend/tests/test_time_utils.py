import unittest
from datetime import datetime, timedelta, timezone

from time_utils import utc_iso


class TimestampTests(unittest.TestCase):
    def test_database_utc_and_offset_timestamps_have_same_wire_format(self):
        self.assertEqual(utc_iso(datetime(2026, 10, 10, 12)), '2026-10-10T12:00:00Z')
        self.assertEqual(utc_iso(datetime(2026, 10, 10, 15, tzinfo=timezone(timedelta(hours=3)))),
                         '2026-10-10T12:00:00Z')
        self.assertIsNone(utc_iso(None))
