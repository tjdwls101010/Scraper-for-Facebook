"""Human-like scrolling with pagination-XHR-aware early stopping (plan §9, §11).

Two things this module has to work around, both found by reading scrapling's
actual source (not assumed from the plan):

1. Exceptions raised inside a scrapling ``page_action`` are caught and only
   logged — never propagated (see ``scrapling.engines._browsers._controllers``).
   So a wall (login/checkpoint) detected mid-scroll can't be signalled by
   raising; it's written into the mutable ``ScrollOutcome`` the caller gets
   back, and the caller raises the typed error itself, after ``fetch()``
   returns.
2. ``page.captured_xhr`` is only populated on the ``Response`` that
   ``session.fetch()`` returns, at the very end — the growing capture list
   inside ``fetch()`` isn't reachable from a ``page_action`` callback (which
   only receives the raw Playwright ``page``). To decide whether we already
   have enough posts (so we can stop scrolling instead of always burning the
   full ``max_scrolls`` budget — which matters for account-ban risk, not just
   speed), this module registers its OWN ``page.on("response", ...)``
   listener alongside scrapling's, watching the same events, and re-parses
   what it's captured so far after every scroll batch.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from . import parse
from .config import CAPTURE_XHR_PATTERN, clamp_scroll_pause
from .session import detect_wall

STOP_LIMIT_REACHED = "limit_reached"
STOP_SINCE_CROSSED = "since_crossed"
STOP_FEED_EXHAUSTED = "feed_exhausted"
STOP_MAX_SCROLLS = "max_scrolls"
STOP_FEED_STALLED = "feed_stalled"
#: scroll() raised before reaching any of the reasons above — an exception
#: inside a scrapling page_action is swallowed (see module docstring), so
#: retrieve.py falls back to this rather than mislabeling a crash as a
#: legitimate, complete max_scrolls run.
STOP_UNKNOWN_ERROR = "unknown_error"

#: consecutive scroll batches with no newly-discovered top-level post before
#: we call it a stall rather than just slow loading.
DEFAULT_STALL_BATCHES = 4


#: best-effort phrase list for memorialized/blocked/restricted/nonexistent
#: profiles — pending live-probe validation (plan §8: "detect from their
#: distinct wall markers... do not let them collapse into 'possible drift'").
_UNAVAILABLE_MARKERS = (
    "isn't available right now",
    "isn't available at the moment",
    "content isn't available",
    "this page isn't available",
    "remembering",
)


@dataclass
class ScrollOutcome:
    stop_reason: str | None = None
    wall_detected: str | None = None  # "login" | "checkpoint" | None
    profile_unavailable: bool = False
    scrolls_performed: int = 0
    top_level_ids_seen: set[str] = field(default_factory=set)
    oldest_non_pinned_seen: datetime | None = None
    newest_non_pinned_seen: datetime | None = None


def _is_pinned(story: dict) -> bool:
    for node in parse.iter_story_dicts(story, exclude_keys=parse.SHARE_EXCLUDE):
        for key, value in node.items():
            if value is True and "pinned" in key.lower():
                return True
    return False


def _looks_unavailable(html: str) -> bool:
    html_lower = html.lower()
    return any(marker in html_lower for marker in _UNAVAILABLE_MARKERS)


def _looks_like_end_of_feed(bodies: list[bytes]) -> bool:
    """Best-effort: an explicit ``has_next_page: false``-shaped marker, if present.

    Pending live-probe validation — until confirmed, "no new posts for N
    batches" is reported as the more honest ``feed_stalled`` (we can't yet
    tell "truly out of history" from "Facebook paused pagination").
    """
    for obj in parse.iter_json_objects(bodies):
        for node in parse.iter_story_dicts(obj):
            if node.get("has_next_page") is False:
                return True
    return False


def make_scroll_action(
    *,
    scroll_pause: tuple[float, float],
    max_scrolls: int,
    limit: int | None,
    since: date | None,
    stall_batches: int = DEFAULT_STALL_BATCHES,
):
    """Build a ``page_action`` callable plus the ``ScrollOutcome`` it will mutate.

    The callable never raises (see module docstring); the caller inspects the
    returned ``ScrollOutcome`` after ``session.fetch()`` completes.

    All mutable state (the outcome's fields, captured bodies, stall counter)
    is (re)initialized INSIDE ``scroll()`` itself, not in this outer function.
    scrapling's ``DynamicSession.fetch()`` retries internally by default
    (``retries=3``) on a brand-new page, calling this same ``page_action``
    again — state initialized only once out here would carry stale, partial
    results from a failed earlier attempt into the eventually-successful one.
    """
    scroll_pause = clamp_scroll_pause(scroll_pause)
    outcome = ScrollOutcome()
    xhr_pattern = re.compile(CAPTURE_XHR_PATTERN)

    def scroll(page) -> None:
        outcome.stop_reason = None
        outcome.wall_detected = None
        outcome.profile_unavailable = False
        outcome.scrolls_performed = 0
        outcome.top_level_ids_seen = set()
        outcome.oldest_non_pinned_seen = None
        outcome.newest_non_pinned_seen = None

        captured_bodies: list[bytes] = []
        stalled_batches = 0

        def on_response(response) -> None:
            try:
                if response.request.resource_type not in ("xhr", "fetch"):
                    return
                if not xhr_pattern.search(response.url):
                    return
                captured_bodies.append(response.body())
            except Exception:
                # Best-effort side channel only — the final
                # response.captured_xhr (read by retrieve.py after fetch()
                # returns) is authoritative.
                pass

        page.on("response", on_response)

        wall = detect_wall(page.url)
        if wall:
            outcome.wall_detected = wall
            return
        if _looks_unavailable(page.content()):
            outcome.profile_unavailable = True
            return

        for i in range(max_scrolls):
            outcome.scrolls_performed = i + 1
            page.mouse.wheel(0, random.randint(1200, 2400))
            time.sleep(random.uniform(*scroll_pause))

            wall = detect_wall(page.url)
            if wall:
                outcome.wall_detected = wall
                return

            parsed = parse.parse_story_nodes(captured_bodies)
            top_ids = set(parsed.top_level_ids())
            new_ids = top_ids - outcome.top_level_ids_seen

            for story_id in top_ids:
                story = parsed.stories[story_id]
                if _is_pinned(story):
                    continue
                creation_time = parse.find_creation_time(story)
                if creation_time is None:
                    continue
                created_at = datetime.fromtimestamp(creation_time, tz=UTC)
                if (
                    outcome.oldest_non_pinned_seen is None
                    or created_at < outcome.oldest_non_pinned_seen
                ):
                    outcome.oldest_non_pinned_seen = created_at
                if (
                    outcome.newest_non_pinned_seen is None
                    or created_at > outcome.newest_non_pinned_seen
                ):
                    outcome.newest_non_pinned_seen = created_at

            outcome.top_level_ids_seen = top_ids
            stalled_batches = 0 if new_ids else stalled_batches + 1

            if limit is not None and len(top_ids) >= limit:
                outcome.stop_reason = STOP_LIMIT_REACHED
                return

            if since is not None and outcome.oldest_non_pinned_seen is not None:
                if outcome.oldest_non_pinned_seen.date() < since:
                    outcome.stop_reason = STOP_SINCE_CROSSED
                    return

            if _looks_like_end_of_feed(captured_bodies):
                outcome.stop_reason = STOP_FEED_EXHAUSTED
                return

            if stalled_batches >= stall_batches:
                outcome.stop_reason = STOP_FEED_STALLED
                return

        outcome.stop_reason = STOP_MAX_SCROLLS

    return scroll, outcome
