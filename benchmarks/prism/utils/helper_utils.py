import json, re
def safe_json_loads(payload: str):
    """
    Try normal JSON parse first.
    If it returns a string that itself looks like JSON, attempt a second parse.
    Also tolerates BOM and CRLF normalization.
    """
    # Normalize BOM and CRLF without touching backslashes.
    s = payload.lstrip("\ufeff").replace("\r\n", "\n")

    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        s = re.sub(r'(?<!\\)\\(?![n\\])', r'\\\\', s)
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise e

    # Handle double-encoded JSON (e.g., "\"{...}\"")
    if isinstance(obj, str):
        inner = obj.strip()
        if inner.startswith("{") or inner.startswith("["):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                # Fall through; return the original string object
                pass

    return obj