"""Retrieval orchestration: drive one fetch, enforce limit/since/until, resolve
truncated text, and report why the run stopped (plan §11).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import model, parse, scroll, truncation
from .config import clamp_scroll_pause
from .errors import ChallengeError, LoginRequiredError, ProfileUnavailableError, SessionExpiredError
from .session import build_session


@dataclass
class RetrieveResult:
    posts: list[model.Post]
    stop_reason: str
    since_reached: bool  # whether a requested --since was confirmed crossed (or moot)
    oldest_seen: datetime | None
    newest_seen: datetime | None
    scrolls_performed: int


def _sort_key(post: model.Post):
    if post.is_pinned:
        return (0, 0.0)
    if post.created_at is None:
        return (2, 0.0)
    return (1, -post.created_at.timestamp())


def _in_window(post: model.Post, *, since: date | None, until: date | None) -> bool:
    # Pinned posts, and posts whose date we couldn't place at all, are never
    # excluded by the window — we can't safely judge either against `since`/
    # `until` (plan §11: pinned breaks a naive stop condition; §8: unplaceable
    # dates must never be silently mis-filtered).
    if post.is_pinned or post.created_at is None:
        return True
    post_date = post.created_at.date()
    if since is not None and post_date < since:
        return False
    if until is not None and post_date > until:
        return False
    return True


def _apply_window(
    posts: list[model.Post], *, limit: int | None, since: date | None, until: date | None
) -> list[model.Post]:
    windowed = [p for p in posts if _in_window(p, since=since, until=until)]
    windowed.sort(key=_sort_key)
    if limit is not None:
        windowed = windowed[:limit]
    return windowed


def _since_reached(since: date | None, stop_reason: str) -> bool:
    if since is None:
        return True
    return stop_reason in (
        scroll.STOP_SINCE_CROSSED,
        scroll.STOP_FEED_EXHAUSTED,
        scroll.STOP_LIMIT_REACHED,
    )


def fetch_profile(
    url: str,
    *,
    profile_dir: Path,
    headless: bool = True,
    limit: int | None = None,
    since: date | None = None,
    until: date | None = None,
    scroll_pause: tuple[float, float] = (2.0, 4.0),
    max_scrolls: int = 40,
    raw: bool = False,
) -> RetrieveResult:
    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )

    scroll_pause = clamp_scroll_pause(scroll_pause)
    scroll_action, outcome = scroll.make_scroll_action(
        scroll_pause=scroll_pause, max_scrolls=max_scrolls, limit=limit, since=since
    )

    with build_session(profile_dir, headless=headless) as session:
        response = session.fetch(url, page_action=scroll_action)

        if outcome.wall_detected == "checkpoint":
            raise ChallengeError(
                "Facebook checkpoint detected mid-fetch. Log in again in a real "
                "browser, then retry: scrape-fb login"
            )
        if outcome.wall_detected == "login":
            raise SessionExpiredError("Session expired mid-fetch. Log in again: scrape-fb login")
        if outcome.profile_unavailable:
            raise ProfileUnavailableError(
                f"Profile unavailable (memorialized, blocked, restricted, or nonexistent): {url}"
            )

        bodies = [xhr.body for xhr in response.captured_xhr]
        parsed = parse.parse_story_nodes(bodies)
        captured_at = datetime.now(UTC)

        posts = [
            model.build_post(parsed.stories[story_id], captured_at=captured_at, include_raw=raw)
            for story_id in parsed.top_level_ids()
        ]

        filtered = _apply_window(posts, limit=limit, since=since, until=until)

        def fetch_permalink_bodies(permalink_url: str) -> list[bytes]:
            time.sleep(random.uniform(*scroll_pause))
            permalink_response = session.fetch(permalink_url, timeout=30000)
            return [xhr.body for xhr in permalink_response.captured_xhr]

        # Only top-level posts are resolved in v1 — resolving a nested
        # shared_post too would mean another permalink fetch per share, and
        # the scope/value tradeoff isn't worth it yet (roadmap candidate).
        for post in filtered:
            if post.text_truncated and not post.text_resolved and post.url:
                resolved = truncation.resolve_truncated_text(post.url, fetch_permalink_bodies)
                if resolved:
                    post.text = resolved
                    post.text_resolved = True

    stop_reason = outcome.stop_reason or scroll.STOP_MAX_SCROLLS
    return RetrieveResult(
        posts=filtered,
        stop_reason=stop_reason,
        since_reached=_since_reached(since, stop_reason),
        oldest_seen=outcome.oldest_non_pinned_seen,
        newest_seen=outcome.newest_non_pinned_seen,
        scrolls_performed=outcome.scrolls_performed,
    )
