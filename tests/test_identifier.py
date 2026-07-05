import pytest

from scraper_for_facebook.errors import InvalidIdentifierError
from scraper_for_facebook.profiles import normalize_target_identifier


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("some.vanity.name", "https://www.facebook.com/some.vanity.name"),
        ("100000000000001", "https://www.facebook.com/profile.php?id=100000000000001"),
        (
            "https://www.facebook.com/some.vanity.name",
            "https://www.facebook.com/some.vanity.name",
        ),
        (
            "https://facebook.com/some.vanity.name/",
            "https://www.facebook.com/some.vanity.name",
        ),
        (
            "https://m.facebook.com/profile.php?id=123456789",
            "https://www.facebook.com/profile.php?id=123456789",
        ),
        (
            "https://www.facebook.com/profile.php?id=123456789&extra=1",
            "https://www.facebook.com/profile.php?id=123456789",
        ),
    ],
)
def test_valid_identifiers_normalize(raw, expected):
    assert normalize_target_identifier(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "http://www.facebook.com/insecure",  # not https
        "https://evil.example.com/facebook.com",  # wrong host
        "https://www.facebook.com/",  # no path
        "https://www.facebook.com/profile.php",  # missing id=
        "not a valid identifier at all!!",
        "javascript:alert(1)",
    ],
)
def test_invalid_identifiers_are_rejected(raw):
    with pytest.raises(InvalidIdentifierError):
        normalize_target_identifier(raw)
