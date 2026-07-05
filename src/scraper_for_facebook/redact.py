"""Single scrub path for anything captured-body-derived that reaches a screen or log.

Every diagnostic surface — ``-v``/``--verbose``, error/drift dumps, ``--raw`` output,
and anything else printed to stdout/stderr/logs — must route through this module.
Captured Facebook responses carry third-party PII and viewer-scoped signed
``scontent``/``fbcdn`` URLs (bearer-like: whoever holds one can fetch that media as
you, until it expires). Redacting only some of these paths and not others is how a
sensitive value ends up in a bug report or terminal scrollback (see plan §21).

This does NOT apply to the actual ``--output`` file, which is the full, unredacted
capture by design — that's the point of the tool (see DISCLAIMER.md §5).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SENSITIVE_KEYS = frozenset(
    {
        "fb_dtsg",
        "lsd",
        "jazoest",
        "datr",
        "sb",
        "c_user",
        "xs",
        "token",
        "access_token",
        "cookie",
        "cookies",
        "authorization",
    }
)

_TEXT_KEYS = frozenset({"text", "message", "name", "author_name", "title", "description"})

_CDN_HOST_RE = re.compile(
    r"(?:scontent[.\-][a-z0-9.\-]*\.fbcdn\.net|fbcdn\.net|fbstatic-a\.akamaihd\.net)$",
    re.IGNORECASE,
)

_FB_DTSG_INLINE_RE = re.compile(r'"(fb_dtsg|lsd|jazoest)"\s*:\s*"[^"]*"')

_TEXT_TRUNCATE_LEN = 40


def is_signed_media_url(url: str) -> bool:
    """True for scontent/fbcdn-style URLs — signed, expiring, viewer-scoped (§17 G-media-expiry)."""
    try:
        host = urlsplit(url).netloc.split("@")[-1].split(":")[0]
    except ValueError:
        return False
    return bool(_CDN_HOST_RE.search(host))


def redact_url(url: str) -> str:
    """Strip the query string (the signing/auth material) off a signed CDN URL."""
    if not is_signed_media_url(url):
        return url
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def redact_text(value: str, max_len: int = _TEXT_TRUNCATE_LEN) -> str:
    """Truncate free text (names, message bodies) so diagnostics don't leak full content."""
    if len(value) <= max_len:
        return value
    return f"{value[:max_len]}...[redacted {len(value) - max_len} more chars]"


def redact_raw_text(text: str) -> str:
    """Scrub an unstructured blob (a raw captured body dumped into an error message)."""
    text = _FB_DTSG_INLINE_RE.sub(lambda m: f'"{m.group(1)}":"[REDACTED]"', text)

    def _scrub_url(match: re.Match) -> str:
        return redact_url(match.group(0))

    text = re.sub(r"https?://[^\s\"'<>]+", _scrub_url, text)
    return text


def redact(value):
    """Recursively scrub a value of the shapes this package produces (dict/list/str/Post-like).

    Dict values are scrubbed by key name (drop sensitive keys, truncate text keys,
    strip signing query strings off URL-shaped values); everything else recurses
    structurally. Unknown scalar types pass through unchanged.
    """
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            key_lower = key.lower() if isinstance(key, str) else key
            if key_lower in _SENSITIVE_KEYS:
                out[key] = "[REDACTED]"
            elif isinstance(val, str) and key_lower in _TEXT_KEYS:
                out[key] = redact_text(val)
            elif isinstance(val, str) and val.startswith(("http://", "https://")):
                out[key] = redact_url(val)
            else:
                out[key] = redact(val)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return redact_url(value)
        return value
    return value
