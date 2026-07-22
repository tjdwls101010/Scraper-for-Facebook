"""Search result shaping (plan §5).

Search is the one surface that returns mixed result types: a "top" search
interleaves posts with people, pages and groups, and only the post-shaped ones
are story-shaped enough for ``parse.py`` (recon §4). Non-post hits become a
light :class:`Entity` instead.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .model import _iso, build_json_schema, build_schema_fields

#: CLI ``--type`` -> the ``args.experience.type`` that selects that vertical.
#: Captured live; the doc_id is identical across all five.
SEARCH_EXPERIENCE_TYPES = {
    "top": "GLOBAL_SEARCH",
    "posts": "POSTS_TAB",
    "people": "PEOPLE_TAB",
    "pages": "PAGES_TAB",
    "groups": "GROUPS_TAB",
}

#: Which ``--type`` values return entities rather than posts, and as what kind.
#: The requested vertical is authoritative — Facebook returns Pages with
#: ``__typename: "User"`` here, so the payload alone cannot tell a page from a
#: person. Only "top" has to fall back to guessing from ``__typename``.
_ENTITY_KIND_BY_TYPE = {"people": "person", "pages": "page", "groups": "group"}


@dataclass
class Entity:
    kind: str  # "person" | "page" | "group"
    id: str
    name: str | None
    url: str | None
    verified: bool | None
    captured_at: datetime

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "verified": self.verified,
            "captured_at": _iso(self.captured_at),
        }


FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "kind": (
        "string",
        "person | page | group. Its presence is also what distinguishes an entity from a "
        "Post in mixed search output — Posts carry `source` instead.",
    ),
    "id": ("string", "Numeric id — the handle to chain into `fetch` or `group`."),
    "name": ("string | null", "Display name."),
    "url": ("string | null", "Facebook URL for this person, page, or group."),
    "verified": ("boolean | null", "Verified badge, or null when the payload omits it."),
    "captured_at": (
        "string",
        "ISO-8601 UTC timestamp of when this tool captured the response.",
    ),
}


def _representative() -> Entity:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Entity(kind="person", id="1", name=None, url=None, verified=None, captured_at=now)


def schema_fields() -> list[dict]:
    return build_schema_fields(_representative().to_dict(), FIELD_DESCRIPTIONS, optional=set())


def json_schema() -> dict:
    return build_json_schema(
        "Entity",
        "A non-post search hit (person, page, or group).",
        schema_fields(),
    )


_ENTITY_TYPENAMES = {"User", "Page", "Group"}


def _is_entity_shaped(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("__typename") in _ENTITY_TYPENAMES
        and obj.get("id") is not None
        and isinstance(obj.get("name"), str)
        and isinstance(obj.get("url"), str)
    )


def iter_entity_nodes(bodies: Iterable[bytes]) -> Iterator[dict]:
    def walk(obj: Any) -> Iterator[dict]:
        if isinstance(obj, dict):
            if _is_entity_shaped(obj):
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


def build_entities(
    bodies: Iterable[bytes], *, search_type: str, captured_at: datetime
) -> list[Entity]:
    """De-duplicated entity hits, in first-seen order."""
    default_kind = _ENTITY_KIND_BY_TYPE.get(search_type)
    seen: set[str] = set()
    result: list[Entity] = []
    for node in iter_entity_nodes(bodies):
        entity_id = str(node["id"])
        if entity_id in seen:
            continue
        seen.add(entity_id)
        kind = default_kind or ("group" if node.get("__typename") == "Group" else "person")
        result.append(
            Entity(
                kind=kind,
                id=entity_id,
                name=node.get("name"),
                url=node.get("url"),
                verified=node.get("is_verified")
                if isinstance(node.get("is_verified"), bool)
                else None,
                captured_at=captured_at,
            )
        )
    return result


def returns_entities(search_type: str) -> bool:
    return search_type in _ENTITY_KIND_BY_TYPE
