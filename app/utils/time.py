from datetime import date, datetime


def now_iso() -> str:
    """Return a local wall-clock timestamp used by persisted business records."""
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def timestamp_id() -> str:
    """Return a sortable timestamp fragment suitable for local identifiers."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")
