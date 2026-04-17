def strip_nul_chars(value):
    """Remove NUL bytes from strings, including nested JSON-like structures."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [strip_nul_chars(item) for item in value]
    if isinstance(value, dict):
        return {
            strip_nul_chars(key) if isinstance(key, str) else key: strip_nul_chars(item)
            for key, item in value.items()
        }
    return value
