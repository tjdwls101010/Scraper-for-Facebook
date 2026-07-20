from datetime import UTC, date, datetime

from scraper_for_facebook import scroll
from scraper_for_facebook.model import Post
from scraper_for_facebook.retrieve import _apply_window, _since_reached

CAPTURED_AT = datetime(2026, 7, 5, tzinfo=UTC)


def _make_post(id_, *, created_at=None, is_pinned=False) -> Post:
    return Post(
        id=id_,
        url=None,
        type="status",
        is_pinned=is_pinned,
        author_name=None,
        author_url=None,
        author_id=None,
        created_at=created_at,
        edited_at=None,
        text="",
        text_truncated=False,
        text_resolved=False,
        media=[],
        links=[],
        reaction_count=None,
        comment_count=None,
        share_count=None,
        shared_post=None,
        source="timeline",
        captured_at=CAPTURED_AT,
    )


def test_window_excludes_posts_outside_since_until():
    posts = [
        _make_post("old", created_at=datetime(2025, 1, 1, tzinfo=UTC)),
        _make_post("mid", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
        _make_post("new", created_at=datetime(2025, 12, 1, tzinfo=UTC)),
    ]
    result = _apply_window(posts, limit=None, since=date(2025, 3, 1), until=date(2025, 9, 1))
    assert [p.id for p in result] == ["mid"]


def test_window_never_excludes_pinned_posts():
    posts = [
        _make_post("pinned_old", created_at=datetime(2020, 1, 1, tzinfo=UTC), is_pinned=True),
        _make_post("in_window", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
    ]
    result = _apply_window(posts, limit=None, since=date(2025, 1, 1), until=None)
    assert {p.id for p in result} == {"pinned_old", "in_window"}


def test_window_never_excludes_posts_with_unknown_date():
    posts = [
        _make_post("unknown_date", created_at=None),
        _make_post("in_window", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
    ]
    result = _apply_window(posts, limit=None, since=date(2025, 1, 1), until=None)
    assert {p.id for p in result} == {"unknown_date", "in_window"}


def test_sort_pinned_first_then_newest_first_then_unknown_last():
    posts = [
        _make_post("older", created_at=datetime(2025, 1, 1, tzinfo=UTC)),
        _make_post("newer", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
        _make_post("unknown", created_at=None),
        _make_post("pinned", created_at=datetime(2020, 1, 1, tzinfo=UTC), is_pinned=True),
    ]
    result = _apply_window(posts, limit=None, since=None, until=None)
    assert [p.id for p in result] == ["pinned", "newer", "older", "unknown"]


def test_sort_multiple_pinned_posts_by_recency_not_encounter_order():
    posts = [
        _make_post("pinned_older", created_at=datetime(2020, 1, 1, tzinfo=UTC), is_pinned=True),
        _make_post("pinned_newer", created_at=datetime(2024, 1, 1, tzinfo=UTC), is_pinned=True),
        _make_post("normal", created_at=datetime(2025, 1, 1, tzinfo=UTC)),
    ]
    result = _apply_window(posts, limit=None, since=None, until=None)
    assert [p.id for p in result] == ["pinned_newer", "pinned_older", "normal"]


def test_limit_is_applied_after_windowing_and_sorting():
    posts = [_make_post(str(i), created_at=datetime(2025, 1, i + 1, tzinfo=UTC)) for i in range(5)]
    result = _apply_window(posts, limit=2, since=None, until=None)
    assert len(result) == 2
    assert result[0].id == "4"  # newest first


def test_since_reached_true_when_since_not_requested():
    assert _since_reached(None, scroll.STOP_MAX_SCROLLS) is True


def test_since_reached_true_on_since_crossed_or_feed_exhausted():
    since = date(2025, 1, 1)
    assert _since_reached(since, scroll.STOP_SINCE_CROSSED) is True
    assert _since_reached(since, scroll.STOP_FEED_EXHAUSTED) is True


def test_since_reached_false_when_stalled_or_maxed_out_before_crossing():
    since = date(2025, 1, 1)
    assert _since_reached(since, scroll.STOP_MAX_SCROLLS) is False
    assert _since_reached(since, scroll.STOP_FEED_STALLED) is False


def test_since_reached_false_on_limit_reached():
    # Hitting --limit proves nothing about whether --since was ever crossed
    # (scroll.py checks limit before since each batch) — the CLI's exit-0
    # treatment of limit_reached is a separate, CLI-level judgment call, not
    # something this field should misrepresent to other callers.
    assert _since_reached(date(2025, 1, 1), scroll.STOP_LIMIT_REACHED) is False
