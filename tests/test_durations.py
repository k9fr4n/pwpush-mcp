import pytest

from pwpush_mcp.durations import resolve_duration


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
