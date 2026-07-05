import json

from scraper_for_facebook import parse


def test_body_is_decoded_from_bytes_not_str(load_fixture):
    body = load_fixture("basic_status_post.ndjson")
    assert isinstance(body, bytes)
    objects = list(parse.iter_json_objects([body]))
    assert len(objects) == 1
    assert objects[0]["data"]["node"]["feedback"]["id"] == "fb_001"


def test_ndjson_split_yields_one_object_per_line(load_fixture):
    body = load_fixture("split_defer_merge.ndjson")
    objects = list(parse.iter_json_objects([body]))
    assert len(objects) == 2


def test_unparseable_line_is_skipped_not_fatal():
    body = b'{"data": {"node": {"feedback": {"id": "ok"}}}}\nnot json at all\n'
    objects = list(parse.iter_json_objects([body]))
    assert len(objects) == 1
    assert objects[0]["data"]["node"]["feedback"]["id"] == "ok"


def test_deep_merge_combines_split_defer_fields(load_fixture):
    body = load_fixture("split_defer_merge.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_002"]
    # From the first line:
    assert parse.find_message_text(story) == (
        "Post whose fields are split across two synthetic defer-style chunks."
    )
    # From the second line:
    assert story["feedback"]["reaction_count"]["count"] == 42
    media = parse.find_media(story)
    assert any(m["kind"] == "image" for m in media)


def test_deep_merge_unions_id_keyed_lists():
    a = {"items": [{"id": "1", "x": 1}]}
    b = {"items": [{"id": "1", "y": 2}, {"id": "2", "z": 3}]}
    merged = parse.deep_merge(a, b)
    by_id = {item["id"]: item for item in merged["items"]}
    assert by_id["1"] == {"id": "1", "x": 1, "y": 2}
    assert by_id["2"] == {"id": "2", "z": 3}


def test_deep_merge_unions_non_id_keyed_lists_by_content():
    # "attachments" carries no id key. Picking one list wholesale (the old
    # "longer wins" rule) drops a genuinely new item whenever the earlier
    # chunk's list isn't shorter.
    a = {"attachments": [{"media": {"image": {"uri": "https://example.test/a.jpg"}}}]}
    b = {"attachments": [{"media": {"image": {"uri": "https://example.test/b.jpg"}}}]}
    merged = parse.deep_merge(a, b)
    uris = {item["media"]["image"]["uri"] for item in merged["attachments"]}
    assert uris == {"https://example.test/a.jpg", "https://example.test/b.jpg"}


def test_shared_post_is_not_double_counted_as_top_level(load_fixture):
    body = load_fixture("shared_post.ndjson")
    parsed = parse.parse_story_nodes([body])
    assert set(parsed.stories.keys()) == {"fb_003_wrapper", "fb_003_shared_original"}
    assert parsed.top_level_ids() == ["fb_003_wrapper"]
    assert "fb_003_shared_original" not in parsed.top_level_seen


def test_shared_post_also_appearing_standalone_is_not_dropped():
    # A friend reshares a post that ALSO shows up in your feed independently
    # (e.g. you follow the original author too) — both must be top-level.
    standalone = {"feedback": {"id": "B"}, "creation_time": 1}
    wrapper = {
        "feedback": {"id": "A"},
        "creation_time": 2,
        "attached_story": {"feedback": {"id": "B"}, "creation_time": 1},
    }
    body = ("\n".join(json.dumps(o) for o in [standalone, wrapper])).encode("utf-8")
    parsed = parse.parse_story_nodes([body])
    assert set(parsed.top_level_ids()) == {"A", "B"}

    # Order-independent: same result if the share appears before the standalone post.
    body_reversed = ("\n".join(json.dumps(o) for o in [wrapper, standalone])).encode("utf-8")
    parsed_reversed = parse.parse_story_nodes([body_reversed])
    assert set(parsed_reversed.top_level_ids()) == {"A", "B"}


def test_creation_time_uses_exact_story_root_key_not_a_decoy_int(load_fixture):
    body = load_fixture("pinned_decoy_and_missing_date.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_004_pinned"]
    # The fixture also buries a decoy creation_time=999999999 inside a nested
    # attachment — the real value at the story root must win.
    assert parse.find_creation_time(story) == 1750000400


def test_creation_time_missing_returns_none_not_a_crash(load_fixture):
    body = load_fixture("pinned_decoy_and_missing_date.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_004_no_date"]
    assert parse.find_creation_time(story) is None


def test_find_media_labels_video_thumbnail_as_image_and_stream_as_video(load_fixture):
    body = load_fixture("media_and_links.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_006"]
    media = parse.find_media(story)
    kinds = {m["kind"] for m in media}
    assert kinds == {"image", "video"}


def test_find_links_extracts_external_link_attachment(load_fixture):
    body = load_fixture("media_and_links.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_006"]
    links = parse.find_links(story)
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/synthetic-article"
    assert links[0]["title"] == "Synthetic Article Title"


def test_find_permalink_and_actors(load_fixture):
    body = load_fixture("basic_status_post.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_001"]
    assert parse.find_permalink(story) == "https://www.facebook.com/100000000000001/posts/1"
    actors = parse.find_actors(story)
    assert actors[0]["name"] == "Synthetic Alice"


def test_multiple_bodies_are_all_parsed(load_fixture):
    bodies = [load_fixture("basic_status_post.ndjson"), load_fixture("truncated_post.ndjson")]
    parsed = parse.parse_story_nodes(bodies)
    assert set(parsed.top_level_ids()) == {"fb_001", "fb_005"}


def test_json_roundtrip_sanity_for_all_fixtures(load_fixture):
    for name in [
        "basic_status_post.ndjson",
        "split_defer_merge.ndjson",
        "shared_post.ndjson",
        "pinned_decoy_and_missing_date.ndjson",
        "truncated_post.ndjson",
        "media_and_links.ndjson",
        "comment_preview_and_universal_marker.ndjson",
    ]:
        body = load_fixture(name)
        for line in body.decode("utf-8").splitlines():
            json.loads(line)  # every fixture line must be valid JSON on its own


def test_comment_preview_is_not_a_top_level_post(load_fixture):
    # Confirmed via live capture: a post's inline "top comment" preview is a
    # separate feedback-shaped object nested under interesting_top_level_
    # comments, reached WITHOUT ever passing through attached_story — it must
    # not be misidentified as an independent top-level post or a share.
    body = load_fixture("comment_preview_and_universal_marker.ndjson")
    parsed = parse.parse_story_nodes([body])
    assert parsed.top_level_ids() == ["fb_007"]
    assert "fb_007_9988776655" not in parsed.stories


def test_permalink_url_root_key_is_preferred(load_fixture):
    body = load_fixture("comment_preview_and_universal_marker.ndjson")
    parsed = parse.parse_story_nodes([body])
    story = parsed.stories["fb_007"]
    assert parse.find_permalink(story) == "https://www.facebook.com/synthetic.profile/posts/8"
