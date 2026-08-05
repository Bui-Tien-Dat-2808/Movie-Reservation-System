from datetime import datetime, timezone, timedelta
from typing import Optional

VIETNAM_TZ = timezone(timedelta(hours=7))


def get_cinema_timezone() -> timezone:
    """Get cinema timezone (UTC+7 for Vietnam)."""
    return VIETNAM_TZ


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime object is timezone-aware in UTC.
    
    If dt is naive (no tzinfo), replace tzinfo with UTC.
    If dt is aware (has tzinfo), convert it to UTC using astimezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
