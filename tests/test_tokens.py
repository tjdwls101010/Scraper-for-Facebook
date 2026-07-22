"""Token extraction/caching. The HTML here is synthetic — shaped like a real
logged-in page's embedded JSON, but carrying no real session material."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta

import pytest

from agentic_facebook import tokens as tokens_mod
from agentic_facebook.errors import SessionExpiredError
from agentic_facebook.tokens import SessionTokens, extract_from_page

#: Shaped exactly like the real embedded JSON — the token names sit in a
#: ``["Name",[],{...}]`` triple, which is what the extraction regexes anchor on.
LOGGED_IN_HTML = """
<script>["DTSGInitialData",[],{"token":"NAcNfake-dtsg-token"},258];
["LSD",[],{"token":"lsd-fake"},1]; {"USER_ID":"100000000000001"}
{"__spin_r":1043454487,"__spin_t":1784550000,"__spin_b":"trunk"}</script>
"""

LOGGED_OUT_HTML = """
<script>{"USER_ID":"0"} {"caa_login_form_data":{"login_source":"COMET_HEADLESS_LOGIN"}}</script>
"""


class _FakePage:
    def __init__(self, html: str, cookies: list[dict]) -> None:
        self._html = html
        self.context = self
        self._cookies = cookies

    def content(self) -> str:
        return self._html

    def cookies(self) -> list[dict]:
        return self._cookies


def _cookies(**overrides) -> list[dict]:
    base = [
        {"name": "c_user", "value": "100000000000001", "domain": ".facebook.com"},
        {"name": "xs", "value": "fake-xs", "domain": ".facebook.com"},
        {"name": "unrelated", "value": "x", "domain": ".example.test"},
    ]
    return overrides.get("cookies", base)


def test_extract_from_page_reads_every_token():
    page = _FakePage(LOGGED_IN_HTML, _cookies())
    result = extract_from_page(page)

    assert result.fb_dtsg == "NAcNfake-dtsg-token"
    assert result.lsd == "lsd-fake"
    assert result.user_id == "100000000000001"
    assert result.rev == "1043454487"
    assert result.spin_b == "trunk"
    # Cookies from other domains must not ride along into an authenticated POST.
    assert set(result.cookies) == {"c_user", "xs"}


def test_extract_from_page_raises_when_logged_out():
    """Detected by the ABSENCE of what a logged-in page always has, not by URL —
    Facebook serves the login form in-place at HTTP 200 (recon §5.1)."""
    page = _FakePage(LOGGED_OUT_HTML, [])
    with pytest.raises(SessionExpiredError):
        extract_from_page(page)


def test_extract_from_page_raises_when_cookie_is_missing_despite_a_token():
    page = _FakePage(LOGGED_IN_HTML, [{"name": "datr", "value": "x", "domain": ".facebook.com"}])
    with pytest.raises(SessionExpiredError):
        extract_from_page(page)


def test_jazoest_is_computed_from_fb_dtsg():
    """Computed, never scraped — it is a checksum of fb_dtsg (recon §1)."""
    result = SessionTokens(
        fb_dtsg="AB",
        lsd="",
        user_id="1",
        rev="",
        spin_t="",
        spin_b="trunk",
        cookies={},
        extracted_at=datetime.now(UTC),
    )
    assert result.jazoest == "2131"  # "2" + str(65 + 66)


def test_is_stale_is_false_when_fresh_and_true_when_old():
    now = datetime.now(UTC)
    fresh = SessionTokens("t", "l", "1", "r", "s", "b", {}, now)
    old = SessionTokens("t", "l", "1", "r", "s", "b", {}, now - timedelta(hours=2))

    assert not fresh.is_stale()
    assert old.is_stale()


def test_round_trip_through_dict():
    original = SessionTokens("t", "l", "1", "r", "s", "b", {"c_user": "1"}, datetime.now(UTC))
    assert SessionTokens.from_dict(original.to_dict()) == original


def test_cache_is_written_owner_only(tmp_path, monkeypatch):
    """The cache holds live session credentials — as sensitive as the profile dir."""
    monkeypatch.setattr(tokens_mod, "tokens_dir", lambda: tmp_path / "tokens")
    result = SessionTokens("t", "l", "1", "r", "s", "b", {"c_user": "1"}, datetime.now(UTC))

    path = tokens_mod.save_cached("default", result)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert tokens_mod.load_cached("default") == result


def test_load_cached_returns_none_for_missing_or_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(tokens_mod, "tokens_dir", lambda: tmp_path / "tokens")
    assert tokens_mod.load_cached("nope") is None

    path = tmp_path / "tokens" / "broken.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert tokens_mod.load_cached("broken") is None

    path.write_text(json.dumps({"fb_dtsg": "only-this-key"}), encoding="utf-8")
    assert tokens_mod.load_cached("broken") is None
