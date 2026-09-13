import unittest
from datetime import datetime, timezone

from icalendar import Event

from sync_notion import canonical_date, classify_event, component_to_record


class SyncNotionTests(unittest.TestCase):
    def test_normalises_equivalent_timezones(self):
        local = canonical_date("2026-09-24T14:15:00+01:00")
        notion = canonical_date("2026-09-24T13:15:00.000Z")
        self.assertEqual(local, notion)

    def test_classifies_course_sessions(self):
        self.assertEqual(classify_event("PBL: Thomas Allan"), "PBL")
        self.assertEqual(classify_event("IOD: White Cell Disorders"), "IoD")
        self.assertEqual(classify_event("CCS: Anaphylaxis"), "CCS")
        self.assertEqual(classify_event("Clinical placement"), "Placement")

    def test_builds_stable_timed_record(self):
        event = Event()
        event.add("uid", "abc@example.test")
        event.add("summary", "PBL: Test case")
        event.add("dtstart", datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc))
        event.add("dtend", datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc))
        event.add("location", "Room 1")

        record = component_to_record(event, "https://example.test/calendar.ics")

        self.assertEqual(record.event_type, "PBL")
        self.assertEqual(record.start, "2026-09-14T09:00:00+00:00")
        self.assertEqual(record.end, "2026-09-14T10:00:00+00:00")
        self.assertEqual(record.location, "Room 1")
        self.assertFalse(record.all_day)


if __name__ == "__main__":
    unittest.main()
