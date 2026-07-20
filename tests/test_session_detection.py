"""Login-state detection — the recon §5.1 false positive and its fix."""

from __future__ import annotations

from scraper_for_facebook.session import detect_wall, looks_logged_in

LOGGED_IN_HTML = '<script>["DTSGInitialData",[],{"token":"tok"},258];</script>'

#: What a DEAD session actually gets served: the login form, in place, at
#: https://www.facebook.com/ — HTTP 200, no redirect anywhere.
LOGIN_FORM_HTML = '<script>{"caa_login_form_data":{"login_source":"COMET_HEADLESS_LOGIN"}}</script>'


def test_detect_wall_still_reads_the_obvious_urls():
    assert detect_wall("https://www.facebook.com/checkpoint/12345") == "checkpoint"
    assert detect_wall("https://www.facebook.com/login/?next=x") == "login"
    assert detect_wall("https://www.facebook.com/") is None


def test_detect_wall_catches_the_in_place_login_form():
    """The regression: a 15-day-dead session reported `logged_in` because the
    URL looked perfectly healthy. The body is the only tell."""
    assert detect_wall("https://www.facebook.com/", LOGIN_FORM_HTML) == "login"


def test_detect_wall_treats_a_missing_login_token_as_logged_out():
    """Positive test, so an unanticipated logged-out shape still fails closed."""
    assert detect_wall("https://www.facebook.com/", "<html>something else</html>") == "login"


def test_detect_wall_passes_a_genuinely_logged_in_page():
    assert detect_wall("https://www.facebook.com/", LOGGED_IN_HTML) is None


def test_looks_logged_in_requires_both_a_token_and_the_session_cookie():
    assert looks_logged_in(LOGGED_IN_HTML, ["c_user", "xs"])
    assert not looks_logged_in(LOGGED_IN_HTML, ["datr"])  # no c_user
    assert not looks_logged_in("<html></html>", ["c_user"])  # no token
    assert not looks_logged_in(LOGGED_IN_HTML + LOGIN_FORM_HTML, ["c_user"])  # form present
