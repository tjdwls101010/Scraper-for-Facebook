"""Opt-in live tests. NEVER run in CI.

These hit real Facebook with a real logged-in session, so they need a throwaway
account and are gated behind ``SFB_LIVE_TESTS=1``:

    SFB_LIVE_TESTS=1 PYTHONPATH=src .venv/bin/python -m pytest tests/live -v

They assert *shapes and invariants*, never specific content — the account's
timeline changes, and asserting on real posts would both break constantly and
bake third-party PII into the repo.
"""

from __future__ import annotations

import os

import pytest

from agentic_facebook import profiles, retrieve

pytestmark = pytest.mark.skipif(
    os.environ.get("SFB_LIVE_TESTS") != "1",
    reason="live tests are opt-in: set SFB_LIVE_TESTS=1 (uses a real logged-in session)",
)

PROFILE_NAME = os.environ.get("SFB_LIVE_PROFILE", "default")
TARGET = os.environ.get("SFB_LIVE_TARGET", "https://www.facebook.com/me")


@pytest.fixture(scope="module")
def profile_dir():
    path = profiles.resolve_profile_dir(PROFILE_NAME, None)
    if not path.exists():
        pytest.skip(f"no login profile at {path} — run: agentic-facebook login")
    return path


def _fetch(profile_dir, mode: str, **kwargs):
    return retrieve.fetch_profile(
        TARGET, profile_dir=profile_dir, profile_name=PROFILE_NAME, mode=mode, **kwargs
    )


def test_active_returns_parseable_posts(profile_dir):
    result = _fetch(profile_dir, "active", limit=3)

    assert result.transport == "active"
    assert result.posts, "active mode returned no posts — doc_id may have rotated"
    for post in result.posts:
        assert post.id
        assert post.source == "timeline"
        # These are the handles a chaining caller navigates by — if they stop
        # being populated, multi-hop navigation silently breaks.
        assert post.author_id or post.author_url


def test_active_and_passive_agree_on_the_posts_they_share(profile_dir):
    """The parity gate: one parser, two transports, identical field values.

    Deliberately compares the INTERSECTION, not the whole set. The two
    transports legitimately see different windows — passive cannot see the
    newest post at all, because a profile's first timeline batch is
    server-rendered into the HTML document rather than fetched as a GraphQL
    XHR. What must hold is that a post seen by both parses identically.
    """
    active = _fetch(profile_dir, "active", limit=5)
    passive = _fetch(profile_dir, "passive", limit=5)

    by_id_active = {p.id: p for p in active.posts}
    by_id_passive = {p.id: p for p in passive.posts}
    shared = set(by_id_active) & set(by_id_passive)
    assert shared, "no overlap at all between transports — one of them is broken"

    for post_id in shared:
        a, p = by_id_active[post_id], by_id_passive[post_id]
        assert (a.author_name, a.author_id, a.created_at) == (
            p.author_name,
            p.author_id,
            p.created_at,
        )
        assert (a.type, a.url, a.text) == (p.type, p.url, p.text)
        assert (a.reaction_count, a.comment_count) == (p.reaction_count, p.comment_count)


def test_active_honors_the_server_side_date_window(profile_dir):
    """--since/--until map to afterTime/beforeTime, enforced by the server (recon §7.3)."""
    baseline = _fetch(profile_dir, "active", limit=10)
    dated = sorted(p.created_at for p in baseline.posts if p.created_at and not p.is_pinned)
    if len(dated) < 2:
        pytest.skip("need >= 2 dated posts to build a discriminating window")

    until = dated[-1].date()
    windowed = _fetch(profile_dir, "active", limit=10, until=until)

    for post in windowed.posts:
        if post.created_at and not post.is_pinned:
            assert post.created_at.date() <= until
