import copy
import os
from datetime import date, datetime, time, timezone

import requests
from icalendar import Calendar

# Learn supplies event details; Scientia supplies room/location only.
OUTPUT_FILE = "merged_calendar.ics"
START_TOLERANCE_SECONDS = 30 * 60


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def fetch_ics_file(url):
    """Fetch and parse an iCalendar feed."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return Calendar.from_ical(response.content)


def iter_events(calendar):
    """Return VEVENT components from a calendar."""
    return [component for component in calendar.walk() if component.name == "VEVENT"]


def as_datetime(value, end_of_day=False):
    """Normalise DATE and DATE-TIME values to timezone-aware datetimes."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, date):
        t = time.max if end_of_day else time.min
        return datetime.combine(value, t, tzinfo=timezone.utc)

    raise TypeError(f"Unsupported calendar date type: {type(value)!r}")


def event_bounds(event):
    """Return an event's start and end as UTC datetimes."""
    start = as_datetime(event.decoded("dtstart"))

    if event.get("dtend") is not None:
        end = as_datetime(event.decoded("dtend"), end_of_day=True)
    elif event.get("duration") is not None:
        end = start + event.decoded("duration")
    else:
        end = start

    return start, end


def match_score(learning_event, scientia_event):
    """Score two events using timing only.

    Titles are deliberately ignored because the two source feeds describe the
    same teaching session differently. Start time is the strongest signal;
    overlap is used as a tie-breaker when durations differ.
    """
    learning_start, learning_end = event_bounds(learning_event)
    scientia_start, scientia_end = event_bounds(scientia_event)

    if learning_start.date() != scientia_start.date():
        return None

    overlap_seconds = max(
        0.0,
        (min(learning_end, scientia_end) - max(learning_start, scientia_start)).total_seconds(),
    )
    start_difference = abs((learning_start - scientia_start).total_seconds())

    if overlap_seconds > 0:
        return (2, -start_difference, overlap_seconds)

    if start_difference <= START_TOLERANCE_SECONDS:
        return (1, -start_difference, 0.0)

    return None


def merge_calendars(learning_cal, scientia_cal):
    """Use Learn as the authoritative calendar and add rooms from Scientia."""
    merged_cal = copy.deepcopy(learning_cal)
    learning_events = iter_events(merged_cal)
    scientia_events = iter_events(scientia_cal)

    unused_scientia = set(range(len(scientia_events)))
    matched = 0
    matched_with_location = 0

    for learning_event in learning_events:
        best_index = None
        best_score = None

        for index in unused_scientia:
            score = match_score(learning_event, scientia_events[index])
            if score is not None and (best_score is None or score > best_score):
                best_score = score
                best_index = index

        if best_index is None:
            continue

        unused_scientia.remove(best_index)
        matched += 1

        scientia_location = str(scientia_events[best_index].get("location", "")).strip()
        if scientia_location:
            learning_event["location"] = scientia_location
            matched_with_location += 1

    print(
        "Merge summary: "
        f"{len(learning_events)} Learn events, "
        f"{len(scientia_events)} Scientia events, "
        f"{matched} matched, "
        f"{matched_with_location} rooms copied, "
        f"{len(unused_scientia)} Scientia events unused."
    )

    return merged_cal


def main():
    learning_calendar_url = require_env("LEARNING_CALENDAR_URL")
    scientia_calendar_url = require_env("SCIENTIA_CALENDAR_URL")

    learning_cal = fetch_ics_file(learning_calendar_url)
    scientia_cal = fetch_ics_file(scientia_calendar_url)
    merged_cal = merge_calendars(learning_cal, scientia_cal)

    with open(OUTPUT_FILE, "wb") as output:
        output.write(merged_cal.to_ical())

    print(f"Successfully merged calendars. Output saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
