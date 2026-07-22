"""Session tokens for active (HTTP GraphQL) mode.

Active mode is not credential injection: it reads the auth material *your own
logged-in browser session already holds* and sends it the way that browser
sends it. The browser is still the only thing that ever logs in — it just stops
being in the hot path once these are extracted.

Everything here is a live session credential. The cache file is written 0600
and is exactly as sensitive as the login profile directory (DISCLAIMER §6).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import tokens_dir
from .errors import SessionExpiredError

#: ``fb_dtsg`` rotates within a live session, so a cached set goes stale long
#: before the underlying login does. Cheap to re-extract; expensive to debug
#: when a stale one silently 400s.
TOKEN_MAX_AGE_SECONDS = 1800

#: 0600 — see module docstring.
_TOKEN_FILE_MODE = 0o600

#: Extraction patterns, confirmed against live page HTML (recon §1).
_PATTERNS = {
    "fb_dtsg": r'"DTSGInitialData",\[\],\{"token":"([^"]+)"',
    "lsd": r'"LSD",\[\],\{"token":"([^"]+)"',
    "user_id": r'"USER_ID":"(\d+)"',
    "rev": r'"__spin_r":(\d+)',
    "spin_t": r'"__spin_t":(\d+)',
    "spin_b": r'"__spin_b":"([^"]+)"',
}


@dataclass
class SessionTokens:
    fb_dtsg: str
    lsd: str
    user_id: str
    rev: str
    spin_t: str
    spin_b: str
    cookies: dict[str, str]
    extracted_at: datetime

    @property
    def jazoest(self) -> str:
        """Computed, never scraped — it is a checksum of ``fb_dtsg`` (recon §1)."""
        return "2" + str(sum(ord(c) for c in self.fb_dtsg))

    def is_stale(self, max_age_seconds: float = TOKEN_MAX_AGE_SECONDS) -> bool:
        age = (datetime.now(UTC) - self.extracted_at).total_seconds()
        return age >= max_age_seconds

    def to_dict(self) -> dict:
        return {
            "fb_dtsg": self.fb_dtsg,
            "lsd": self.lsd,
            "user_id": self.user_id,
            "rev": self.rev,
            "spin_t": self.spin_t,
            "spin_b": self.spin_b,
            "cookies": self.cookies,
            "extracted_at": self.extracted_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionTokens:
        return cls(
            fb_dtsg=data["fb_dtsg"],
            lsd=data["lsd"],
            user_id=data["user_id"],
            rev=data["rev"],
            spin_t=data["spin_t"],
            spin_b=data["spin_b"],
            cookies=data["cookies"],
            extracted_at=datetime.fromisoformat(data["extracted_at"]),
        )


def extract_from_page(page) -> SessionTokens:
    """Scrape auth material out of an already-logged-in Playwright page.

    Raises :class:`SessionExpiredError` when the page is a logged-out one —
    detected by the *absence of what a logged-in page always has* (``fb_dtsg``
    plus a ``c_user`` cookie) rather than by URL sniffing, because Facebook
    serves the login form in-place at ``/`` with HTTP 200 (recon §5.1).
    """
    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in page.context.cookies()
        if "facebook" in cookie.get("domain", "")
    }
    return _extract_from_html(page.content(), cookies)


def cache_path(profile_name: str) -> Path:
    return tokens_dir() / f"{profile_name}.json"


def load_cached(profile_name: str) -> SessionTokens | None:
    """The cached tokens for this profile, or ``None`` if absent/unreadable/corrupt."""
    path = cache_path(profile_name)
    if not path.exists():
        return None
    try:
        return SessionTokens.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def save_cached(profile_name: str, tokens: SessionTokens) -> Path:
    """Persist tokens 0600, creating the directory with a restrictive umask."""
    path = cache_path(profile_name)
    old_umask = os.umask(0o077)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(old_umask)
    path.write_text(json.dumps(tokens.to_dict()), encoding="utf-8")
    os.chmod(path, _TOKEN_FILE_MODE)
    return path


def _extract_from_html(html: str, cookies: dict[str, str]) -> SessionTokens:
    found = {}
    for field, pattern in _PATTERNS.items():
        match = re.search(pattern, html)
        found[field] = match.group(1) if match else ""

    if not found["fb_dtsg"] or "c_user" not in cookies:
        raise SessionExpiredError(
            "These cookies are not a logged-in Facebook session. "
            "Log in again: agentic-facebook login"
        )
    return SessionTokens(
        fb_dtsg=found["fb_dtsg"],
        lsd=found["lsd"],
        user_id=found["user_id"],
        rev=found["rev"],
        spin_t=found["spin_t"],
        spin_b=found["spin_b"] or "trunk",
        cookies=cookies,
        extracted_at=datetime.now(UTC),
    )


def refresh_over_http(cookies: dict[str, str]) -> SessionTokens:
    """Re-derive tokens from existing cookies, with no browser at all.

    ``fb_dtsg`` rotates far faster than the session cookies behind it, so a
    stale token set can almost always be renewed by re-reading one page over
    HTTP — far cheaper than launching Chromium, and the only refresh path
    available to a ``--from-chrome`` session, which has no browser profile of
    its own to reopen.
    """
    from scrapling.fetchers import FetcherSession

    with FetcherSession(impersonate="chrome") as http:
        response = http.get("https://www.facebook.com/me", cookies=cookies)
    body = response.body
    html = body.decode("utf-8", "replace") if isinstance(body, bytes | bytearray) else str(body)
    return _extract_from_html(html, cookies)


def from_chrome(chrome_profile: str = "Default") -> SessionTokens:
    """Import the Facebook session from a local Chrome profile (opt-in, plan §3a)."""
    from .chrome import load_facebook_cookies

    return refresh_over_http(load_facebook_cookies(chrome_profile))


def refresh_from_browser(profile_dir: Path, *, headless: bool = True) -> SessionTokens:
    """Open the persisted login profile just long enough to re-extract tokens."""
    from .session import build_session  # local: session.py imports browser machinery

    holder: dict[str, SessionTokens] = {}

    def _grab(page) -> None:
        holder["tokens"] = extract_from_page(page)

    with build_session(profile_dir, headless=headless) as session:
        session.fetch("https://www.facebook.com/me", page_action=_grab, timeout=60000)

    if "tokens" not in holder:
        # extract_from_page raised inside page_action, where scrapling swallows
        # exceptions (see scroll.py's docstring) — surface it as the auth
        # failure it almost certainly is rather than a bare KeyError.
        raise SessionExpiredError(
            "Could not extract session tokens from the browser. "
            "Log in again: agentic-facebook login"
        )
    return holder["tokens"]


def get_tokens(
    profile_dir: Path,
    profile_name: str,
    *,
    headless: bool = True,
    force_refresh: bool = False,
) -> SessionTokens:
    """Cached tokens if fresh; otherwise refreshed over HTTP, then via the browser.

    The HTTP refresh is tried first because it is far cheaper than a browser
    launch and usually sufficient (only ``fb_dtsg`` has gone stale, not the
    session). The browser is the fallback for when the cookies themselves are
    dead — and the only option when there is no cache to refresh from.
    """
    cached = load_cached(profile_name)
    if not force_refresh and cached is not None and not cached.is_stale():
        return cached

    if cached is not None:
        try:
            tokens = refresh_over_http(cached.cookies)
            save_cached(profile_name, tokens)
            return tokens
        except Exception:  # noqa: BLE001 - any failure just means "use the browser"
            pass

    tokens = refresh_from_browser(profile_dir, headless=headless)
    save_cached(profile_name, tokens)
    return tokens
