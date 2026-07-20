"""Search result typing. Fixtures synthetic, shaped like real search nodes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scraper_for_facebook import search

CAPTURED_AT = datetime(2026, 7, 20, tzinfo=UTC)


def _entity(entity_id: str, typename: str = "User", *, verified=None, name="Someone") -> dict:
    node = {
        "__typename": typename,
        "id": entity_id,
        "name": name,
        "url": f"https://www.facebook.com/{entity_id}",
    }
    if verified is not None:
        node["is_verified"] = verified
    return node


def _body(*nodes: dict) -> bytes:
    return json.dumps(
        {"data": {"serpResponse": {"results": {"edges": [{"node": n} for n in nodes]}}}}
    ).encode()


@pytest.mark.parametrize(
    ("search_type", "expected"),
    [("people", "person"), ("pages", "page"), ("groups", "group")],
)
def test_entity_kind_comes_from_the_requested_vertical(search_type, expected):
    """Facebook returns Pages typed as "User" here, so the payload cannot tell a
    page from a person — the vertical that was asked for is authoritative."""
    entities = search.build_entities(
        [_body(_entity("1", "User"))], search_type=search_type, captured_at=CAPTURED_AT
    )
    assert [e.kind for e in entities] == [expected]


def test_top_search_falls_back_to_typename():
    bodies = [_body(_entity("1", "Group"), _entity("2", "User"))]

    entities = search.build_entities(bodies, search_type="top", captured_at=CAPTURED_AT)

    assert [(e.id, e.kind) for e in entities] == [("1", "group"), ("2", "person")]


def test_entities_are_deduped_by_id_across_pages():
    bodies = [_body(_entity("1"), _entity("2")), _body(_entity("2"), _entity("3"))]

    entities = search.build_entities(bodies, search_type="people", captured_at=CAPTURED_AT)

    assert [e.id for e in entities] == ["1", "2", "3"]


def test_entity_fields_map_through():
    entities = search.build_entities(
        [_body(_entity("42", verified=True, name="A Page"))],
        search_type="pages",
        captured_at=CAPTURED_AT,
    )
    entity = entities[0]

    assert (entity.id, entity.name, entity.verified) == ("42", "A Page", True)
    assert entity.url == "https://www.facebook.com/42"


def test_missing_verified_flag_is_null_not_false():
    """Absent != false — a group payload simply omits it, and guessing would lie."""
    entities = search.build_entities(
        [_body(_entity("1", "Group"))], search_type="groups", captured_at=CAPTURED_AT
    )
    assert entities[0].verified is None


def test_nodes_without_a_url_or_name_are_not_entities():
    partial = {"__typename": "User", "id": "1"}
    assert (
        search.build_entities([_body(partial)], search_type="people", captured_at=CAPTURED_AT) == []
    )


def test_every_search_type_maps_to_an_experience_type():
    assert set(search.SEARCH_EXPERIENCE_TYPES) == {"top", "posts", "people", "pages", "groups"}
    assert search.SEARCH_EXPERIENCE_TYPES["people"] == "PEOPLE_TAB"
    assert search.returns_entities("people")
    assert not search.returns_entities("posts")


def test_entity_schema_matches_to_dict_keys():
    sample = search.build_entities(
        [_body(_entity("1"))], search_type="people", captured_at=CAPTURED_AT
    )[0].to_dict()
    assert {f["name"] for f in search.schema_fields()} == set(sample)
    assert search.json_schema()["title"] == "Entity"
