"""Turn captured GraphQL response bodies into merged story dicts (plan §8).

Pipeline: bytes -> decoded text -> NDJSON lines -> parsed JSON objects ->
story-shaped nodes found anywhere in the tree -> deep-merged by ``feedback.id``
-> top-level vs. shared/quoted (``attached_story``) split.

Design choice, deliberately not literally "anchor on data.node" (plan §8's
literal wording): Facebook's ``@defer``/``@stream`` follow-up chunks are not
guaranteed to repeat a ``data.node`` envelope — confirmed via live capture,
they patch fields in via a ``path`` array instead (e.g.
``path: ["node", "timeline_list_feed_units", "edges", 1]``), addressed by
array index, not by repeating ``feedback.id``. Anchoring purely on the
STRUCTURAL nesting of ``feedback.id``-bearing nodes (a story is "top-level"
unless it is reachable only through some other story's ``attached_story``)
achieves the same correctness goal — no double-counting a shared/quoted post
— without depending on an envelope shape at all.

Confirmed via live capture: ``creation_time``, ``permalink_url``/``wwwURL``,
and ``message.text`` are exactly where §8's field map hinted. Also confirmed,
and NOT anticipated by that field map: a post's inline "top comment" preview
is its own feedback-shaped object (nested under
``interesting_top_level_comments``, reached without ever passing through
``attached_story``) that must be excluded the same way a share is, or it's
miscounted as an independent top-level post. Media/link extraction paths are
still unconfirmed — the probed profile had no media or link attachments.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

# --- bytes -> JSON objects ----------------------------------------------------


def iter_json_objects(bodies: Iterable[bytes]) -> Iterator[dict]:
    """Decode captured response bodies and yield each NDJSON line's parsed object.

    ``Response.body`` is raw bytes (scrapling, verified against 0.4.10 source) —
    decoding must happen here, explicitly, before any string operation.
    Unparseable lines are skipped rather than raising: a single malformed line
    (e.g. a truncated stream) must not lose every other post in the batch.
    """
    for body in bodies:
        text = body.decode("utf-8", errors="replace")
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


# --- deep merge ----------------------------------------------------------------


def deep_merge(a: dict, b: dict) -> dict:
    """Merge ``b`` into ``a``: non-null wins, dicts recurse, id-keyed lists union.

    ``@defer`` ships a story in pieces across multiple lines/bodies (plan
    §8 G-ndjson-defer) — picking "the more complete" instance silently drops
    whichever fields only live in the other one.
    """
    result = dict(a)
    for key, b_val in b.items():
        if b_val is None:
            continue
        a_val = result.get(key)
        if a_val is None:
            result[key] = b_val
        elif isinstance(a_val, dict) and isinstance(b_val, dict):
            result[key] = deep_merge(a_val, b_val)
        elif isinstance(a_val, list) and isinstance(b_val, list):
            result[key] = _merge_lists(a_val, b_val)
        # else: both non-null scalars that disagree — keep the first seen.
    return result


def _merge_lists(a: list, b: list) -> list:
    if a and isinstance(a[0], dict) and "id" in a[0]:
        by_id: dict[Any, dict] = {}
        order: list[Any] = []
        for item in a:
            if isinstance(item, dict) and "id" in item:
                by_id[item["id"]] = item
                order.append(item["id"])
        for item in b:
            if isinstance(item, dict) and "id" in item:
                item_id = item["id"]
                if item_id in by_id:
                    by_id[item_id] = deep_merge(by_id[item_id], item)
                else:
                    by_id[item_id] = item
                    order.append(item_id)
        return [by_id[i] for i in order]
    # No id key to union by (e.g. an "attachments" list) — picking one list
    # wholesale (the old "longer wins" rule) silently drops a genuinely new
    # item the OTHER list has whenever it isn't the longer one. Concatenate
    # and dedupe by content instead, so a distinct item from either side
    # always survives.
    combined: list = []
    seen_keys: set[str] = set()
    for item in (*a, *b):
        try:
            key = json.dumps(item, sort_keys=True, default=str)
        except TypeError:
            key = repr(item)
        if key not in seen_keys:
            seen_keys.add(key)
            combined.append(item)
    return combined


# --- story-node discovery -------------------------------------------------------


def _is_story_shaped(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("feedback"), dict)
        and obj["feedback"].get("id") is not None
    )


# KNOWN LIMITATION (pending further live-probe validation): a @defer patch
# chunk that updates a nested field (e.g. reaction_count) WITHOUT repeating
# feedback.id is invisible to _walk — it's simply never recognized as
# story-shaped, so its data is silently dropped rather than merged. This
# mirrors the plan's stated merge key (feedback.id) rather than inventing an
# unverified fallback (e.g. reading a GraphQL `path` array) without real
# capture data to design it against.

#: Confirmed via live capture (2026-07): a post's inline "top comment"
#: preview is a SEPARATE feedback-shaped object nested under this key
#: (path seen: comet_sections.feedback.story.story_ufi_container.story.
#: feedback_context.interesting_top_level_comments[].comment) — reached
#: without ever passing through attached_story, so it would otherwise be
#: misidentified as an independent top-level post. It is a comment, not a
#: post or a share: skipped entirely, never merged, never top-level.
_NON_POST_CONTAINER_KEYS = frozenset({"interesting_top_level_comments"})


def _walk(
    obj: Any, stories: dict[str, dict], top_level_seen: set[str], *, is_nested_share: bool
) -> None:
    if isinstance(obj, dict):
        if _is_story_shaped(obj):
            story_id = str(obj["feedback"]["id"])
            if not is_nested_share:
                # A story earns top-level status if EVER encountered outside
                # someone else's attached_story, even if it's ALSO nested
                # under a share elsewhere in the same capture (a friend can
                # reshare a post that's also, independently, in your own
                # feed) — tracking this positively, rather than recording
                # "seen as a child" and excluding by that, means a later or
                # earlier top-level sighting can't be permanently discarded.
                top_level_seen.add(story_id)
            stories[story_id] = (
                deep_merge(stories[story_id], obj) if story_id in stories else dict(obj)
            )

            attached = obj.get("attached_story")
            if isinstance(attached, dict):
                _walk(attached, stories, top_level_seen, is_nested_share=True)

        for key, value in obj.items():
            if key == "attached_story" or key in _NON_POST_CONTAINER_KEYS:
                continue
            _walk(value, stories, top_level_seen, is_nested_share=is_nested_share)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, stories, top_level_seen, is_nested_share=is_nested_share)


@dataclass
class ParsedStories:
    stories: dict[str, dict]  # feedback.id -> deep-merged raw story dict
    top_level_seen: set[str]  # ids ever encountered outside someone else's attached_story

    def top_level_ids(self) -> list[str]:
        """IDs of stories ever seen outside someone else's ``attached_story``."""
        return [story_id for story_id in self.stories if story_id in self.top_level_seen]


def parse_story_nodes(bodies: Iterable[bytes]) -> ParsedStories:
    """Return every distinct, fully deep-merged story found across ``bodies``.

    Keyed by ``feedback.id``. Includes BOTH top-level posts and shared/quoted
    posts nested under someone's ``attached_story`` — use
    :meth:`ParsedStories.top_level_ids` to tell them apart. Merging everything
    first (before filtering) means a shared post whose own fields arrive split
    across ``@defer`` chunks is still merged correctly.
    """
    stories: dict[str, dict] = {}
    top_level_seen: set[str] = set()
    for obj in iter_json_objects(bodies):
        _walk(obj, stories, top_level_seen, is_nested_share=False)
    return ParsedStories(stories=stories, top_level_seen=top_level_seen)


# --- field extraction (best-effort — see module docstring) ---------------------


def iter_story_dicts(obj: Any, *, exclude_keys: frozenset[str] = frozenset()) -> Iterator[dict]:
    """DFS over every nested dict in ``obj``, not descending into ``exclude_keys``."""
    if isinstance(obj, dict):
        yield obj
        for key, value in obj.items():
            if key in exclude_keys:
                continue
            yield from iter_story_dicts(value, exclude_keys=exclude_keys)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_story_dicts(item, exclude_keys=exclude_keys)


SHARE_EXCLUDE = frozenset({"attached_story", *_NON_POST_CONTAINER_KEYS})


def find_creation_time(story: dict) -> int | None:
    """The story's own ``creation_time`` — a direct key on the story root only.

    Deliberately NOT a recursive search: the plan's decoy-int fixture exists
    precisely because "any int in the tree" grabs the wrong value (an edit
    time, a nested attachment's timestamp, a cache-busting int). Restricting
    to a direct key on the merged story dict is the exact-path discipline
    plan §8 asks for. Confirmed via live capture: this is exactly where it
    lives on a real post.
    """
    value = story.get("creation_time")
    return value if isinstance(value, int) else None


def find_permalink(story: dict) -> str | None:
    """The story's permalink. Confirmed via live capture: ``permalink_url`` is
    a direct root key (as reliable a lookup as ``creation_time``); ``wwwURL``
    is the same URL repeated deeper in ``comet_sections``, kept as a fallback.
    """
    value = story.get("permalink_url")
    if isinstance(value, str):
        return value
    value = story.get("wwwURL")
    if isinstance(value, str):
        return value
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        if node is story:
            continue
        value = node.get("wwwURL")
        if isinstance(value, str):
            return value
    return None


def find_message_text(story: dict) -> str | None:
    """First non-empty ``message.text`` reachable from the story root (own text only)."""
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        message = node.get("message")
        if isinstance(message, dict):
            text = message.get("text")
            if isinstance(text, str) and text:
                return text
    return None


def find_actors(story: dict) -> list[dict]:
    """Actor dicts (name/url/id) — prefers a key literally named ``actors``."""
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        actors = node.get("actors")
        if isinstance(actors, list) and actors and all(isinstance(a, dict) for a in actors):
            return actors
    return []


def find_media(story: dict) -> list[dict]:
    """Media-shaped dicts: anything with an ``image``/``uri`` pair or a playable video URL.

    A video attachment carries BOTH an ``image`` (its poster thumbnail) and a
    ``playable_url`` (the actual video) as siblings — the thumbnail's own kind
    is still "image" regardless of that sibling; only the ``playable_url``
    entry is "video".
    """
    media: list[dict] = []
    seen_urls: set[str] = set()
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        image = node.get("image")
        if isinstance(image, dict) and isinstance(image.get("uri"), str):
            url = image["uri"]
            if url not in seen_urls:
                seen_urls.add(url)
                media.append(
                    {
                        "kind": "image",
                        "url": url,
                        "width": image.get("width"),
                        "height": image.get("height"),
                    }
                )
        playable = node.get("playable_url") or node.get("playable_url_quality_hd")
        if isinstance(playable, str) and playable not in seen_urls:
            seen_urls.add(playable)
            media.append({"kind": "video", "url": playable, "width": None, "height": None})
    return media


def find_links(story: dict) -> list[dict]:
    """External link-share attachments: a dict carrying ``url`` + (``title`` or ``description``)."""
    links: list[dict] = []
    seen_urls: set[str] = set()
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        url = node.get("url")
        if (
            isinstance(url, str)
            and url not in seen_urls
            and ("title" in node or "description" in node)
            and "uri" not in node  # exclude media dicts, which use "uri" not "url"
        ):
            seen_urls.add(url)
            links.append(
                {
                    "url": url,
                    "title": node.get("title") if isinstance(node.get("title"), str) else None,
                    "description": node.get("description")
                    if isinstance(node.get("description"), str)
                    else None,
                }
            )
    return links
