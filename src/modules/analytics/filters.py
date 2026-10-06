from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any


VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN", "INFO", "NORMAL"}
MAX_RANGE_DAYS = 365


def parse_datetime(val: str | datetime | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip().replace("Z", "+00:00")
    if not s:
        return None
    try:
        # Date only: e.g. 2026-10-01
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime.fromisoformat(f"{s}T00:00:00+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid timestamp format: '{val}'. Expected ISO 8601 format.") from exc


@dataclass(frozen=True)
class AnalyticsFilter:
    """Canonical filter object for all analytics queries."""
    start_time: str
    end_time: str
    zone: str | None = None
    severity: str | None = None
    event_type: str | None = None
    model_id: str | None = None
    include_demo: bool = False

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Validate bounds and column constraints."""
        s_dt = parse_datetime(self.start_time)
        e_dt = parse_datetime(self.end_time)

        if s_dt is None or e_dt is None:
            raise ValueError("Unbounded ranges are not permitted: both start_time and end_time are required.")

        if s_dt > e_dt:
            raise ValueError(f"Invalid date range: start_time ({self.start_time}) cannot be after end_time ({self.end_time}).")

        delta = e_dt - s_dt
        if delta > timedelta(days=MAX_RANGE_DAYS):
            raise ValueError(f"Requested date range of {delta.days} days exceeds maximum allowed limit of {MAX_RANGE_DAYS} days.")

        if self.severity is not None:
            sev_norm = self.severity.strip().upper()
            if sev_norm not in VALID_SEVERITIES:
                raise ValueError(f"Invalid severity '{self.severity}'. Must be one of: {sorted(VALID_SEVERITIES)}")

    @property
    def start_date(self) -> str:
        return self.start_time[:10]

    @property
    def end_date(self) -> str:
        return self.end_time[:10]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "zone": self.zone,
            "severity": self.severity,
            "event_type": self.event_type,
            "model_id": self.model_id,
            "include_demo": self.include_demo,
        }

    @classmethod
    def from_params(
        cls,
        params: dict[str, Any] | None = None,
        default_days: int = 30,
        ref_time: datetime | None = None
    ) -> AnalyticsFilter:
        """Build validated AnalyticsFilter from request params or dictionary."""
        params = params or {}
        now = ref_time or datetime.now(timezone.utc)

        # 1. Resolve time bounds
        st = params.get("start_time") or params.get("start_date") or params.get("from")
        et = params.get("end_time") or params.get("end_date") or params.get("to")
        window = params.get("range") or params.get("window")

        if isinstance(st, list) and st: st = st[0]
        if isinstance(et, list) and et: et = et[0]
        if isinstance(window, list) and window: window = window[0]

        if st and et:
            start_iso = parse_datetime(st).isoformat()
            end_iso = parse_datetime(et).isoformat()
        elif st and not et:
            start_iso = parse_datetime(st).isoformat()
            end_iso = now.isoformat()
        elif et and not st:
            end_dt = parse_datetime(et)
            start_iso = (end_dt - timedelta(days=default_days)).isoformat()
            end_iso = end_dt.isoformat()
        elif window:
            w = str(window).strip().lower()
            if w == "all":
                # Reject unbounded 'all' or clamp to max 365 days
                start_iso = (now - timedelta(days=MAX_RANGE_DAYS)).isoformat()
                end_iso = now.isoformat()
            elif w.endswith("h"):
                try: h = int(w[:-1])
                except ValueError: h = 24
                start_iso = (now - timedelta(hours=h)).isoformat()
                end_iso = now.isoformat()
            elif w.endswith("d"):
                try: d = int(w[:-1])
                except ValueError: d = default_days
                start_iso = (now - timedelta(days=d)).isoformat()
                end_iso = now.isoformat()
            else:
                start_iso = (now - timedelta(days=default_days)).isoformat()
                end_iso = now.isoformat()
        else:
            start_iso = (now - timedelta(days=default_days)).isoformat()
            end_iso = now.isoformat()

        # 2. Extract and sanitize filters
        def clean_filter(v: Any) -> str | None:
            if isinstance(v, list) and v: v = v[0]
            if v is None: return None
            s = str(v).strip()
            if s.lower() in ("", "all", "none", "null", "*"): return None
            return s

        zone = clean_filter(params.get("zone") or params.get("zone_id"))
        severity = clean_filter(params.get("severity") or params.get("sev"))
        if severity: severity = severity.upper()
        event_type = clean_filter(params.get("event_type") or params.get("type"))
        if event_type: event_type = event_type.upper()
        model_id = clean_filter(params.get("model") or params.get("model_id"))

        inc_demo_raw = params.get("include_demo", False)
        if isinstance(inc_demo_raw, list) and inc_demo_raw: inc_demo_raw = inc_demo_raw[0]
        include_demo = str(inc_demo_raw).lower() in ("true", "1", "yes")

        return cls(
            start_time=start_iso,
            end_time=end_iso,
            zone=zone,
            severity=severity,
            event_type=event_type,
            model_id=model_id,
            include_demo=include_demo
        )
