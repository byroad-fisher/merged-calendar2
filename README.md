# merged-calendar2

Automatically merges two university calendar feeds into one subscription calendar and can synchronise the result to a native Notion calendar.

- Learn/Blackboard is authoritative for event title, start time, end time and duration.
- Scientia is used only to add the matching room/location.
- Source feed URLs and the Notion token are stored as GitHub Actions secrets.
- `merged_calendar.ics` is regenerated automatically each day.
- `sync_notion.py` creates, updates and archives Notion event pages by stable calendar UID. Re-running it does not duplicate unchanged events.

## Calendar subscription

https://raw.githubusercontent.com/byroad-fisher/merged-calendar2/main/merged_calendar.ics

## Native Notion calendar sync

The daily workflow can push the 2026–27 timetable into the **University Timetable** database in the MBBS T-Year Hub. Notion then displays the database through a native calendar view, including event times, type and location.

1. Create an internal Notion integration with read and update content capabilities.
2. In Notion, open the **University Timetable** database, use **Connections**, and grant the integration access.
3. In this repository, open **Settings → Secrets and variables → Actions** and add:
   - `NOTION_TOKEN`: the internal integration secret.
   - `NOTION_DATA_SOURCE_ID`: the data source ID of the University Timetable database.
4. Run **Merge Calendars Daily** from the Actions tab once. Future runs occur daily.

The sync window is configured in `.github/workflows/merge_calendars.yml` using `SYNC_FROM` and `SYNC_UNTIL`. Missing events within that window are archived in Notion, so cancellations and timetable removals do not leave stale cards behind.

The initial import may take a few minutes because the Notion API is rate-limited. Later runs normally update only changed events.

## Local validation

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
CALENDAR_FILE=merged_calendar.ics python sync_notion.py --dry-run
```
