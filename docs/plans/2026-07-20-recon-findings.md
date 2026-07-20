# Recon findings — live GraphQL reverse-engineering (2026-07-20)

Empirical grounding for [2026-07-20-active-mode-expansion-plan.md](./2026-07-20-active-mode-expansion-plan.md).
Everything here was captured from a **real logged-in session** (throwaway account,
`default` profile) by driving the package's own `scrapling` browser and reading
`page.on("request")` / `page.on("response")`. Raw capture artifacts lived in a
scratchpad outside the repo and are **not** committed (they contain third-party PII).

> **doc_ids and variable shapes rotate.** Every `doc_id` below is a snapshot from
> 2026-07-20. Treat them as *examples of the shape to expect*, not durable constants —
> see §6 (durability) in the plan. The **method** of discovery (capture from a live
> browser, then replay) is the durable asset, not any single id.

---

## 1. Headline result: ACTIVE MODE IS PROVEN END-TO-END

A proof-of-concept (`poc_replay.py`) did the full active-mode loop and succeeded:

1. **Browser (token extraction only):** loaded `facebook.com/me` with the persisted
   login profile, scraped auth material out of the page.
2. **Pure HTTP (no browser in the hot path):** `scrapling.FetcherSession(impersonate="chrome")`
   POSTed to `https://www.facebook.com/api/graphql/` with a real captured query.
3. **Result:** HTTP **200**, a **1.2 MB** response, parsed by the package's **existing**
   `parse.parse_story_nodes` + `model.build_post` into **3 real top-level posts**.

**Consequences that shape the plan:**
- The browser is only needed for **login + periodic token/doc_id refresh**, never for data retrieval.
- The **existing parser is transport-agnostic** — HTTP-fetched and browser-captured responses are byte-for-byte the same GraphQL JSON. `parse.py`/`model.py` need **no changes** to work in active mode. This is the single most important finding: active mode is a new *transport*, not a new *parser*.
- A **minimal** POST body is sufficient. `__dyn`, `__csr`, `__hs`, `__hsdp`, `__sjsp` were **omitted** and it still worked.

### Auth material needed for an active request

| Item | Where it comes from | Notes |
|---|---|---|
| Cookies | `page.context.cookies()` on any logged-in page | Observed: `c_user, xs, datr, fr, sb, ps_l, ps_n, wd`. `c_user` + `xs` are the session. |
| `fb_dtsg` | regex on page HTML: `"DTSGInitialData",[],{"token":"([^"]+)"` | CSRF token; rotates within a session — re-extract periodically. |
| `lsd` | regex: `"LSD",[],{"token":"([^"]+)"` | |
| `__user` / `av` | regex: `"USER_ID":"(\d+)"` | the logged-in actor id |
| `__rev` / `__spin_r` | regex: `"__spin_r":(\d+)` | client revision; stale-tolerant |
| `jazoest` | **computed**: `"2" + str(sum(ord(c) for c in fb_dtsg))` | no need to scrape it |

### Minimal POST body that worked (form-urlencoded)

```
av, __user           = <USER_ID>
__a                  = 1
__comet_req          = 15
fb_dtsg              = <extracted>
jazoest              = <computed from fb_dtsg>
lsd                  = <extracted>
__spin_r, __rev      = <extracted rev>   (stale-tolerant)
server_timestamps    = true
fb_api_caller_class  = RelayModern
fb_api_req_friendly_name = <query name>
variables            = <JSON string>
doc_id               = <query doc_id>
```

### Required headers

```
content-type      : application/x-www-form-urlencoded
x-fb-friendly-name: <query name>
x-fb-lsd          : <lsd>
origin            : https://www.facebook.com
referer           : https://www.facebook.com/<relevant path>
```

---

## 2. Per-surface query catalog (2026-07-20 snapshot)

All are `POST /api/graphql/`, `fb_api_caller_class=RelayModern`. "Pagination var" = the
variable that carries the cursor. Response cursor lives at `<connection>.page_info.{end_cursor,has_next_page}`.

| Surface | Query (`fb_api_req_friendly_name`) | `doc_id` | Key variables | Response connection |
|---|---|---|---|---|
| **Home feed** | `CometNewsFeedPaginationQuery` | `27790894430578947` | `cursor`, `count`(5), `feedLocation:"NEWSFEED"`, `orderby:["TOP_STORIES"]`, `renderLocation:"homepage_stream"` | `viewer…news_feed` |
| **Profile timeline** | `ProfileCometTimelineFeedRefetchQuery` | `27676223615330440` | `id:"<profileId>"`, `cursor`, `count`(3), `feedLocation:"TIMELINE"`, `omitPinnedPost`, **`afterTime`/`beforeTime`**, `postedBy`, `taggedInOnly` | `node.timeline_list_feed_units` |
| **Profile tiles/highlights** | `ProfileCometTilesFeedPaginationQuery` | `27971913519111336` | `id`, `cursor`, `count` | (tiles) |
| **Groups (cross-group)** | `GroupsCometCrossGroupFeedPaginationQuery` | `27520387417615619` | `cursor`, `count`(5), `feedLocation:"GROUP"`, `renderLocation:"groups_tab"` | `group_feed` |
| **Search (all types)** | `SearchCometResultsPaginatedResultsQuery` | `28091046377146459` | `args:{text, callsite:"COMET_GLOBAL_SEARCH", experience:{type:"GLOBAL_SEARCH"}, filters:[]}`, `count`(5), `cursor` (JSON w/ `page_number`) | `page_info` on results |
| **Single post + comments** | `CometSinglePostDialogContentQuery` | `27371991432470815` | post id / story context | inline post + comments |
| **UFI container** | `CometUFIConversationGuideContainerQuery` | `25316047617978702` | `feedbackID`, `feedLocation`, `scale` | UFI |
| **Stories tray** (bonus) | `StoriesTrayRectangularQuery` | `27238086775841395` | `cursor`, `bucketsToFetch`, … | stories |

**The date-filter finding (high value).** `ProfileCometTimelineFeedRefetchQuery` accepts
`afterTime` / `beforeTime` (unix seconds). Active mode can therefore do a **precise**
`--since`/`--until` on a profile timeline by passing these directly — a categorical
improvement over the current passive tool, which can only scroll-until-date on a
best-effort basis (exit code 7). Needs live confirmation that the server honors them
(they were `null` in every captured request), but the variables exist.

### Full variable examples

`ProfileCometTimelineFeedRefetchQuery` (relay-provider flags omitted):
```json
{"afterTime": null, "beforeTime": null, "count": 3, "cursor": "<opaque>",
 "feedLocation": "TIMELINE", "omitPinnedPost": true, "postedBy": null,
 "privacy": null, "renderLocation": "timeline", "scale": 2, "stream_count": 1,
 "taggedInOnly": null, "id": "<profileId>"}
```
`SearchCometResultsPaginatedResultsQuery`:
```json
{"count": 5, "cursor": "{\"page_number\":0,\"flow_cursors_serialized\":{…}}",
 "args": {"callsite": "COMET_GLOBAL_SEARCH", "config": {"exact_match": false, …},
          "context": {"bsid": "<uuid>"}, "experience": {"type": "GLOBAL_SEARCH", …},
          "filters": [], "text": "seoul"},
 "feedLocation": "SEARCH", "renderLocation": "search_results_page", "scale": 2}
```
Each pagination query also carries **~27–31 `__relay_internal__pv__*relayprovider`
boolean flags**. They must be reproduced in the request (copy a captured set); their
values are GK toggles, stale-tolerant, but omitting the keys entirely can error.

---

## 3. Comment structure (confirmed)

From the `CometSinglePostDialogContentQuery` response, comment nodes have:

| Field | Path | Example |
|---|---|---|
| author name | `author.name` | `"<commenter name>"` |
| body text | `body.text` | `"<comment text>"` |
| timestamp | `created_time` (unix) | `1784342488` |
| **depth** | `depth` | `0` = top-level, `1` = reply |
| id | `id`, `legacy_fbid` | |
| own reactions | `feedback` | comments have their own feedback node |

`depth` maps **exactly** onto the agreed comment design: top-level (`depth==0`) by default,
`--replies` includes `depth>=1`.

**Gap:** deep comment pagination ("view more comments") uses a separate query
(expected `CommentsListComponentsPaginationQuery` or similar) that was **not** captured —
the initial dialog query returned only the first batch. See plan Phase-0 follow-up.

---

## 4. Parser validation on live data (existing code, no changes)

Ran the current `parse.parse_story_nodes` + `model.build_post` on captured responses:

| Surface | Top-level posts parsed | Notes |
|---|---|---|
| Home feed | **43** | authors, type, date, reaction/comment/share counts, body — all correct |
| Own profile | **30** | |
| Groups feed | **20** | |
| Search | 5 (partial) | **mixed result types** — people/pages aren't story-shaped (`author=None, type=unknown`) |

Before today, the parser had been live-tested against **one** profile, once. It now has
**multi-surface** live validation. Two confirmed parser gaps:
- **Search** results interleave posts + people + pages; only post-shaped results parse. Needs a result-type-aware path.
- **Permalink pages return 0 GraphQL stories** — the post body is server-rendered into the initial HTML document, not a GraphQL XHR. Comments arrive via the dialog/UFI query, not a feed query. So "fetch one post by URL" cannot reuse the feed-scrape path; it must use `CometSinglePostDialogContentQuery`.

---

## 5. Session / login findings (bugs to fix)

1. **`status` / `detect_wall` gives false positives.** A 15-day-old session was actually
   logged **out**, but `scrape-fb status` reported `logged_in`. Cause: `detect_wall()`
   only checks the URL for `/login` or `/checkpoint`, but Facebook serves the **login
   form in-place at `https://www.facebook.com/` with HTTP 200** (no redirect). The
   response body is a `caa_login_form_data` payload (`fb_api_req_friendly_name:
   CAAFetaAYMHPasswordEntryQuery`, `login_source: "COMET_HEADERLESS_LOGIN"`). **Fix:**
   detect the login-form / password-entry query (or absence of a feed query) in the
   response, not just the URL. This matters more in active mode, where a silent
   logged-out state would otherwise produce confusing empty results.

2. **Headless is fine with a fresh session.** The earlier headless failure was **staleness**,
   not bot-detection. Vanilla `DynamicSession` (headless) returned full feed data once
   re-logged-in. So headless remains viable for the token-refresh browser step; stealth
   (`StealthySession`) is a fallback lever, not a day-one requirement.

3. **`login`'s `input()` wait is hostile to non-interactive drivers.** `run_login` blocks
   on `input("…press Enter…")`. Under Claude Code's `!` shell this hangs and holds the
   profile's Chromium lock, blocking every subsequent browser launch. **Fix for the skill
   era:** replace the `input()` gate with browser-state polling (detect a logged-in
   marker), or a `login --wait-seconds` / file-signal handshake, so an agent can drive
   login without a human pressing Enter in a TTY.

4. **`--from-chrome` naive path fails (Playwright forces `--use-mock-keychain`).** Copying a
   logged-in Chrome profile and opening it with scrapling `real_chrome=True` lands on the
   **login form** with **0 feed queries** — Playwright's default `--use-mock-keychain`
   launch arg prevents Chrome from decrypting cookies encrypted by the real macOS Keychain
   "Chrome Safe Storage". The real Chrome `Default` profile was confirmed logged into
   Facebook (cookie *metadata*: `c_user/xs/datr/sb/fr` present) yet the copy opened
   logged-out. So `--from-chrome` needs **manual decrypt + inject** (Keychain key →
   PBKDF2-HMAC-SHA1(salt `saltysalt`, 1003, 16) → AES-CBC on `v10`-prefixed values) or a
   **CDP attach** to a running Chrome — see plan §3a. Detecting *which* profile holds a
   session is cheap and non-invasive: query each profile's `Cookies` DB for a
   `facebook.com` `c_user` row (name/domain only, no value decryption).

---

## 6. Durability risk (the one real weakness of active mode)

`doc_id`s and the relay-provider variable set **rotate** as Facebook ships client builds.
An active request built against a stale `doc_id` will fail. Mitigations the plan adopts:
- **Passive browser fallback** (same parser) when an active call fails or returns a login/error shape.
- **doc_id (re)discovery from a live browser**: the ids are embedded in the page's JS
  bundles and in the captured requests; a `refresh`/`--discover` step can re-harvest them
  the same way this recon did, writing them to a small on-disk registry the active client reads.
- Treat every active call as **fallible**: on a non-story response shape, fall back, don't crash.
