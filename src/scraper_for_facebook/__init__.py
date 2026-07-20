"""Public Python API (plan §5). See README.md for the full picture."""

from __future__ import annotations

__version__ = "0.3.1"

from collections.abc import Iterator
from datetime import date
from pathlib import Path

from . import profiles
from . import retrieve as retrieve_module
from . import session as session_module
from .config import DEFAULT_MAX_SCROLLS, DEFAULT_PROFILE_NAME, DEFAULT_SCROLL_PAUSE
from .errors import (
    ChallengeError,
    InvalidIdentifierError,
    LoginRequiredError,
    ProfileUnavailableError,
    ScraperForFacebookError,
    SessionClosedError,
    SessionExpiredError,
)
from .model import LinkAttachment, Media, Post
from .retrieve import RetrieveResult
from .session import Status

__all__ = [
    "FacebookScraper",
    "Post",
    "Media",
    "LinkAttachment",
    "Status",
    "RetrieveResult",
    "ScraperForFacebookError",
    "LoginRequiredError",
    "SessionExpiredError",
    "ChallengeError",
    "ProfileUnavailableError",
    "SessionClosedError",
    "InvalidIdentifierError",
]


def _parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)  # strict YYYY-MM-DD; raises ValueError otherwise


class _HybridLogin:
    """Makes ``login`` behave differently on the class vs. an instance:

    - ``FacebookScraper.login(profile=..., profile_dir=...)`` (class access)
      CONSTRUCTS a new instance with those keywords, then logs it in — so it
      needs them.
    - ``FacebookScraper(profile=...).login()`` (instance access) takes NO
      keywords — ``profile``/``profile_dir`` are already fixed by the
      instance you're calling it on; passing them again would be ambiguous
      (log into the instance's own profile, or silently reconstruct a
      different one?), so it's a plain ``TypeError`` instead of guessing.

    Plain ``def``/``@classmethod`` can't express this one name having two
    different call shapes — the second definition would just shadow the
    first in the class namespace. This closes the gap the plan calls out
    explicitly (§5): a classmethod-only shim can't forward a caller's custom
    ``profile_dir`` into the same session it then logs into, so a library
    user with a non-default ``profile_dir`` would log into one place and
    fetch from another.
    """

    def __get__(self, obj, objtype=None):
        if obj is not None:
            return obj._login_instance

        def classmethod_shim(
            profile: str = DEFAULT_PROFILE_NAME,
            *,
            profile_dir: str | Path | None = None,
        ) -> bool:
            return objtype(profile=profile, profile_dir=profile_dir)._login_instance()

        return classmethod_shim


class FacebookScraper:
    """Scrape your own logged-in Facebook timeline. See DISCLAIMER.md first."""

    def __init__(
        self,
        profile: str = DEFAULT_PROFILE_NAME,
        *,
        headless: bool = True,
        profile_dir: str | Path | None = None,
        scroll_pause: tuple[float, float] = DEFAULT_SCROLL_PAUSE,
        max_scrolls: int = DEFAULT_MAX_SCROLLS,
    ) -> None:
        self.profile = profile
        self.headless = headless
        self.scroll_pause = scroll_pause
        self.max_scrolls = max_scrolls
        self.last_result: RetrieveResult | None = None
        self._profile_dir = profiles.resolve_profile_dir(profile, profile_dir)
        self._closed = False

    def __enter__(self) -> FacebookScraper:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._closed = True

    def _login_instance(self) -> bool:
        return session_module.run_login(self._profile_dir)

    login = _HybridLogin()

    def status(self) -> Status:
        return session_module.run_status(self._profile_dir)

    def fetch_profile(
        self,
        url: str,
        *,
        limit: int | None = None,
        since: str | date | None = None,
        until: str | date | None = None,
        raw: bool = False,
    ) -> list[Post]:
        if self._closed:
            raise SessionClosedError("FacebookScraper is closed; use it inside a `with` block")
        normalized_url = profiles.normalize_target_identifier(url)
        result = retrieve_module.fetch_profile(
            normalized_url,
            profile_dir=self._profile_dir,
            # Must travel with profile_dir, not default separately: active mode
            # keys its token cache by profile NAME while the browser session is
            # keyed by DIRECTORY. Letting the name fall back to "default" while
            # the directory points at another profile makes the two disagree —
            # the run would read (and overwrite) a different account's cached
            # cookies than the browser profile it is actually driving.
            profile_name=self.profile,
            headless=self.headless,
            limit=limit,
            since=_parse_date(since),
            until=_parse_date(until),
            scroll_pause=self.scroll_pause,
            max_scrolls=self.max_scrolls,
            raw=raw,
        )
        self.last_result = result
        return result.posts

    def iter_profile(
        self,
        url: str,
        *,
        limit: int | None = None,
        since: str | date | None = None,
        until: str | date | None = None,
        raw: bool = False,
    ) -> Iterator[Post]:
        """Generator form. Must be consumed inside the owning ``with`` block —
        advancing it (the first ``next()``, e.g. via a ``for`` loop) after the
        block exited raises :class:`SessionClosedError` rather than touching
        an already-closed session. Because this is a generator, that check
        cannot run at call time — calling ``iter_profile()`` itself never
        raises, even on an already-closed instance; only advancing it does.

        Note this fully scrolls, captures, and parses before yielding the
        first post — like ``fetch_profile``, just yielded one at a time
        afterward. Breaking out of the loop early doesn't reduce browser
        work already done.
        """
        if self._closed:
            raise SessionClosedError("iter_profile() was advanced after its `with` block exited")
        for post in self.fetch_profile(url, limit=limit, since=since, until=until, raw=raw):
            if self._closed:
                raise SessionClosedError(
                    "iter_profile() was advanced after its `with` block exited"
                )
            yield post
