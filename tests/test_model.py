from datetime import UTC, datetime

from scraper_for_facebook import parse
from scraper_for_facebook.model import (
    FIELD_DESCRIPTIONS,
    LinkAttachment,
    Media,
    Post,
    build_post,
    json_schema,
    schema_fields,
)

CAPTURED_AT = datetime(2026, 7, 5, tzinfo=UTC)


def test_build_post_basic_fields(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("basic_status_post.ndjson")])
    post = build_post(parsed.stories["fb_001"], captured_at=CAPTURED_AT, source="timeline")
    assert post.id == "fb_001"
    assert post.author_name == "Synthetic Alice"
    assert post.author_id == "100000000000001"
    assert post.created_at == datetime(2025, 6, 15, 15, 6, 40, tzinfo=UTC)
    assert post.text == "Hello world, this is a simple synthetic status post."
    assert post.reaction_count == 12
    assert post.comment_count == 3
    assert post.share_count == 1
    assert post.type == "status"
    assert post.is_pinned is False
    assert post.raw is None


def test_build_post_include_raw(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("basic_status_post.ndjson")])
    post = build_post(
        parsed.stories["fb_001"], captured_at=CAPTURED_AT, source="timeline", include_raw=True
    )
    assert post.raw is not None
    assert post.raw["feedback"]["id"] == "fb_001"


def test_build_post_shared_post_nested_one_level(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("shared_post.ndjson")])
    post = build_post(parsed.stories["fb_003_wrapper"], captured_at=CAPTURED_AT, source="timeline")
    assert post.type == "shared"
    assert post.shared_post is not None
    assert post.shared_post.id == "fb_003_shared_original"
    assert post.shared_post.author_name == "Synthetic Bob"
    assert post.shared_post.text == "This is the original synthetic shared post content."


def test_build_post_pinned_flag_and_decoy_creation_time(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("pinned_decoy_and_missing_date.ndjson")])
    pinned_post = build_post(
        parsed.stories["fb_004_pinned"], captured_at=CAPTURED_AT, source="timeline"
    )
    assert pinned_post.is_pinned is True
    assert pinned_post.created_at.timestamp() == 1750000400

    no_date_post = build_post(
        parsed.stories["fb_004_no_date"], captured_at=CAPTURED_AT, source="timeline"
    )
    assert no_date_post.created_at is None


def test_build_post_truncation_marker_sets_flag_but_not_resolved(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("truncated_post.ndjson")])
    post = build_post(parsed.stories["fb_005"], captured_at=CAPTURED_AT, source="timeline")
    assert post.text_truncated is True
    assert post.text_resolved is False
    assert post.text == "This synthetic post got cut off and..."


def test_build_post_media_and_link_types(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("media_and_links.ndjson")])
    post = build_post(parsed.stories["fb_006"], captured_at=CAPTURED_AT, source="timeline")
    assert len(post.media) == 2
    assert len(post.links) == 1
    assert post.type == "video"  # pins the documented video-over-photo precedence


def test_post_to_dict_serializes_datetimes_as_iso_utc_z():
    post = Post(
        id="1",
        url=None,
        type="status",
        is_pinned=False,
        author_name=None,
        author_url=None,
        author_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        edited_at=None,
        text="hi",
        text_truncated=False,
        text_resolved=False,
        media=[Media(kind="image", url="https://example.test/x.jpg", width=1, height=1)],
        links=[LinkAttachment(url="https://example.test", title=None, description=None)],
        reaction_count=None,
        comment_count=None,
        share_count=None,
        shared_post=None,
        source="timeline",
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    data = post.to_dict()
    assert data["created_at"] == "2026-01-01T00:00:00Z"
    assert data["captured_at"] == "2026-01-02T00:00:00Z"
    assert data["media"][0]["url"] == "https://example.test/x.jpg"
    assert "raw" not in data  # omitted entirely when None, not emitted as null


def test_post_to_dict_includes_raw_only_when_set():
    post = Post(
        id="1",
        url=None,
        type="status",
        is_pinned=False,
        author_name=None,
        author_url=None,
        author_id=None,
        created_at=None,
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
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw={"secret": "stuff"},
    )
    assert post.to_dict()["raw"] == {"secret": "stuff"}


def _minimal_post(**overrides) -> Post:
    fields = {
        "id": "1",
        "url": None,
        "type": "status",
        "is_pinned": False,
        "author_name": None,
        "author_url": None,
        "author_id": None,
        "created_at": None,
        "edited_at": None,
        "text": "",
        "text_truncated": False,
        "text_resolved": False,
        "media": [],
        "links": [],
        "reaction_count": None,
        "comment_count": None,
        "share_count": None,
        "shared_post": None,
        "source": "timeline",
        "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    fields.update(overrides)
    return Post(**fields)


def test_schema_fields_match_to_dict_keys_without_raw():
    # Anchored on to_dict() output, NOT dataclasses.fields(Post) — the latter
    # returns 20 names including `raw` unconditionally, which would
    # mis-document `raw` as always-present (plan §10a).
    to_dict_keys = set(_minimal_post().to_dict().keys())
    assert len(to_dict_keys) == 20
    schema_names = {f["name"] for f in schema_fields() if f["always_present"]}
    assert schema_names == to_dict_keys


def test_schema_fields_include_raw_only_flagged_correctly():
    to_dict_keys_with_raw = set(_minimal_post(raw={"x": 1}).to_dict().keys())
    assert len(to_dict_keys_with_raw) == 21
    all_schema_names = {f["name"] for f in schema_fields()}
    assert all_schema_names == to_dict_keys_with_raw
    raw_entry = next(f for f in schema_fields() if f["name"] == "raw")
    assert raw_entry["always_present"] is False


def test_every_to_dict_key_has_a_description():
    # A new to_dict() key with no FIELD_DESCRIPTIONS entry must fail here,
    # not surface as a silent KeyError deep inside schema_fields().
    to_dict_keys = set(_minimal_post(raw={"x": 1}).to_dict().keys())
    assert to_dict_keys.issubset(FIELD_DESCRIPTIONS.keys())


def test_json_schema_uses_json_types_not_python_annotations():
    schema = json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    # created_at is `datetime | None` in Python but must render as the JSON
    # shape a consumer actually sees: string-or-null, never "datetime".
    assert schema["properties"]["created_at"]["type"] == ["string", "null"]
    assert schema["properties"]["media"]["type"] == "array"
    assert schema["properties"]["shared_post"]["type"] == ["object", "null"]
    assert "raw" not in schema["required"]
    assert "id" in schema["required"]
