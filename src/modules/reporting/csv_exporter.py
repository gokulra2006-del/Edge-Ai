from __future__ import annotations

import csv
import io
from typing import Any, Generator, Sequence
from pathlib import Path

from src.modules.database.governed_store import IncidentRepository


DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    """Neutralize potential CSV/formula injection attacks (DDE/Excel macro injection)."""
    if value is None:
        return ""
    val_str = str(value)
    if not val_str:
        return ""
    if val_str.startswith(DANGEROUS_FORMULA_PREFIXES) or val_str.lstrip(" ").startswith(DANGEROUS_FORMULA_PREFIXES):
        return f"'{val_str}"
    return val_str


CSV_HEADERS = [
    "incident_id",
    "incident_uuid",
    "event_type",
    "zone_id",
    "status",
    "severity",
    "assurance_level",
    "created_at",
    "updated_at",
    "acknowledged_seconds",
    "resolution_seconds",
    "temporal_state",
    "ood_status",
    "is_demo",
    "outcome",
    "version",
]


def stream_incidents_csv(
    repository: IncidentRepository,
    start_time: str | None = None,
    end_time: str | None = None,
    zone_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    event_type: str | None = None,
    include_demo: bool = False,
    chunk_size: int = 50,
) -> Generator[str, None, None]:
    """Stream incident CSV lines safely in chunks to preserve Raspberry Pi memory."""
    conditions = []
    params: list[Any] = []

    if start_time:
        conditions.append("created_at >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("created_at <= ?")
        params.append(end_time)
    if not include_demo:
        conditions.append("is_demo = 0")
    if zone_id and zone_id.lower() not in ("all", ""):
        conditions.append("zone_id = ?")
        params.append(zone_id)
    if severity and severity.lower() not in ("all", ""):
        conditions.append("severity = ?")
        params.append(severity.upper())
    if status and status.lower() not in ("all", ""):
        conditions.append("status = ?")
        params.append(status.upper())
    if event_type and event_type.lower() not in ("all", ""):
        conditions.append("event_type = ?")
        params.append(event_type.upper())

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
        SELECT incident_id, incident_uuid, event_type, zone_id, status, severity,
               assurance_level, created_at, updated_at, acknowledged_seconds,
               resolution_seconds, temporal_state, ood_status, is_demo, outcome, version
        FROM incidents
        {where_clause}
        ORDER BY created_at DESC
    """

    # Yield Header
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADERS)
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    # Read rows and yield in streamed batches
    import sqlite3
    con = sqlite3.connect(str(repository.db_path), timeout=1.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only = ON")
    except sqlite3.OperationalError:
        pass
    try:
        cursor = con.execute(query, tuple(params))
        batch: list[list[str]] = []

        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            for row in rows:
                cleaned_row = [sanitize_csv_cell(row[col]) for col in CSV_HEADERS]
                batch.append(cleaned_row)

            writer.writerows(batch)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            batch.clear()
    finally:
        con.close()


def export_incidents_csv(
    repository: IncidentRepository,
    target_path: Path | str,
    start_time: str | None = None,
    end_time: str | None = None,
    zone_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    event_type: str | None = None,
    include_demo: bool = False,
) -> Path:
    """Write streamed incident CSV into target file with formula injection protection."""
    out_file = Path(target_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with open(out_file, "w", encoding="utf-8", newline="") as f:
        for chunk in stream_incidents_csv(
            repository=repository,
            start_time=start_time,
            end_time=end_time,
            zone_id=zone_id,
            severity=severity,
            status=status,
            event_type=event_type,
            include_demo=include_demo,
        ):
            f.write(chunk)

    return out_file
