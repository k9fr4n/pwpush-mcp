import pytest

from pwpush_mcp.durations import resolve_days, resolve_duration


@pytest.mark.parametrize(
    ("value", "days"),
    [
        ("15m", 1),  # sub-day rounds up to 1
        ("12h", 1),
        ("1d", 1),
        ("6d", 6),
        ("7d", 7),
        ("1w", 7),
        ("3w", 21),
        ("1mo", 30),
        ("3mo", 90),
        (0, 1),
        (17, 90),
    ],
)
def test_resolve_days(value, days):
    assert resolve_days(value) == days


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (17, 17),
        ("0", 0),
        ("6", 6),
        ("15m", 0),
        ("1h", 3),
        ("6h", 4),
        ("1d", 6),
        ("1day", 6),
        ("1w", 12),
        ("7d", 12),
        ("7days", 12),
        ("1week", 12),
        ("1mo", 15),
        ("3mo", 17),
        (" 1D ", 6),
    ],
)
def test_resolve_valid(value, expected):
    assert resolve_duration(value) == expected


@pytest.mark.parametrize("value", [-1, 18, 100, "", "99", "2hours-ish", "foo"])
def test_resolve_invalid(value):
    with pytest.raises(ValueError):
        resolve_duration(value)


def test_bool_rejected():
    with pytest.raises(ValueError):
        resolve_duration(True)
