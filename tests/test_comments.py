"""Comment parsing/shaping. Fixtures are synthetic, shaped like the real nodes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from scraper_for_facebook import comments as cm
from scraper_for_facebook.retrieve import _order_comments

CAPTURED_AT = datetime(2026, 7, 20, tzinfo=UTC)
POST_ID = "ZmVlZGJhY2s6MQ=="


def _node(
    node_id: str,
    *,
    depth: int = 0,
    text: str = "hello",
    parent: str | None = None,
    replies: int = 0,
    reactors_count: int | None = None,
    reactors_reduced: str | None = None,
    action_link_count: int | None = None,
    expansion: str | None = None,
) -> dict:
    reactors: dict = {}
    if reactors_count is not None:
        reactors["count"] = reactors_count
    if reactors_reduced is not None:
        reactors["count_reduced"] = reactors_reduced

    node: dict = {
        "id": node_id,
        "depth": depth,
        "created_time": 1784342488,
        "author": {"id": "42", "name": "A Commenter", "url": "https://www.facebook.com/someone"},
        "body": {"text": text},
        "feedback": {
            "id": f"feedback:{node_id}",
            "reaction_count": None,  # always null on a comment — the real trap
            "reactors": reactors,
            "replies_fields": {"count": replies, "total_count": replies},
        },
    }
    if parent is not None:
        node["comment_direct_parent"] = {"id": parent}
    if expansion is not None:
        node["feedback"]["expansion_info"] = {"expansion_token": expansion}
    if action_link_count is not None:
        node["comment_action_links"] = [
            {"comment": {"feedback": {"reactors": {"count": action_link_count}}}}
        ]
    return node


def _body(*nodes: dict) -> bytes:
    return json.dumps(
        {"data": {"node": {"comments": {"edges": [{"node": n} for n in nodes]}}}}
    ).encode()


def test_build_comment_maps_every_field():
    comment = cm.build_comment(
        _node("c1", replies=3, reactors_count=7), post_id=POST_ID, captured_at=CAPTURED_AT
    )

    assert comment.id == "c1"
    assert comment.post_id == POST_ID
    assert comment.author_name == "A Commenter"
    assert comment.author_url == "https://www.facebook.com/someone"
    assert comment.author_id == "42"
    assert comment.text == "hello"
    assert comment.created_at == datetime.fromtimestamp(1784342488, tz=UTC)
    assert comment.depth == 0
    assert comment.reply_count == 3
    assert comment.reaction_count == 7


def test_depth_distinguishes_a_reply_from_a_top_level_comment():
    """depth maps exactly onto the --replies design (recon §3)."""
    top = cm.build_comment(_node("c1"), post_id=POST_ID, captured_at=CAPTURED_AT)
    reply = cm.build_comment(
        _node("c2", depth=1, parent="c1"), post_id=POST_ID, captured_at=CAPTURED_AT
    )

    assert (top.depth, top.parent_id) == (0, None)
    assert (reply.depth, reply.parent_id) == (1, "c1")


def test_reaction_count_prefers_the_exact_int_over_the_display_string():
    """A comment's own feedback carries only a display string; the int is nested."""
    node = _node("c1", reactors_reduced="1.2K", action_link_count=1234)
    assert cm.build_comment(node, post_id=POST_ID, captured_at=CAPTURED_AT).reaction_count == 1234


def test_reaction_count_parses_a_plainly_numeric_display_string():
    node = _node("c1", reactors_reduced="6")
    assert cm.build_comment(node, post_id=POST_ID, captured_at=CAPTURED_AT).reaction_count == 6


def test_reaction_count_refuses_to_guess_at_an_abbreviated_string():
    """ "1.2K" must not become 1.2 or 1200 — inventing precision is worse than null."""
    node = _node("c1", reactors_reduced="1.2K")
    assert cm.build_comment(node, post_id=POST_ID, captured_at=CAPTURED_AT).reaction_count is None


def test_build_comments_dedupes_by_id_across_bodies():
    """The same comment arrives again on the next page/expansion; it is one comment."""
    bodies = [_body(_node("c1"), _node("c2")), _body(_node("c2"), _node("c3"))]

    result = cm.build_comments(bodies, post_id=POST_ID, captured_at=CAPTURED_AT)

    assert [c.id for c in result] == ["c1", "c2", "c3"]


def test_iter_comment_nodes_ignores_post_shaped_nodes():
    """A post is feedback-shaped too — only the depth+author+body triple is a comment."""
    post_like = {"feedback": {"id": "feedback:post"}, "creation_time": 1, "message": {"text": "x"}}
    body = json.dumps({"data": {"node": post_like, "extra": _node("c1")}}).encode()

    assert [n["id"] for n in cm.iter_comment_nodes([body])] == ["c1"]


def test_expansion_token_read_from_feedback():
    assert cm.expansion_token(_node("c1", expansion="TOK")) == "TOK"
    assert cm.expansion_token(_node("c1")) is None


# --- ordering / limit ---------------------------------------------------------


def _c(id_, depth=0, parent=None):
    return cm.build_comment(
        _node(id_, depth=depth, parent=parent), post_id=POST_ID, captured_at=CAPTURED_AT
    )


def test_order_comments_limits_top_level_only_and_nests_replies():
    """--limit counts top-level comments; a reply-heavy comment can't eat the budget."""
    parsed = [_c("t1"), _c("t2"), _c("t3"), _c("r1", 1, "t1"), _c("r2", 1, "t1")]

    ordered = _order_comments(parsed, limit=2, replies=True)

    assert [c.id for c in ordered] == ["t1", "r1", "r2", "t2"]


def test_order_comments_drops_replies_when_not_requested():
    parsed = [_c("t1"), _c("r1", 1, "t1")]

    assert [c.id for c in _order_comments(parsed, limit=None, replies=False)] == ["t1"]


def test_order_comments_excludes_replies_whose_parent_fell_outside_the_limit():
    parsed = [_c("t1"), _c("t2"), _c("r2", 1, "t2")]

    ordered = _order_comments(parsed, limit=1, replies=True)

    assert [c.id for c in ordered] == ["t1"]


def test_order_comments_keeps_replies_with_an_unreadable_parent():
    """Failing to read parent_id must not silently delete real retrieved data."""
    orphan = _c("r1", 1, None)
    ordered = _order_comments([_c("t1"), orphan], limit=None, replies=True)

    assert [c.id for c in ordered] == ["t1", "r1"]


def test_comment_schema_matches_to_dict_keys():
    sample = _c("c1").to_dict()
    assert {f["name"] for f in cm.schema_fields()} == set(sample)
    assert all(f["always_present"] for f in cm.schema_fields())
    assert cm.json_schema()["title"] == "Comment"
