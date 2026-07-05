"""Detect and resolve truncated post bodies (plan §8, §13).

``message.text`` is usually the full body — Facebook expands "See more"
client-side with no extra network call, which is evidence the text already
shipped in full. But that is a claim to disprove, not assume (link/mention
-heavy posts truncate server-side more often), so ``text_truncated`` is always
populated from a payload marker regardless of whether a full-body field also
exists.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .parse import SHARE_EXCLUDE, iter_story_dicts, parse_story_nodes

_TRUNCATION_KEY_MARKERS = ("truncat", "preferred_body", "see_more")


def has_truncation_marker(story: dict) -> bool:
    """True if any key name under the story's own content (not a shared post) looks truncation-related."""  # noqa: E501
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        for key, value in node.items():
            key_lower = key.lower()
            if value and any(marker in key_lower for marker in _TRUNCATION_KEY_MARKERS):
                return True
    return False


def resolve_truncated_text(
    permalink: str, fetch_permalink_bodies: Callable[[str], Iterable[bytes]]
) -> str | None:
    """Recover the full body by revisiting the post's permalink.

    ``fetch_permalink_bodies`` is injected (rather than importing session.py
    directly) so this module stays a pure parsing concern; the caller (which
    already owns a live browser session) supplies the actual navigation.
    Returns ``None`` if the permalink capture didn't yield a usable story —
    callers should leave ``text_resolved`` false in that case, not raise.
    """
    bodies = list(fetch_permalink_bodies(permalink))
    if not bodies:
        return None
    parsed = parse_story_nodes(bodies)
    for story in parsed.stories.values():
        for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
            message = node.get("message")
            if isinstance(message, dict):
                text = message.get("text")
                if isinstance(text, str) and text:
                    return text
    return None
