"""Retrieval orchestration: drive one fetch, enforce limit/since/until, resolve
truncated text, and report why the run stopped (plan §11).

Transport-agnostic since 0.3.0: the same target can be read over HTTP GraphQL
(active, fast) or by scrolling a browser (passive, original). Both produce
identical GraphQL JSON, so everything below the byte-fetching step — parse,
window, sort — is shared verbatim (recon §1).
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import comments as comments_mod
from . import graphql, model, parse, profiles, queries, scroll, tokens, truncation
from . import search as search_mod
from .config import DEFAULT_MAX_PAGES, DEFAULT_REQUEST_INTERVAL, clamp_scroll_pause
from .errors import (
    ActiveTransportError,
    ChallengeError,
    InvalidIdentifierError,
    LoginRequiredError,
    ProfileUnavailableError,
    SessionExpiredError,
)
from .session import build_session

#: Active mode's own budget ceiling — the counterpart to STOP_MAX_SCROLLS. Named
#: separately because "we ran out of pages" and "we ran out of scrolls" are
#: different facts, even though both leave a requested --since unconfirmed.
STOP_MAX_PAGES = "max_pages"


@dataclass
class RetrieveResult:
    posts: list[model.Post]
    stop_reason: str
    since_reached: bool  # whether a requested --since was confirmed crossed (or moot)
    oldest_seen: datetime | None
    newest_seen: datetime | None
    scrolls_performed: int
    #: "active" | "passive" — which transport produced these posts. Surfaced so
    #: a silent fallback to the slow path is visible rather than mysterious.
    transport: str = "passive"


def _sort_key(post: model.Post):
    # Unplaceable dates always sort last, pinned or not — we can't judge them.
    if post.created_at is None:
        return (2, 0.0)
    # Pinned and non-pinned each sort newest-first among themselves; pinned
    # posts as a group still come first (bucket 0 vs 1).
    bucket = 0 if post.is_pinned else 1
    return (bucket, -post.created_at.timestamp())


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
    """Whether the `--since` date boundary was itself actually verified.

    Deliberately does NOT treat STOP_LIMIT_REACHED as proof of this — the
    scroll loop checks `limit` before `since` each batch (scroll.py), so
    hitting the limit can happen long before ever scrolling anywhere near
    `since`. The CLI still reports exit 0 for a limit-satisfied run (per the
    plan's exit-code table: hitting `--limit` is success in its own right,
    since `--limit`/`--since` "compose, first trigger wins") — but that is a
    separate, CLI-level judgment call, computed directly from stop_reason
    (see cli.py), not smuggled into this field's meaning.
    """
    if since is None:
        return True
    return stop_reason in (scroll.STOP_SINCE_CROSSED, scroll.STOP_FEED_EXHAUSTED)


def _posts_from_bodies(
    bodies: list[bytes], *, source: str, include_raw: bool, captured_at: datetime
) -> list[model.Post]:
    """Bytes -> Posts. The one step both transports share verbatim."""
    parsed = parse.parse_story_nodes(bodies)
    return [
        model.build_post(
            parsed.stories[story_id],
            captured_at=captured_at,
            source=source,
            include_raw=include_raw,
        )
        for story_id in parsed.top_level_ids()
    ]


def _day_bounds(since: date | None, until: date | None) -> dict:
    """``--since``/``--until`` as the server-side window the timeline query takes.

    Confirmed enforced server-side (recon §7.3), which is why active mode can
    filter by date precisely instead of scrolling until it happens to see one.
    ``until`` is inclusive of its whole day, matching ``_in_window``'s
    date-granularity comparison.
    """
    bounds: dict = {}
    if since is not None:
        bounds["afterTime"] = int(
            datetime.combine(since, datetime.min.time(), tzinfo=UTC).timestamp()
        )
    if until is not None:
        bounds["beforeTime"] = int(
            datetime.combine(until, datetime.max.time(), tzinfo=UTC).timestamp()
        )
    return bounds


_PROFILE_ID_RE = re.compile(r'"userID":"(\d+)"')


def _resolve_profile_id(fetcher: graphql.ActiveFetcher, url: str) -> str:
    """The target profile's numeric id, from its own page HTML.

    ``userID`` on a profile page is the profile *being viewed* (verified:
    ``/zuck`` -> ``4``); the viewer's own id appears separately as ``actorID``.
    A ``profile.php?id=`` URL already carries it and skips the request.
    """
    direct = re.search(r"profile\.php\?id=(\d+)", url)
    if direct:
        return direct.group(1)
    html = fetcher.get(url)
    match = _PROFILE_ID_RE.search(html.decode("utf-8", errors="replace"))
    if not match:
        raise ActiveTransportError(f"could not resolve a numeric profile id from {url}")
    return match.group(1)


def open_fetcher(
    profile_dir: Path,
    profile_name: str,
    *,
    headless: bool = True,
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
) -> graphql.ActiveFetcher:
    """An active fetcher backed by this profile's (cached or refreshed) tokens."""
    session_tokens = tokens.get_tokens(profile_dir, profile_name, headless=headless)
    return graphql.ActiveFetcher(session_tokens, request_interval=request_interval)


def paginate_posts(
    fetcher: graphql.ActiveFetcher,
    spec: queries.QuerySpec,
    overrides: dict,
    *,
    source: str,
    limit: int | None,
    since: date | None = None,
    until: date | None = None,
    max_pages: int,
    raw: bool,
    referer: str | None = None,
) -> RetrieveResult:
    """Walk a post-bearing feed connection and normalize it into a result.

    Shared by every post-shaped surface — timeline, news feed, group, search —
    which differ only in their query spec and variables, never in how their
    pages are walked or parsed.
    """
    bodies: list[bytes] = []
    pages = 0
    stop_reason = scroll.STOP_FEED_EXHAUSTED
    for body in fetcher.paginate(spec, overrides, max_pages=max_pages, referer=referer):
        bodies.append(body)
        pages += 1
        # Stop paying for pages we already have enough posts to satisfy. Counted
        # on the merged parse rather than per-page, because one post's fields
        # can arrive split across pages (@defer).
        if limit is not None and len(parse.parse_story_nodes(bodies).top_level_ids()) >= limit:
            stop_reason = scroll.STOP_LIMIT_REACHED
            break
    else:
        if pages >= max_pages:
            stop_reason = STOP_MAX_PAGES

    captured_at = datetime.now(UTC)
    posts = _posts_from_bodies(bodies, source=source, include_raw=raw, captured_at=captured_at)
    filtered = _apply_window(posts, limit=limit, since=since, until=until)
    dated = [p.created_at for p in posts if p.created_at is not None and not p.is_pinned]

    return RetrieveResult(
        posts=filtered,
        stop_reason=stop_reason,
        since_reached=_since_reached(since, stop_reason),
        oldest_seen=min(dated) if dated else None,
        newest_seen=max(dated) if dated else None,
        scrolls_performed=0,
        transport="active",
    )


def _fetch_active(
    url: str,
    *,
    profile_dir: Path,
    profile_name: str,
    headless: bool,
    limit: int | None,
    since: date | None,
    until: date | None,
    request_interval: tuple[float, float],
    max_pages: int,
    raw: bool,
) -> RetrieveResult:
    """Read a profile timeline over HTTP GraphQL. No scrolling, no browser."""
    fetcher = open_fetcher(
        profile_dir, profile_name, headless=headless, request_interval=request_interval
    )
    return paginate_posts(
        fetcher,
        queries.QUERIES["timeline"],
        {"id": _resolve_profile_id(fetcher, url), **_day_bounds(since, until)},
        source="timeline",
        limit=limit,
        since=since,
        until=until,
        max_pages=max_pages,
        raw=raw,
        referer=url,
    )


@dataclass
class SearchResult:
    """Search returns mixed types: post-shaped hits and entity hits (plan §5)."""

    posts: list[model.Post]
    entities: list[search_mod.Entity]
    stop_reason: str


_GROUP_ID_RE = re.compile(r"facebook\.com/groups/(\d+)")
_GROUP_ID_HTML_RES = (
    re.compile(r'"groupID":"(\d+)"'),
    re.compile(r'"group_id":"?(\d+)"?'),
    re.compile(r"/groups/(\d+)/"),
)


def _resolve_group_id(fetcher: graphql.ActiveFetcher, identifier: str) -> str:
    """A group id, URL, or vanity slug -> the numeric id the feed query needs."""
    if identifier.isdigit():
        return identifier
    direct = _GROUP_ID_RE.search(identifier)
    if direct:
        return direct.group(1)

    url = (
        identifier
        if identifier.startswith("http")
        else f"https://www.facebook.com/groups/{identifier}/"
    )
    profiles.validate_permalink_url(url)
    html = fetcher.get(url).decode("utf-8", errors="replace")
    for pattern in _GROUP_ID_HTML_RES:
        match = pattern.search(html)
        if match:
            return match.group(1)
    raise ActiveTransportError(f"could not resolve a numeric group id from {identifier}")


def fetch_group(
    identifier: str,
    *,
    profile_dir: Path,
    profile_name: str = "default",
    headless: bool = True,
    limit: int | None = None,
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    max_pages: int = DEFAULT_MAX_PAGES,
    raw: bool = False,
) -> RetrieveResult:
    """Posts from one group's feed. Active-only."""
    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )
    fetcher = open_fetcher(
        profile_dir, profile_name, headless=headless, request_interval=request_interval
    )
    group_id = _resolve_group_id(fetcher, identifier)
    return paginate_posts(
        fetcher,
        queries.QUERIES["group"],
        {"id": group_id},
        source="group",
        limit=limit,
        max_pages=max_pages,
        raw=raw,
        referer=f"https://www.facebook.com/groups/{group_id}/",
    )


def search(
    query: str,
    *,
    profile_dir: Path,
    profile_name: str = "default",
    search_type: str = "top",
    headless: bool = True,
    limit: int | None = None,
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    max_pages: int = DEFAULT_MAX_PAGES,
    raw: bool = False,
) -> SearchResult:
    """Search Facebook. Active-only.

    ``search_type`` selects the vertical ("top", "posts", "people", "pages",
    "groups"). Post-shaped hits parse through the normal post path; people,
    page and group hits become ``Entity`` records instead.
    """
    if search_type not in search_mod.SEARCH_EXPERIENCE_TYPES:
        raise ValueError(
            f"unknown search type {search_type!r}: expected one of "
            f"{sorted(search_mod.SEARCH_EXPERIENCE_TYPES)}"
        )
    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )

    fetcher = open_fetcher(
        profile_dir, profile_name, headless=headless, request_interval=request_interval
    )
    spec = queries.QUERIES["search"]
    variables = queries.build_variables(spec, {})
    args = json.loads(json.dumps(variables["args"]))  # deep copy: don't mutate the registry
    args["text"] = query
    args["experience"]["type"] = search_mod.SEARCH_EXPERIENCE_TYPES[search_type]

    bodies: list[bytes] = []
    stop_reason = scroll.STOP_FEED_EXHAUSTED
    captured_at = datetime.now(UTC)
    wants_entities = search_mod.returns_entities(search_type)

    for page in range(max_pages):
        raw_page = fetcher.post(
            spec,
            {**variables, "args": args, "cursor": _search_cursor(bodies, spec)},
            referer=f"https://www.facebook.com/search/{search_type}/?q={query}",
        )
        bodies.append(raw_page)

        if limit is not None:
            got = (
                len(
                    search_mod.build_entities(
                        bodies, search_type=search_type, captured_at=captured_at
                    )
                )
                if wants_entities
                else len(parse.parse_story_nodes(bodies).top_level_ids())
            )
            if got >= limit:
                stop_reason = scroll.STOP_LIMIT_REACHED
                break

        page_info = graphql.find_page_info(raw_page, spec.connection_key)
        if not page_info or not page_info.get("has_next_page") or not page_info.get("end_cursor"):
            break
        if page + 1 >= max_pages:
            stop_reason = STOP_MAX_PAGES

    posts = (
        []
        if wants_entities
        else _posts_from_bodies(bodies, source="search", include_raw=raw, captured_at=captured_at)
    )
    entities = search_mod.build_entities(bodies, search_type=search_type, captured_at=captured_at)
    if not wants_entities:
        # A "top"/"posts" search still surfaces entity nodes (the author of every
        # post is entity-shaped); only report them for a genuinely mixed search.
        entities = entities if search_type == "top" else []

    if limit is not None:
        posts, entities = posts[:limit], entities[:limit]
    return SearchResult(posts=posts, entities=entities, stop_reason=stop_reason)


def _search_cursor(bodies: list[bytes], spec: queries.QuerySpec) -> str | None:
    if not bodies:
        return None
    page_info = graphql.find_page_info(bodies[-1], spec.connection_key)
    return page_info.get("end_cursor") if page_info else None


@dataclass
class CommentsResult:
    comments: list[comments_mod.Comment]
    post_id: str
    stop_reason: str


_STORY_ID_RE = re.compile(r'"storyID":"([^"]+)"')


def _resolve_story_id(fetcher: graphql.ActiveFetcher, url: str) -> str:
    """A post permalink -> the opaque ``storyID`` its dialog query needs.

    A permalink page returns **no** post GraphQL at all — the body is
    server-rendered into the HTML (recon §4) — so the id has to be read out of
    that HTML before anything can be queried.
    """
    profiles.validate_permalink_url(url)
    html = fetcher.get(url).decode("utf-8", errors="replace")
    match = _STORY_ID_RE.search(html)
    if not match:
        raise ActiveTransportError(f"could not find a story id on {url}")
    return match.group(1)


def _fetch_post_story(fetcher: graphql.ActiveFetcher, url: str) -> dict:
    """The single post's merged story dict, from its permalink URL.

    Anchors on the response's root node rather than parsing the whole payload:
    the dialog response also carries comment nodes, and comments are
    feedback-shaped, so a whole-payload parse reports a dozen "top-level posts"
    for one post.
    """
    story_id = _resolve_story_id(fetcher, url)
    spec = queries.QUERIES["post"]
    raw = fetcher.post(spec, queries.build_variables(spec, {"storyID": story_id}), referer=url)

    for chunk in graphql.iter_chunks(raw):
        data = chunk.get("data")
        if not isinstance(data, dict):
            continue
        root = data.get("node_v2") or data.get("node") or data.get("story")
        if isinstance(root, dict):
            parsed = parse.parse_story_nodes([json.dumps(root).encode()])
            top = parsed.top_level_ids()
            if top:
                return parsed.stories[top[0]]
    raise ActiveTransportError(f"no post found at {url}")


def fetch_post(
    url: str,
    *,
    profile_dir: Path,
    profile_name: str = "default",
    headless: bool = True,
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    raw: bool = False,
) -> model.Post:
    """One post, by permalink URL. Active-only."""
    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )
    fetcher = open_fetcher(
        profile_dir, profile_name, headless=headless, request_interval=request_interval
    )
    story = _fetch_post_story(fetcher, url)
    return model.build_post(
        story, captured_at=datetime.now(UTC), source="timeline", include_raw=raw
    )


def fetch_comments(
    url: str,
    *,
    profile_dir: Path,
    profile_name: str = "default",
    headless: bool = True,
    limit: int | None = None,
    sort: str = "top",
    replies: bool = False,
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> CommentsResult:
    """Comments on a post, by permalink URL. Active-only.

    ``sort`` picks the ``commentsIntentToken`` ("top" or "recent");
    ``replies`` additionally expands each top-level comment that has any,
    which costs one extra request per such comment.
    """
    if sort not in queries.COMMENT_SORT_TOKENS:
        raise ValueError(
            f"unknown sort {sort!r}: expected one of {sorted(queries.COMMENT_SORT_TOKENS)}"
        )
    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )

    fetcher = open_fetcher(
        profile_dir, profile_name, headless=headless, request_interval=request_interval
    )
    # The comment list is keyed by the post's FEEDBACK id, which the post query
    # is what actually establishes — hence resolving the post first.
    story = _fetch_post_story(fetcher, url)
    post_id = str(story["feedback"]["id"])
    intent = queries.COMMENT_SORT_TOKENS[sort]

    root_spec = queries.QUERIES["comments"]
    page_spec = queries.QUERIES["comments_page"]
    bodies = [
        fetcher.post(
            root_spec,
            queries.build_variables(root_spec, {"id": post_id, "commentsIntentToken": intent}),
            referer=url,
        )
    ]

    stop_reason = scroll.STOP_FEED_EXHAUSTED
    captured_at = datetime.now(UTC)
    for page in range(1, max_pages):
        found = comments_mod.build_comments(bodies, post_id=post_id, captured_at=captured_at)
        if limit is not None and len([c for c in found if c.depth == 0]) >= limit:
            stop_reason = scroll.STOP_LIMIT_REACHED
            break
        page_info = graphql.find_page_info(bodies[-1], root_spec.connection_key)
        if not page_info or not page_info.get("has_next_page") or not page_info.get("end_cursor"):
            break
        bodies.append(
            fetcher.post(
                page_spec,
                queries.build_variables(
                    page_spec,
                    {
                        "id": post_id,
                        "commentsAfterCursor": page_info["end_cursor"],
                        "commentsIntentToken": intent,
                    },
                ),
                referer=url,
            )
        )
        if page + 1 >= max_pages:
            stop_reason = STOP_MAX_PAGES

    if replies:
        reply_spec = queries.QUERIES["replies"]
        for node in list(comments_mod.iter_comment_nodes(bodies)):
            if (node.get("depth") or 0) != 0:
                continue
            token = comments_mod.expansion_token(node)
            comment_feedback = comments_mod.feedback_id(node)
            if not token or not comment_feedback:
                continue
            if not (node.get("feedback") or {}).get("replies_fields", {}).get("total_count"):
                continue
            try:
                bodies.append(
                    fetcher.post(
                        reply_spec,
                        queries.build_variables(
                            reply_spec,
                            {"id": comment_feedback, "expansionToken": token},
                        ),
                        referer=url,
                    )
                )
            except ActiveTransportError:
                # One comment's replies failing must not discard every comment
                # already retrieved.
                continue

    parsed = comments_mod.build_comments(bodies, post_id=post_id, captured_at=datetime.now(UTC))
    return CommentsResult(
        comments=_order_comments(parsed, limit=limit, replies=replies),
        post_id=post_id,
        stop_reason=stop_reason,
    )


def _order_comments(
    parsed: list[comments_mod.Comment], *, limit: int | None, replies: bool
) -> list[comments_mod.Comment]:
    """Apply ``--limit`` to top-level comments, then nest each one's replies under it.

    ``limit`` counts top-level comments only — a comment with 40 replies should
    not consume the whole budget. Replies are emitted directly after their
    parent rather than in arrival order: they arrive in a separate response
    appended after every top-level page, so raw order would put every reply at
    the very end, detached from the comment it answers (and would fall outside
    a truncating limit entirely).
    """
    tops = [c for c in parsed if c.depth == 0]
    if limit is not None:
        tops = tops[:limit]
    if not replies:
        return tops

    kept_ids = {c.id for c in tops}
    by_parent: dict[str | None, list[comments_mod.Comment]] = {}
    for comment in parsed:
        if comment.depth > 0:
            by_parent.setdefault(comment.parent_id, []).append(comment)

    ordered: list[comments_mod.Comment] = []
    for top in tops:
        ordered.append(top)
        ordered.extend(by_parent.get(top.id, []))
    # Replies whose parent id didn't resolve still belong in the output as long
    # as their parent survived the limit — dropping them would silently lose
    # data over a field we merely failed to read.
    orphans = [
        c
        for parent_id, group in by_parent.items()
        if parent_id not in kept_ids
        for c in group
        if parent_id is None
    ]
    return ordered + orphans


def fetch_feed(
    *,
    profile_dir: Path,
    profile_name: str = "default",
    headless: bool = True,
    limit: int | None = None,
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    max_pages: int = DEFAULT_MAX_PAGES,
    raw: bool = False,
) -> RetrieveResult:
    """Read the home news feed.

    Active-only: unlike ``fetch``, there is no pre-existing browser-scroll path
    for this surface to fall back to. No ``--since``/``--until`` either — the
    home feed's query takes no date window (only the profile timeline does), so
    offering one would be a filter that silently doesn't filter.
    """
    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )
    fetcher = open_fetcher(
        profile_dir, profile_name, headless=headless, request_interval=request_interval
    )
    return paginate_posts(
        fetcher,
        queries.QUERIES["newsfeed"],
        {},
        source="newsfeed",
        limit=limit,
        max_pages=max_pages,
        raw=raw,
    )


def fetch_profile(
    url: str,
    *,
    profile_dir: Path,
    profile_name: str = "default",
    mode: str = "auto",
    headless: bool = True,
    limit: int | None = None,
    since: date | None = None,
    until: date | None = None,
    scroll_pause: tuple[float, float] = (2.0, 4.0),
    request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    max_scrolls: int = 40,
    max_pages: int = DEFAULT_MAX_PAGES,
    raw: bool = False,
) -> RetrieveResult:
    """Fetch a profile timeline, active-first with a passive browser fallback.

    ``mode``: ``"auto"`` (active, falling back to passive), ``"active"``, or
    ``"passive"``. A fallback is never silent — it says so on stderr, because
    "why is this suddenly slow" should not require reading the source.
    """
    if mode not in ("auto", "active", "passive"):
        raise ValueError(f"unknown mode {mode!r}: expected auto, active, or passive")

    if not profile_dir.exists():
        raise LoginRequiredError(
            f"No login profile at {profile_dir}. Run: scrape-fb login --profile <name>"
        )

    if mode in ("auto", "active"):
        try:
            return _fetch_active(
                url,
                profile_dir=profile_dir,
                profile_name=profile_name,
                headless=headless,
                limit=limit,
                since=since,
                until=until,
                request_interval=request_interval,
                max_pages=max_pages,
                raw=raw,
            )
        except ActiveTransportError as exc:
            # A rotated doc_id or a transport hiccup — the browser path reads
            # the same data a slower way, so this is recoverable (recon §6).
            if mode == "active":
                raise
            print(
                f"scrape-fb: active mode failed ({exc}); falling back to browser", file=sys.stderr
            )

    return _fetch_passive(
        url,
        profile_dir=profile_dir,
        headless=headless,
        limit=limit,
        since=since,
        until=until,
        scroll_pause=scroll_pause,
        max_scrolls=max_scrolls,
        raw=raw,
    )


def _fetch_passive(
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
        captured_at = datetime.now(UTC)
        posts = _posts_from_bodies(
            bodies, source="timeline", include_raw=raw, captured_at=captured_at
        )

        filtered = _apply_window(posts, limit=limit, since=since, until=until)

        def fetch_permalink_bodies(permalink_url: str) -> list[bytes]:
            # Validated here, NOT via normalize_target_identifier — that
            # function truncates its input down to a bare profile URL, which
            # would silently mangle a post permalink's full path. This still
            # closes the same gap: an unvalidated string from parsed post
            # content must not reach the authenticated browser unchecked.
            try:
                profiles.validate_permalink_url(permalink_url)
            except InvalidIdentifierError:
                return []
            time.sleep(random.uniform(*scroll_pause))
            permalink_response = session.fetch(permalink_url, timeout=30000)
            return [xhr.body for xhr in permalink_response.captured_xhr]

        # Only top-level posts are resolved in v1 — resolving a nested
        # shared_post too would mean another permalink fetch per share, and
        # the scope/value tradeoff isn't worth it yet (roadmap candidate).
        for post in filtered:
            if post.text_truncated and not post.text_resolved and post.url:
                # One bad permalink (dead link, redirect, timeout) must not
                # discard every other already-fetched, already-parsed post —
                # skip resolving just this one and move on.
                try:
                    resolved = truncation.resolve_truncated_text(post.url, fetch_permalink_bodies)
                except Exception:
                    resolved = None
                if resolved:
                    post.text = resolved
                    post.text_resolved = True

    # `outcome.stop_reason` staying None here means scroll() raised before
    # reaching any of its own stop_reason assignments — an exception inside a
    # scrapling page_action is swallowed (see scroll.py's module docstring),
    # so this is the only place that can notice. Falling back to
    # STOP_MAX_SCROLLS would mislabel a genuine crash as a normal, complete
    # 40/40-scroll run; report it honestly instead.
    stop_reason = outcome.stop_reason or scroll.STOP_UNKNOWN_ERROR
    return RetrieveResult(
        posts=filtered,
        stop_reason=stop_reason,
        since_reached=_since_reached(since, stop_reason),
        oldest_seen=outcome.oldest_non_pinned_seen,
        newest_seen=outcome.newest_non_pinned_seen,
        scrolls_performed=outcome.scrolls_performed,
        transport="passive",
    )
