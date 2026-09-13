"""Synchronise merged_calendar.ics into a native Notion calendar database."""

from __future__ import annotations

import argparse
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any

import recurring_ical_events
import requests
from icalendar import Calendar

NOTION_API = "https://api.notion.com/v1"
DEFAULT_API_VERSION = "2025-09-03"
DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/byroad-fisher/merged-calendar2/"
    "main/merged_calendar.ics"
)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def parse_boundary(value: str, *, end: bool = False) -> datetime:
    parsed = date.fromisoformat(value)
    clock = dt_time.max if end else dt_time.min
    return datetime.combine(parsed, clock, tzinfo=timezone.utc)


def decoded(component: Any, name: str, default: Any = None) -> Any:
    try:
        return component.decoded(name)
    except (KeyError, AttributeError):
        return default


def iso_value(value: date | datetime) -> tuple[str, bool]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat(), False
    return value.isoformat(), True


def classify_event(title: str) -> str:
    upper = title.upper()
    if "PBL" in upper:
        return "PBL"
    if "IOD" in upper or "INVESTIGATION OF DISEASE" in upper:
        return "IoD"
    if "CCS" in upper or "CLINICAL AND COMMUNICATION" in upper:
        return "CCS"
    if any(word in upper for word in ("PLACEMENT", "CLINICAL ATTACHMENT", "INDUCTION")):
        return "Placement"
    if any(word in upper for word in ("EXAM", "YSKT", "OSCE", "ASSESSMENT")):
        return "Assessment"
    if any(word in upper for word in ("ONLINE", "ELEARNING", "E-LEARNING")):
        return "Online"
    return "Lecture" if title.strip() else "Other"


def text_value(value: Any, limit: int = 1900) -> str:
    return str(value or "").replace("\\n", "\n").strip()[:limit]


@dataclass(frozen=True)
class EventRecord:
    key: str
    title: str
    start: str
    end: str | None
    all_day: bool
    event_type: str
    location: str
    description: str
    source_url: str
    status: str

    def comparable(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "all_day": self.all_day,
            "event_type": self.event_type,
            "location": self.location,
            "description": self.description,
            "source_url": self.source_url,
            "status": self.status,
        }

    def notion_properties(self, synced_at: str) -> dict[str, Any]:
        return {
            "Event": {"title": [{"type": "text", "text": {"content": self.title}}]},
            "When": {"date": {"start": self.start, "end": self.end}},
            "Type": {"select": {"name": self.event_type}},
            "Location": rich_text(self.location),
            "Description": rich_text(self.description),
            "Source URL": {"url": self.source_url or None},
            "Event Key": rich_text(self.key),
            "Status": {"select": {"name": self.status}},
            "All Day": {"checkbox": self.all_day},
            "Last Synced": {"date": {"start": synced_at}},
        }


def rich_text(value: str) -> dict[str, Any]:
    if not value:
        return {"rich_text": []}
    return {"rich_text": [{"type": "text", "text": {"content": value}}]}


def event_key(component: Any, start: str) -> str:
    uid = text_value(component.get("uid"), 1000)
    recurring = component.get("rrule") is not None or component.get("recurrence-id") is not None
    raw = f"{uid}|{start}" if recurring else uid
    if not raw:
        raw = f"{text_value(component.get('summary'))}|{start}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def component_to_record(component: Any, source_url: str) -> EventRecord:
    start_value = decoded(component, "dtstart")
    end_value = decoded(component, "dtend")
    if start_value is None:
        raise ValueError("Calendar event has no DTSTART")

    start, all_day = iso_value(start_value)
    end: str | None = None
    if end_value is not None:
        end, _ = iso_value(end_value)
    elif decoded(component, "duration") is not None and isinstance(start_value, datetime):
        end, _ = iso_value(start_value + decoded(component, "duration"))

    title = text_value(component.get("summary") or "Untitled event")
    event_url = text_value(component.get("url"), 1900) or source_url
    status = "Cancelled" if text_value(component.get("status")).upper() == "CANCELLED" else "Scheduled"
    return EventRecord(
        key=event_key(component, start),
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        event_type=classify_event(title),
        location=text_value(component.get("location")),
        description=text_value(component.get("description")),
        source_url=event_url,
        status=status,
    )


def load_events(path: Path, start: datetime, end: datetime, source_url: str) -> dict[str, EventRecord]:
    calendar = Calendar.from_ical(path.read_bytes())
    components = recurring_ical_events.of(calendar).between(start, end)
    records: dict[str, EventRecord] = {}
    for component in components:
        record = component_to_record(component, source_url)
        if record.key in records:
            raise RuntimeError(f"Duplicate event key generated for {record.title!r}")
        records[record.key] = record
    return records


def plain_text(items: list[dict[str, Any]] | None) -> str:
    return "".join(item.get("plain_text", "") for item in (items or []))


def existing_record(page: dict[str, Any]) -> dict[str, Any]:
    props = page["properties"]
    when = props.get("When", {}).get("date") or {}
    return {
        "title": plain_text(props.get("Event", {}).get("title")),
        "start": when.get("start"),
        "end": when.get("end"),
        "all_day": bool(props.get("All Day", {}).get("checkbox")),
        "event_type": (props.get("Type", {}).get("select") or {}).get("name"),
        "location": plain_text(props.get("Location", {}).get("rich_text")),
        "description": plain_text(props.get("Description", {}).get("rich_text")),
        "source_url": props.get("Source URL", {}).get("url") or "",
        "status": (props.get("Status", {}).get("select") or {}).get("name"),
    }


class NotionClient:
    def __init__(self, token: str, data_source_id: str, api_version: str) -> None:
        self.data_source_id = data_source_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": api_version,
            "Content-Type": "application/json",
        })

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(6):
            response = self.session.request(method, f"{NOTION_API}{path}", timeout=30, **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            if attempt == 5:
                response.raise_for_status()
            time.sleep(float(response.headers.get("Retry-After", "1")))
        raise AssertionError("unreachable")

    def list_pages(self) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        payload: dict[str, Any] = {"page_size": 100}
        while True:
            result = self.request("POST", f"/data_sources/{self.data_source_id}/query", json=payload)
            pages.extend(result["results"])
            if not result.get("has_more"):
                return pages
            payload["start_cursor"] = result["next_cursor"]

    def create(self, properties: dict[str, Any]) -> None:
        self.request("POST", "/pages", json={
            "parent": {"type": "data_source_id", "data_source_id": self.data_source_id},
            "properties": properties,
            "icon": {"type": "emoji", "emoji": "📅"},
        })

    def update(self, page_id: str, properties: dict[str, Any]) -> None:
        self.request("PATCH", f"/pages/{page_id}", json={"properties": properties})

    def archive(self, page_id: str) -> None:
        self.request("PATCH", f"/pages/{page_id}", json={"archived": True})


def sync(client: NotionClient, desired: dict[str, EventRecord], dry_run: bool) -> None:
    pages = client.list_pages()
    existing: dict[str, dict[str, Any]] = {}
    for page in pages:
        key = plain_text(page["properties"].get("Event Key", {}).get("rich_text"))
        if key:
            existing[key] = page

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    created = updated = unchanged = archived = 0
    for key, record in desired.items():
        page = existing.pop(key, None)
        if page is None:
            created += 1
            if not dry_run:
                client.create(record.notion_properties(now))
                time.sleep(0.35)
        elif existing_record(page) != record.comparable():
            updated += 1
            if not dry_run:
                client.update(page["id"], record.notion_properties(now))
                time.sleep(0.35)
        else:
            unchanged += 1

    for page in existing.values():
        archived += 1
        if not dry_run:
            client.archive(page["id"])
            time.sleep(0.35)

    print(
        f"Notion sync: {len(desired)} source events; {created} created, "
        f"{updated} updated, {unchanged} unchanged, {archived} archived."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    calendar_path = Path(os.environ.get("CALENDAR_FILE", "merged_calendar.ics"))
    start = parse_boundary(os.environ.get("SYNC_FROM", "2026-08-01"))
    end = parse_boundary(os.environ.get("SYNC_UNTIL", "2027-07-31"), end=True)
    source_url = os.environ.get("ICS_SOURCE_URL", DEFAULT_SOURCE_URL)
    records = load_events(calendar_path, start, end, source_url)
    print(f"Parsed {len(records)} calendar events from {calendar_path}.")

    if args.dry_run:
        return

    client = NotionClient(
        require_env("NOTION_TOKEN"),
        require_env("NOTION_DATA_SOURCE_ID"),
        os.environ.get("NOTION_API_VERSION", DEFAULT_API_VERSION),
    )
    sync(client, records, dry_run=False)


if __name__ == "__main__":
    main()
