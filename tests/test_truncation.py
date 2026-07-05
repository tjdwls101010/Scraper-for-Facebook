from scraper_for_facebook import parse, truncation


def test_has_truncation_marker_true_when_marker_key_present(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("truncated_post.ndjson")])
    story = parsed.stories["fb_005"]
    assert truncation.has_truncation_marker(story) is True


def test_has_truncation_marker_false_without_marker(load_fixture):
    parsed = parse.parse_story_nodes([load_fixture("basic_status_post.ndjson")])
    story = parsed.stories["fb_001"]
    assert truncation.has_truncation_marker(story) is False


def test_has_truncation_marker_ignores_shared_posts_own_markers():
    # A truncation marker living only inside attached_story must not make the
    # WRAPPER look truncated — has_truncation_marker(wrapper) should reflect
    # only the wrapper's own content.
    story = {
        "feedback": {"id": "wrapper"},
        "attached_story": {
            "feedback": {"id": "inner"},
            "is_truncated_body": True,
        },
    }
    assert truncation.has_truncation_marker(story) is False


def test_resolve_truncated_text_uses_injected_fetcher(load_fixture):
    permalink_body = load_fixture("basic_status_post.ndjson")

    def fake_fetcher(url: str):
        assert url == "https://www.facebook.com/some/permalink"
        return [permalink_body]

    text = truncation.resolve_truncated_text(
        "https://www.facebook.com/some/permalink", fake_fetcher
    )
    assert text == "Hello world, this is a simple synthetic status post."


def test_resolve_truncated_text_returns_none_when_fetcher_yields_nothing():
    text = truncation.resolve_truncated_text("https://www.facebook.com/x", lambda url: [])
    assert text is None


def test_resolve_truncated_text_never_returns_a_nested_shared_posts_text():
    # The permalink's own top-level story has no message of its own (a bare
    # reshare with no added caption) — the nested shared post's text must
    # NOT be attributed to it.
    body = (
        b'{"feedback": {"id": "wrapper"}, "attached_story": '
        b'{"feedback": {"id": "shared"}, "message": {"text": "the shared posts own text"}}}'
    )

    text = truncation.resolve_truncated_text("https://www.facebook.com/x", lambda url: [body])
    assert text is None
