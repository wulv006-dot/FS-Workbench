"""Short-lived display copy of FC27 team activity; source audits stay untouched."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3


DB_PATH = Path("/var/lib/fc27-cloud/activity-log/events.sqlite3")
BEIJING = timezone(timedelta(hours=8))
KEEP_DAYS = 14


def instant(value):
    if not isinstance(value, str):
        raise ValueError("activity_time_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("activity_time_invalid")
    return int(parsed.timestamp())


@contextmanager
def database():
    DB_PATH.parent.mkdir(mode=0o2770, parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("""CREATE TABLE IF NOT EXISTS events (
            source TEXT NOT NULL, event_id TEXT NOT NULL, at_epoch INTEGER NOT NULL,
            payload_json TEXT NOT NULL, retained INTEGER NOT NULL DEFAULT 0,
            retained_by TEXT, retained_at TEXT,
            PRIMARY KEY (source, event_id))""")
        connection.execute("CREATE INDEX IF NOT EXISTS events_at ON events(at_epoch DESC)")
        os.chmod(DB_PATH, 0o640)
        with connection:
            yield connection
    finally:
        connection.close()


def capture(events, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = int((now - timedelta(days=KEEP_DAYS)).timestamp())
    admitted, skipped = 0, 0
    with database() as db:
        for event in events:
            try:
                source, event_id = event["source"], str(event["id"])
                if source not in {"cloud", "legacy"} or not 1 <= len(event_id) <= 120:
                    raise ValueError("activity_key_invalid")
                when = instant(event["at"])
                if when < cutoff or when > int((now + timedelta(minutes=5)).timestamp()):
                    continue
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                db.execute("""INSERT OR IGNORE INTO events(source,event_id,at_epoch,payload_json)
                    VALUES (?,?,?,?)""", (source, event_id, when, payload))
                db.execute("""UPDATE events SET at_epoch=?,payload_json=?
                    WHERE source=? AND event_id=?""", (when, payload, source, event_id))
                admitted += 1
            except (KeyError, ValueError, TypeError, OverflowError):
                skipped += 1
        deleted = db.execute("DELETE FROM events WHERE at_epoch < ? AND retained = 0",
                             (cutoff,)).rowcount
    return {"captured": admitted, "skipped": skipped, "deleted": deleted}


def query(limit=200, day=None, now=None):
    now = now or datetime.now(timezone.utc)
    if day is None:
        start, end = int((now - timedelta(hours=24)).timestamp()), int(now.timestamp()) + 1
        scope = "recent"
    else:
        selected = date.fromisoformat(day)
        start = int(datetime.combine(selected, time.min, BEIJING).timestamp())
        end = int(datetime.combine(selected + timedelta(days=1), time.min, BEIJING).timestamp())
        scope = "date"
    with database() as db:
        rows = db.execute("""SELECT payload_json,retained FROM events
            WHERE at_epoch >= ? AND at_epoch < ?
            ORDER BY at_epoch DESC,source,event_id LIMIT ?""", (start, end, limit)).fetchall()
    events = []
    for payload, retained in rows:
        event = json.loads(payload)
        event["retained"] = bool(retained)
        events.append(event)
    return {"scope": scope, "date": day, "events": events}


def set_retained(source, event_id, retained, actor, now=None):
    if (source not in {"cloud", "legacy"} or not isinstance(event_id, str)
            or not 1 <= len(event_id) <= 120 or type(retained) is not bool):
        raise ValueError("activity_mark_invalid")
    now = now or datetime.now(timezone.utc)
    with database() as db:
        changed = db.execute("""UPDATE events SET retained=?,retained_by=?,retained_at=?
            WHERE source=? AND event_id=?""",
            (int(retained), actor if retained else None, now.isoformat() if retained else None,
             source, event_id)).rowcount
        if not changed:
            raise ValueError("activity_event_not_found")
        db.execute("DELETE FROM events WHERE at_epoch < ? AND retained = 0",
                   (int((now - timedelta(days=KEEP_DAYS)).timestamp()),))
    return {"source": source, "id": event_id, "retained": retained}
