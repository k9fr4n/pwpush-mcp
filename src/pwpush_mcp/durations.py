"""Mapping between human-friendly durations and Password Pusher's enum.

Password Pusher's ``expire_after_duration`` / ``close_after_duration`` are not
raw time values but an enum index in the range 0..17. We accept either the raw
index or a human label (e.g. ``"1d"``, ``"6h"``) and resolve it to the index.
"""

from __future__ import annotations

# Canonical enum index -> human label, per API v2.
INDEX_TO_LABEL: dict[int, str] = {
    0: "15m",
    1: "30m",
    2: "45m",
    3: "1h",
    4: "6h",
    5: "12h",
    6: "1d",
    7: "2d",
    8: "3d",
    9: "4d",
    10: "5d",
    11: "6d",
    12: "1w",
    13: "2w",
    14: "3w",
    15: "1mo",
    16: "2mo",
    17: "3mo",
}

LABEL_TO_INDEX: dict[str, int] = {label: index for index, label in INDEX_TO_LABEL.items()}

# Accepted spellings that map onto a canonical label.
_ALIASES: dict[str, str] = {
    "15min": "15m",
    "30min": "30m",
    "45min": "45m",
    "1hour": "1h",
    "6hours": "6h",
    "12hours": "12h",
    "1day": "1d",
    "2days": "2d",
    "3days": "3d",
    "4days": "4d",
    "5days": "5d",
    "6days": "6d",
    # 7 days is not a distinct enum value; it is exactly one week.
    "7d": "1w",
    "7days": "1w",
    "1week": "1w",
    "2weeks": "2w",
    "3weeks": "3w",
    "1month": "1mo",
    "2months": "2mo",
    "3months": "3mo",
}

DEFAULT_LABEL = "7d"  # 7 days == one week (enum index 12)


# Days each canonical label corresponds to, for the v1 API which expires by
# whole days only. Sub-day durations are rounded up to one day.
_LABEL_TO_DAYS: dict[str, int] = {
    "15m": 1, "30m": 1, "45m": 1, "1h": 1, "6h": 1, "12h": 1,
    "1d": 1, "2d": 2, "3d": 3, "4d": 4, "5d": 5, "6d": 6,
    "1w": 7, "2w": 14, "3w": 21, "1mo": 30, "2mo": 60, "3mo": 90,
}


def resolve_days(value: int | str) -> int:
    """Resolve a duration to whole days for the v1 API (minimum 1).

    Accepts the same inputs as :func:`resolve_duration`. Sub-day labels round
    up to one day, since the v1 API only supports day-granular expiry.
    """
    index = resolve_duration(value)
    return _LABEL_TO_DAYS[INDEX_TO_LABEL[index]]


def resolve_duration(value: int | str) -> int:
    """Resolve a duration (index or human label) to the enum index 0..17.

    Raises:
        ValueError: if the value is out of range or unrecognised.
    """
    # ``bool`` is a subclass of ``int``; reject it explicitly.
    if isinstance(value, bool):
        raise ValueError("duration must be an integer index or a label, not a boolean")

    if isinstance(value, int):
        if 0 <= value <= 17:
            return value
        raise ValueError(f"duration index must be between 0 and 17, got {value}")

    if isinstance(value, str):
        key = value.strip().lower()
        if not key:
            raise ValueError("duration cannot be empty")
        if key.lstrip("+").isdigit():
            return resolve_duration(int(key))
        key = _ALIASES.get(key, key)
        if key in LABEL_TO_INDEX:
            return LABEL_TO_INDEX[key]
        valid = ", ".join(INDEX_TO_LABEL[i] for i in range(18))
        raise ValueError(f"unknown duration {value!r}; valid labels: {valid}")

    raise ValueError(f"duration must be int or str, got {type(value).__name__}")
