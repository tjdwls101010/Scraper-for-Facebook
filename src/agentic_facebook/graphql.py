"""Active transport: read Facebook's GraphQL API over plain HTTP.

This is a new *transport*, not a new parser. The bytes it returns are the same
GraphQL JSON the browser transport captures, so ``parse.py``/``model.py`` are
untouched and both modes are guaranteed to agree (recon §1, re-proven §7.6).

The browser is still the only thing that logs in; this module only replays the
auth material that session already holds (see ``tokens.py``).
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Iterator

from scrapling.fetchers import FetcherSession

from .config import DEFAULT_MAX_PAGES, DEFAULT_REQUEST_INTERVAL, clamp_request_interval
from .errors import ActiveTransportError, SessionExpiredError
from .queries import QuerySpec, build_variables
from .tokens import SessionTokens

GRAPHQL_URL = "https://www.facebook.com/api/graphql/"

#: Facebook's "your session isn't valid" error code, plus the login-form query
#: it serves in-place at HTTP 200. Detecting the RESPONSE shape rather than the
#: URL is the fix for the false-positive in recon §5.1 — there is no redirect
#: to notice, so a URL check sees a perfectly healthy-looking 200.
_LOGGED_OUT_MARKERS = (
    b'"error":1357001',
    b"CAAFetaAYMHPasswordEntryQuery",
    b"caa_login_form_data",
)


def looks_logged_out(raw: bytes) -> bool:
    return any(marker in raw for marker in _LOGGED_OUT_MARKERS)


def iter_chunks(raw: bytes) -> Iterator[dict]:
    """Each NDJSON line of a (possibly ``@defer``/``@stream``ed) response."""
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict):
            yield chunk


def find_page_info(raw: bytes, connection_key: str) -> dict | None:
    """The paginating connection's ``page_info``, in either delivery shape.

    Live responses deliver it two different ways (recon §7.5):

    - **inline** — ``...<connection_key>: {edges: [...], page_info: {...}}``
    - **deferred** — a trailing chunk whose ``path`` ends in ``connection_key``
      and whose ``data`` is just ``{"page_info": {...}}``. Feed connections
      are ``@stream``ed, so this is the common case: the inline connection
      dict arrives carrying ``edges`` and **no** ``page_info`` at all.

    Keying on ``connection_key`` rather than "the first page_info anywhere"
    matters — responses carry unrelated nested connections (reactors, comment
    previews, search sub-results) whose cursors would paginate the wrong thing.
    """

    def walk(obj) -> dict | None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if (
                    key == connection_key
                    and isinstance(value, dict)
                    and isinstance(value.get("page_info"), dict)
                ):
                    return value["page_info"]
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = walk(item)
                if found is not None:
                    return found
        return None

    for chunk in iter_chunks(raw):
        path = chunk.get("path")
        data = chunk.get("data")
        if isinstance(path, list) and path and path[-1] == connection_key:
            if isinstance(data, dict) and isinstance(data.get("page_info"), dict):
                return data["page_info"]
        found = walk(data)
        if found is not None:
            return found
    return None


class ActiveFetcher:
    """Replays registry queries over HTTP, under a non-bypassable rate floor."""

    def __init__(
        self,
        tokens: SessionTokens,
        *,
        request_interval: tuple[float, float] = DEFAULT_REQUEST_INTERVAL,
    ) -> None:
        self.tokens = tokens
        # Clamped once, here, so no call path can reach post() with a faster
        # interval than the floor — including direct library use (plan §6).
        self._interval = clamp_request_interval(request_interval)
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        """Sleep out the remainder of a jittered inter-request delay."""
        target = random.uniform(*self._interval)
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < target:
                time.sleep(target - elapsed)
        self._last_request_at = time.monotonic()

    def _body(self, spec: QuerySpec, variables: dict) -> dict:
        tokens = self.tokens
        return {
            "av": tokens.user_id,
            "__user": tokens.user_id,
            "__a": "1",
            "__comet_req": "15",
            "fb_dtsg": tokens.fb_dtsg,
            "jazoest": tokens.jazoest,
            "lsd": tokens.lsd,
            "__spin_r": tokens.rev,
            "__spin_t": tokens.spin_t,
            "__spin_b": tokens.spin_b,
            "__rev": tokens.rev,
            "server_timestamps": "true",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": spec.name,
            "variables": json.dumps(variables, separators=(",", ":")),
            "doc_id": spec.doc_id,
        }

    def post(self, spec: QuerySpec, variables: dict, *, referer: str | None = None) -> bytes:
        """One rate-limited GraphQL POST. Returns the raw response bytes."""
        self._throttle()
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "x-fb-friendly-name": spec.name,
            "x-fb-lsd": self.tokens.lsd,
            "origin": "https://www.facebook.com",
            "referer": referer or spec.referer,
        }
        try:
            with FetcherSession(impersonate="chrome") as http:
                response = http.post(
                    GRAPHQL_URL,
                    data=self._body(spec, variables),
                    cookies=self.tokens.cookies,
                    headers=headers,
                )
        except Exception as exc:  # noqa: BLE001 - any transport failure is a fallback signal
            raise ActiveTransportError(f"active request failed: {type(exc).__name__}") from exc

        raw = (
            response.body
            if isinstance(response.body, bytes | bytearray)
            else str(response.body).encode()
        )
        raw = bytes(raw)
        if looks_logged_out(raw):
            raise SessionExpiredError(
                "Facebook rejected the session token. Log in again: agentic-facebook login"
            )
        if response.status != 200:
            raise ActiveTransportError(f"active request returned HTTP {response.status}")
        return raw

    def get(self, url: str) -> bytes:
        """One rate-limited authenticated GET, for the few things GraphQL can't answer.

        Namely: resolving a vanity URL to a numeric id, and reading a permalink
        page whose post body is server-rendered rather than fetched over
        GraphQL (recon §4). Goes through the same throttle as :meth:`post` —
        an unthrottled side channel would be a hole in the floor.
        """
        self._throttle()
        try:
            with FetcherSession(impersonate="chrome") as http:
                response = http.get(
                    url,
                    cookies=self.tokens.cookies,
                    headers={"referer": "https://www.facebook.com/"},
                )
        except Exception as exc:  # noqa: BLE001 - any transport failure is a fallback signal
            raise ActiveTransportError(f"active GET failed: {type(exc).__name__}") from exc

        raw = bytes(
            response.body
            if isinstance(response.body, bytes | bytearray)
            else str(response.body).encode()
        )
        if looks_logged_out(raw):
            raise SessionExpiredError(
                "Facebook served a login page. Log in again: agentic-facebook login"
            )
        if response.status != 200:
            raise ActiveTransportError(f"active GET returned HTTP {response.status}")
        return raw

    def paginate(
        self,
        spec: QuerySpec,
        variables: dict | None = None,
        *,
        max_pages: int = DEFAULT_MAX_PAGES,
        referer: str | None = None,
    ) -> Iterator[bytes]:
        """Walk the cursor loop, yielding each page's raw bytes.

        Stops at ``has_next_page == False``, a missing cursor, or ``max_pages``
        — whichever comes first. Every request goes through :meth:`post`, so
        the rate floor applies to pagination by construction.
        """
        if spec.connection_key is None or spec.cursor_var is None:
            raise ValueError(f"{spec.name} does not paginate")

        current = build_variables(spec, variables)
        for _ in range(max_pages):
            raw = self.post(spec, current, referer=referer)
            yield raw

            page_info = find_page_info(raw, spec.connection_key)
            if not page_info or not page_info.get("has_next_page"):
                return
            cursor = page_info.get("end_cursor")
            if not cursor:
                return
            current = dict(current)
            current[spec.cursor_var] = cursor
