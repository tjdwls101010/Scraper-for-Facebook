import pytest

from agentic_facebook.errors import InvalidIdentifierError
from agentic_facebook.profiles import normalize_target_identifier, validate_permalink_url


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


def test_validate_permalink_url_preserves_full_path_unlike_normalize():
    # normalize_target_identifier would truncate this down to just the
    # profile URL, losing the post reference entirely — permalink
    # validation must preserve the full path.
    permalink = "https://www.facebook.com/100000000000001/posts/999888777"
    assert validate_permalink_url(permalink) == permalink


@pytest.mark.parametrize(
    "url",
    [
        "http://www.facebook.com/some/permalink",  # not https
        "https://evil.example.com/some/permalink",  # wrong host
    ],
)
def test_validate_permalink_url_rejects_bad_scheme_or_host(url):
    with pytest.raises(InvalidIdentifierError):
        validate_permalink_url(url)
