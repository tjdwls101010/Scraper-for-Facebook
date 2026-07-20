"""Comment schema and extraction (plan §5).

Comments need their own extraction path rather than reusing ``parse.py``:
a comment node carries its own ``feedback`` object, so the story walker
counts comments as top-level *posts*. The two shapes are told apart by the
``depth`` + ``author`` + ``body`` triple that only comments have.

``depth`` maps exactly onto the agreed design (recon §3): ``0`` is a
top-level comment, ``>= 1`` is a reply.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .model import _iso, build_json_schema, build_schema_fields


@dataclass
class Comment:
    id: str
    post_id: str  # feedback id of the post this comment belongs to
    author_name: str | None
    author_url: str | None
    author_id: str | None
    text: str
    created_at: datetime | None
    depth: int  # 0 = top-level, >= 1 = reply
    parent_id: str | None
    reaction_count: int | None
    reply_count: int | None
    captured_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "post_id": self.post_id,
            "author_name": self.author_name,
            "author_url": self.author_url,
            "author_id": self.author_id,
            "text": self.text,
            "created_at": _iso(self.created_at),
            "depth": self.depth,
            "parent_id": self.parent_id,
            "reaction_count": self.reaction_count,
            "reply_count": self.reply_count,
            "captured_at": _iso(self.captured_at),
        }


FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "id": ("string", "Stable identity/dedup key for this comment."),
    "post_id": (
        "string",
        "Feedback id of the post this comment belongs to — matches a Post's `id`, so "
        "comments and posts can be joined.",
    ),
    "author_name": ("string | null", "Display name of the comment's author."),
    "author_url": (
        "string | null",
        "Profile URL of the comment's author — the handle to chain into `fetch`.",
    ),
    "author_id": ("string | null", "Numeric id of the comment's author."),
    "text": (
        "string",
        "The comment body; empty string if it has none (e.g. a sticker-only reply).",
    ),
    "created_at": (
        "string | null",
        "ISO-8601 UTC timestamp with a 'Z' suffix; null if it could not be located.",
    ),
    "depth": ("integer", "0 for a top-level comment, 1 or more for a reply."),
    "parent_id": ("string | null", "Id of the comment this one replies to; null at depth 0."),
    "reaction_count": ("integer | null", "Reactions on this comment, or null if unavailable."),
    "reply_count": ("integer | null", "Replies to this comment, or null if unavailable."),
    "captured_at": (
        "string",
        "ISO-8601 UTC timestamp of when this tool captured the response. Changes every "
        "run — never a dedup key.",
    ),
}


def _representative() -> Comment:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Comment(
        id="1",
        post_id="1",
        author_name=None,
        author_url=None,
        author_id=None,
        text="",
        created_at=now,
        depth=0,
        parent_id=None,
        reaction_count=None,
        reply_count=None,
        captured_at=now,
    )


def schema_fields() -> list[dict]:
    return build_schema_fields(_representative().to_dict(), FIELD_DESCRIPTIONS, optional=set())


def json_schema() -> dict:
    return build_json_schema(
        "Comment",
        "One element of the comments output array (or one NDJSON line).",
        schema_fields(),
    )


# --- extraction ---------------------------------------------------------------


def _is_comment_shaped(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and "depth" in obj
        and isinstance(obj.get("author"), dict)
        and isinstance(obj.get("body"), dict | type(None))
        and obj.get("id") is not None
    )


def iter_comment_nodes(bodies: Iterable[bytes]) -> Iterator[dict]:
    """Every comment-shaped node across the given response bodies, in order."""

    def walk(obj: Any) -> Iterator[dict]:
        if isinstance(obj, dict):
            if _is_comment_shaped(obj):
                yield obj
            for value in obj.values():
                yield from walk(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from walk(item)

    for body in bodies:
        for line in body.decode("utf-8", errors="replace").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield from walk(chunk)


def _count(node: dict, *path: str) -> int | None:
    current: Any = node
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, int) else None


def reaction_count(node: dict) -> int | None:
    """Reactions on a comment — which live nowhere near where a post keeps them.

    A comment's own ``feedback.reaction_count`` is always null; what it carries
    is ``feedback.reactors.count_reduced``, a *display string* ("6", and "1.2K"
    once the number is large enough to abbreviate). The exact integer is in the
    comment's action-links subtree, so that is preferred and the display string
    is only parsed as a last resort — and only when it is plainly numeric,
    since guessing at "1.2K" would invent precision.
    """
    feedback = node.get("feedback") or {}
    for path in (("reactors", "count"), ("unified_reactors", "count"), ("reaction_count", "count")):
        value = _count(feedback, *path)
        if value is not None:
            return value

    for link in node.get("comment_action_links") or []:
        if isinstance(link, dict):
            value = _count(link, "comment", "feedback", "reactors", "count")
            if value is not None:
                return value

    reduced = (feedback.get("reactors") or {}).get("count_reduced")
    if isinstance(reduced, str) and reduced.isdigit():
        return int(reduced)
    return None


def expansion_token(node: dict) -> str | None:
    """The handle that expands this comment's replies (``Depth1CommentsListPaginationQuery``).

    Replies are never delivered inline — ``replies_connection.edges`` comes back
    empty even when ``replies_fields.total_count`` is non-zero, so fetching them
    costs one extra request per comment that has any.
    """
    feedback = node.get("feedback")
    if not isinstance(feedback, dict):
        return None
    info = feedback.get("expansion_info")
    if not isinstance(info, dict):
        return None
    token = info.get("expansion_token")
    return token if isinstance(token, str) else None


def feedback_id(node: dict) -> str | None:
    feedback = node.get("feedback")
    return feedback.get("id") if isinstance(feedback, dict) else None


def build_comment(node: dict, *, post_id: str, captured_at: datetime) -> Comment:
    author = node.get("author") or {}
    body = node.get("body") or {}
    parent = node.get("comment_direct_parent") or {}
    created = node.get("created_time")
    author_id = author.get("id")

    return Comment(
        id=str(node["id"]),
        post_id=post_id,
        author_name=author.get("name") if isinstance(author.get("name"), str) else None,
        author_url=author.get("url") if isinstance(author.get("url"), str) else None,
        author_id=str(author_id) if author_id is not None else None,
        text=body.get("text") if isinstance(body.get("text"), str) else "",
        created_at=datetime.fromtimestamp(created, tz=UTC) if isinstance(created, int) else None,
        depth=node.get("depth") if isinstance(node.get("depth"), int) else 0,
        parent_id=str(parent["id"]) if isinstance(parent, dict) and parent.get("id") else None,
        reaction_count=reaction_count(node),
        reply_count=_count(node, "feedback", "replies_fields", "total_count"),
        captured_at=captured_at,
    )


def build_comments(
    bodies: Iterable[bytes], *, post_id: str, captured_at: datetime
) -> list[Comment]:
    """Parse and de-duplicate every comment in ``bodies``, preserving first-seen order."""
    seen: set[str] = set()
    result: list[Comment] = []
    for node in iter_comment_nodes(bodies):
        comment = build_comment(node, post_id=post_id, captured_at=captured_at)
        if comment.id in seen:
            continue
        seen.add(comment.id)
        result.append(comment)
    return result
