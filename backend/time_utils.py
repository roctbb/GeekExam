from datetime import timezone


def utc_iso(value):
    """Serialize database timestamps (stored as naive UTC) with an explicit zone."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
