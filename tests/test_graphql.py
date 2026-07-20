"""Active-transport unit tests. All fixtures here are synthetic by construction —
no captured response ever becomes a committed fixture (it would carry PII)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scraper_for_facebook import graphql, queries
from scraper_for_facebook.config import MIN_REQUEST_INTERVAL_SECONDS
from scraper_for_facebook.errors import ActiveTransportError, SessionExpiredError
from scraper_for_facebook.tokens import SessionTokens


def _tokens() -> SessionTokens:
    return SessionTokens(
        fb_dtsg="AB",  # jazoest = "2" + str(65 + 66)
        lsd="lsd-token",
        user_id="12345",
        rev="1000",
        spin_t="1700000000",
        spin_b="trunk",
        cookies={"c_user": "12345", "xs": "secret"},
        extracted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _page(edges: list[dict], *, connection: str, cursor: str | None, has_next: bool) -> bytes:
    """A response in the INLINE page_info delivery shape."""
    return json.dumps(
        {
            "data": {
                "node": {
                    connection: {
                        "edges": edges,
                        "page_info": {"end_cursor": cursor, "has_next_page": has_next},
                    }
                }
            }
        }
    ).encode()


def _deferred_page(
    edges: list[dict], *, connection: str, cursor: str | None, has_next: bool
) -> bytes:
    """A response in the DEFERRED shape: edges inline, page_info in a later chunk.

    This is the shape feed queries actually return (recon §7.5) — the inline
    connection carries edges and no page_info at all.
    """
    first = json.dumps({"data": {"node": {connection: {"edges": edges}}}})
    trailer = json.dumps(
        {
            "label": f"Feed$defer${connection}$page_info",
            "path": ["node", connection],
            "data": {"page_info": {"end_cursor": cursor, "has_next_page": has_next}},
        }
    )
    return (first + "\n" + trailer).encode()


# --- the guardrail (plan §6) --------------------------------------------------


@pytest.mark.parametrize("requested", [(0.0, 0.0), (-5.0, -1.0), (0.001, 0.002)])
def test_active_request_floor_cannot_be_bypassed(requested):
    """The whole point of the floor: no caller can set it to zero.

    Active mode fires plain HTTP POSTs, so this is the only thing standing
    between "personal tool" and "mass scraper" once the browser leaves the hot
    path — MIN_SCROLL_PAUSE_SECONDS constrains nothing here.
    """
    fetcher = graphql.ActiveFetcher(_tokens(), request_interval=requested)
    assert fetcher._interval[0] >= MIN_REQUEST_INTERVAL_SECONDS
    assert fetcher._interval[1] >= fetcher._interval[0]


def test_active_request_floor_applies_to_get_too():
    """A GET side channel that skipped the throttle would be a hole in the floor."""
    fetcher = graphql.ActiveFetcher(_tokens(), request_interval=(0.0, 0.0))
    assert fetcher._interval[0] >= MIN_REQUEST_INTERVAL_SECONDS


# --- request body -------------------------------------------------------------


def test_body_computes_jazoest_and_carries_doc_id():
    fetcher = graphql.ActiveFetcher(_tokens())
    spec = queries.QUERIES["timeline"]
    body = fetcher._body(spec, {"id": "1"})

    assert body["jazoest"] == "2131"  # "2" + str(ord('A') + ord('B'))
    assert body["doc_id"] == spec.doc_id
    assert body["fb_api_req_friendly_name"] == spec.name
    assert body["fb_api_caller_class"] == "RelayModern"
    assert json.loads(body["variables"]) == {"id": "1"}


def test_build_variables_merges_defaults_flags_and_overrides():
    spec = queries.QUERIES["timeline"]
    variables = queries.build_variables(spec, {"id": "9", "count": 99})

    assert variables["id"] == "9"
    assert variables["count"] == 99  # override wins over the default
    assert variables["feedLocation"] == "TIMELINE"  # spec default survives
    # The relay flags are required, not optional — omitting them degrades the
    # response into missing_required_variable_value warnings (recon §7.4).
    assert len(queries.RELAY_PROVIDER_FLAGS) == 31
    assert variables.items() >= queries.RELAY_PROVIDER_FLAGS.items()


# --- cursor discovery ---------------------------------------------------------


def test_find_page_info_inline_delivery():
    raw = _page([{"node": {}}], connection="news_feed", cursor="CUR", has_next=True)
    assert graphql.find_page_info(raw, "news_feed") == {
        "end_cursor": "CUR",
        "has_next_page": True,
    }


def test_find_page_info_deferred_delivery():
    raw = _deferred_page(
        [{"node": {}}], connection="timeline_list_feed_units", cursor="CUR", has_next=True
    )
    assert graphql.find_page_info(raw, "timeline_list_feed_units")["end_cursor"] == "CUR"


def test_find_page_info_ignores_a_different_connections_cursor():
    """Responses nest unrelated connections; paginating on one would walk the wrong list."""
    raw = json.dumps(
        {
            "data": {
                "node": {
                    "important_reactors": {
                        "edges": [],
                        "page_info": {"end_cursor": "WRONG", "has_next_page": True},
                    },
                    "timeline_list_feed_units": {
                        "edges": [],
                        "page_info": {"end_cursor": "RIGHT", "has_next_page": True},
                    },
                }
            }
        }
    ).encode()
    assert graphql.find_page_info(raw, "timeline_list_feed_units")["end_cursor"] == "RIGHT"


def test_find_page_info_returns_none_when_absent():
    raw = json.dumps({"data": {"node": {"news_feed": {"edges": []}}}}).encode()
    assert graphql.find_page_info(raw, "news_feed") is None


# --- pagination loop ----------------------------------------------------------


class _FakeFetcher(graphql.ActiveFetcher):
    """Records the variables of each call and replays canned pages."""

    def __init__(self, pages: list[bytes]) -> None:
        super().__init__(_tokens(), request_interval=(0.0, 0.0))
        self._pages = list(pages)
        self.calls: list[dict] = []

    def _throttle(self) -> None:  # keep unit tests instant; the floor is tested above
        pass

    def post(self, spec, variables, *, referer=None) -> bytes:
        self.calls.append(variables)
        return self._pages.pop(0)


def test_paginate_follows_the_cursor_then_stops_on_has_next_false():
    spec = queries.QUERIES["timeline"]
    fetcher = _FakeFetcher(
        [
            _deferred_page([], connection=spec.connection_key, cursor="C1", has_next=True),
            _deferred_page([], connection=spec.connection_key, cursor="C2", has_next=False),
        ]
    )

    pages = list(fetcher.paginate(spec, {"id": "1"}))

    assert len(pages) == 2
    assert fetcher.calls[0]["cursor"] is None  # first page starts at the top
    assert fetcher.calls[1]["cursor"] == "C1"  # second page follows page 1's cursor


def test_paginate_stops_at_max_pages():
    spec = queries.QUERIES["timeline"]
    forever = [
        _deferred_page([], connection=spec.connection_key, cursor=f"C{i}", has_next=True)
        for i in range(10)
    ]
    fetcher = _FakeFetcher(forever)

    assert len(list(fetcher.paginate(spec, {"id": "1"}, max_pages=3))) == 3


def test_paginate_stops_when_cursor_is_missing():
    spec = queries.QUERIES["timeline"]
    fetcher = _FakeFetcher(
        [_deferred_page([], connection=spec.connection_key, cursor=None, has_next=True)]
    )

    assert len(list(fetcher.paginate(spec, {"id": "1"}))) == 1


def test_paginate_rejects_a_non_paginating_query():
    with pytest.raises(ValueError, match="does not paginate"):
        list(_FakeFetcher([]).paginate(queries.QUERIES["post"], {}))


# --- logged-out detection (recon §5.1) ----------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b'{"error":1357001,"errorSummary":"Sorry, something went wrong"}',
        b'{"data":{"caa_login_form_data":{}}}',
        b'{"fb_api_req_friendly_name":"CAAFetaAYMHPasswordEntryQuery"}',
    ],
)
def test_looks_logged_out_detects_login_shaped_responses(raw):
    """Facebook serves the login form in-place at HTTP 200 with no redirect, so
    the response shape is the only reliable signal (recon §5.1)."""
    assert graphql.looks_logged_out(raw)


def test_looks_logged_out_is_false_for_a_normal_response():
    assert not graphql.looks_logged_out(
        _page([{"node": {}}], connection="news_feed", cursor="C", has_next=False)
    )


def test_post_raises_session_expired_on_a_login_shaped_response(monkeypatch):
    fetcher = graphql.ActiveFetcher(_tokens(), request_interval=(0.0, 0.0))
    monkeypatch.setattr(fetcher, "_throttle", lambda: None)

    class _Resp:
        status = 200
        body = b'{"error":1357001}'

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(graphql, "FetcherSession", lambda **kw: _Session())
    with pytest.raises(SessionExpiredError):
        fetcher.post(queries.QUERIES["timeline"], {})


def test_post_raises_active_transport_error_on_non_200(monkeypatch):
    """A rotated doc_id or a server hiccup must be recoverable-by-fallback, not fatal."""
    fetcher = graphql.ActiveFetcher(_tokens(), request_interval=(0.0, 0.0))
    monkeypatch.setattr(fetcher, "_throttle", lambda: None)

    class _Resp:
        status = 500
        body = b"{}"

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(graphql, "FetcherSession", lambda **kw: _Session())
    with pytest.raises(ActiveTransportError):
        fetcher.post(queries.QUERIES["timeline"], {})
