# merged-calendar2

Automatically merges two university calendar feeds into one subscription calendar.

- Learn/Blackboard is authoritative for event title, start time, end time and duration.
- Scientia is used only to add the matching room/location.
- Source feed URLs are stored as GitHub Actions secrets and are not committed to the repository.
- `merged_calendar.ics` is regenerated automatically each day.

## Calendar subscription

https://raw.githubusercontent.com/byroad-fisher/merged-calendar2/main/merged_calendar.ics
