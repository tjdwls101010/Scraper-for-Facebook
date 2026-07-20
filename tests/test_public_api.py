"""The `FacebookScraper` facade's contract with the retrieval layer.

These exist because the facade forwards a growing set of options, and a
forwarding bug is invisible from inside the facade — everything still runs,
just against the wrong thing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import scraper_for_facebook as package
from scraper_for_facebook import FacebookScraper
from scraper_for_facebook.retrieve import RetrieveResult


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Record what the facade passes down, without touching a browser."""
    calls: list[dict] = []

    def _fake_fetch_profile(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return RetrieveResult(
            posts=[],
            stop_reason="feed_exhausted",
            since_reached=True,
            oldest_seen=None,
            newest_seen=None,
            scrolls_performed=0,
            transport="active",
        )

    monkeypatch.setattr(package.retrieve_module, "fetch_profile", _fake_fetch_profile)
    monkeypatch.setattr(
        package.profiles, "resolve_profile_dir", lambda name, override: tmp_path / name
    )
    return calls


def test_profile_name_travels_with_profile_dir(captured, tmp_path):
    """Regression: the token cache is keyed by NAME, the browser by DIRECTORY.

    When the facade forwarded only the directory, a non-default profile drove
    one account's browser while reading and overwriting a *different* account's
    cached cookies — a silent cross-account mix-up, not a crash.
    """
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    with FacebookScraper(profile="work") as fb:
        fb.fetch_profile("someone")

    call = captured[0]
    assert call["profile_name"] == "work"
    assert call["profile_dir"] == tmp_path / "work"


def test_default_profile_still_forwards_its_name(captured, tmp_path):
    (tmp_path / "default").mkdir(parents=True, exist_ok=True)
    with FacebookScraper() as fb:
        fb.fetch_profile("someone")

    assert captured[0]["profile_name"] == "default"


def test_scroll_settings_are_forwarded(captured, tmp_path):
    (tmp_path / "default").mkdir(parents=True, exist_ok=True)
    with FacebookScraper(scroll_pause=(3.0, 5.0), max_scrolls=7, headless=False) as fb:
        fb.fetch_profile("someone")

    call = captured[0]
    assert call["scroll_pause"] == (3.0, 5.0)
    assert call["max_scrolls"] == 7
    assert call["headless"] is False


def test_dates_are_parsed_from_strings(captured, tmp_path):
    (tmp_path / "default").mkdir(parents=True, exist_ok=True)
    with FacebookScraper() as fb:
        fb.fetch_profile("someone", since="2026-01-01", until="2026-02-01")

    call = captured[0]
    assert call["since"] == datetime(2026, 1, 1, tzinfo=UTC).date()
    assert call["until"] == datetime(2026, 2, 1, tzinfo=UTC).date()
