# Plan — v0.3.0 active-mode expansion + navigation primitives

**Status:** approved plan, ready to implement in a *fresh* session.
**Companion:** [2026-07-20-recon-findings.md](./2026-07-20-recon-findings.md) — the live-captured
`doc_id`s, variable shapes, and the end-to-end proof this plan is built on. Read it first.
**Baseline:** `agentic-facebook` v0.2.0 (PyPI), 75 unit tests green, single-profile passive scraper.

> **How to use this doc (next session):** implement in the phase order of §9. Do **not**
> plan and implement in the same breath for each phase — each phase names a *verify* gate;
> loop until it passes. Honor `CLAUDE.md`: minimum code, surgical changes, no speculative
> abstractions. The recon already de-risked the hard unknowns; the work now is disciplined engineering.

---

## 1. Goal & framing

Turn the single-profile passive scraper into a small set of **fast, composable CLI
primitives** that read Facebook into a clean schema over the **backend GraphQL API**,
so a future `.claude/skills/facebook` can drive Facebook "like a human" by *chaining*
primitives — feed → a post's author → that author's timeline → a post's comments →
search — with the **LLM doing the navigation reasoning and the CLI doing the fast,
structured retrieval.**

Non-goals (explicitly out of scope, per the agreed division of labor):
- No crawler/orchestration engine *inside* the CLI. Multi-hop is the LLM's job (decision below).
- No Instagram/Threads. No mass-scraping. No scheduler/daemon.

## 2. Locked decisions (from interview + recon)

| # | Decision | Source |
|---|---|---|
| D1 | **Architecture: active (HTTP GraphQL) primary + passive (browser) fallback, one shared parser.** | interview Q1 + recon §1 (proven) |
| D2 | New surfaces to add: **home feed, comments (body/author), groups/pages, search.** | interview Q2 (all four) |
| D3 | **Multi-hop is the LLM's job.** CLI stays single-purpose primitives; the skill chains them. | interview Q3 |
| D4 | **Throwaway account; ban risk accepted** — but keep the non-mass-scraping floor (now an *active-request* floor). Use scrapling's stealth/impersonation levers as needed. | interview Q4 |
| D5 | **Comments: top-level by default, `--replies` opt-in.** `depth==0` vs `depth>=1` maps exactly (recon §3). | interview Q_comments |
| D6 | **Version 0.3.0, additive, reposition README.** Existing `fetch` schema/flags stay back-compatible; "no token replay" reframed as "your own session's token, used the way your browser uses it" (not injection of a foreign token). | interview Q_version |
| D7 | End state: publish to PyPI (push → auto-publish), then build `.claude/skills/facebook` that installs and drives it. | user messages |

## 3. Architecture

```
                         ┌─────────────────────────────────────────┐
   agentic-facebook login  ───▶ │ Browser (scrapling DynamicSession)       │
                         │  • one-time interactive login (persist)  │
                         │  • extract tokens (fb_dtsg/cookies/rev)  │
                         │  • refresh tokens + doc_ids when stale   │
                         └───────────────┬──────────────────────────┘
                                         │ SessionTokens (cached on disk)
                                         ▼
   agentic-facebook feed  ────▶  ActiveFetcher (FetcherSession, HTTP) ──▶ /api/graphql/
   agentic-facebook fetch ────▶      │  build body · paginate by cursor      (fast path)
   agentic-facebook comments ─▶      │  rate-limited (active floor)
   agentic-facebook search ──▶       │
   agentic-facebook group ───▶       └── on login/error/doc_id-miss ──▶ PassiveFetcher
                                                                  (browser scroll, current)
                                         │ response bytes (identical JSON either way)
                                         ▼
                          parse.py / model.py   ← UNCHANGED, transport-agnostic
                                         │
                                         ▼
                              JSON / NDJSON  (Post, Comment schemas)
```

**Key invariant (proven in recon §1):** active and passive produce the *same* GraphQL
JSON, so `parse.py`/`model.py` are untouched. Active mode is a new **transport**, not a
new parser. Everything new is upstream of the parser (getting bytes) or a small amount
downstream (Comment/search shaping the parser doesn't cover yet).

### New modules

| Module | Responsibility |
|---|---|
| `tokens.py` | `SessionTokens` (cookies, fb_dtsg, lsd, user_id, rev). Extract from a browser page (recon §1 regexes), cache to `<data>/tokens/<profile>.json`, `is_stale()`, refresh. `jazoest` computed, not scraped. |
| `queries.py` | Registry of `QuerySpec(name, doc_id, connection_path, cursor_var, default_variables)` per surface. Seeded from recon §2. A `refresh_doc_ids()` re-harvests from a live browser. |
| `graphql.py` | `ActiveFetcher`: `build_body(spec, variables, tokens)`, `post(...)` via `FetcherSession(impersonate="chrome")`, and `paginate(spec, variables) -> Iterator[bytes]` (cursor loop with the **active rate floor**). |
| `transport.py` | Thin `Fetcher` protocol + `active_then_passive(...)` fallback wrapper. |
| `comments.py` | `Comment` model + parse comment nodes (author/body/created_time/depth/feedback) out of a `CometSinglePostDialogContentQuery` response. |
| `search.py` | Result-type-aware shaping (posts vs people vs pages vs groups). |

Existing modules: `retrieve.py` becomes transport-agnostic (takes a `Fetcher`); `scroll.py`
stays as the passive fetcher's engine; `session.py` gains token-extraction + the login/status fixes.

## 3a. Login / session acquisition (decision A + a verified caveat)

**Decision (interview):** the **isolated dedicated profile stays the default** (keeps the
throwaway-account safety model; no dependency on the user's Chrome setup); **fix the login
UX**; add **`--from-chrome`** as an opt-in convenience.

1. **Fix the manual-login UX — the actual friction.** Replace `run_login`'s `input()` gate
   with **browser-state polling** (treat login as done when the login form is gone / a feed
   GraphQL query fires) or a file-signal handshake, so login is smooth and an agent can
   drive it without a human pressing Enter in a TTY. The `input()` gate hung under Claude
   Code's `!` and held the Chromium profile lock (recon §5.3).

2. **`--from-chrome` is viable but NOT trivial — VERIFIED 2026-07-20.** The naive path
   (copy a Chrome profile + open with scrapling `real_chrome=True`) **fails on macOS**: it
   lands on the login form with **0 feed queries**. Root cause: **Playwright launches Chrome
   with `--use-mock-keychain`**, so Chrome can't reach the real "Chrome Safe Storage"
   Keychain entry and every cookie fails to decrypt → logged out. (Confirmed the user's real
   Chrome `Default` profile *is* logged into Facebook — `c_user/xs/datr/...` present — yet
   the copied-profile launch showed the login form.) Two realistic implementations, to
   validate in implementation:
   - **(a) Decrypt + inject (pycookiecheat-style, recommended).** Read the key from the
     Keychain (`security find-generic-password -s "Chrome Safe Storage"`), derive the AES
     key (PBKDF2-HMAC-SHA1, salt `saltysalt`, 1003 iters, 16 bytes), AES-CBC-decrypt the
     `v10`-prefixed cookie values from the profile's `Cookies` DB, inject via
     `context.add_cookies` / `FetcherSession(cookies=...)`. Headless-friendly, self-contained.
     Caveat: it *is* literal cookie extraction (touches the Keychain, may prompt once) —
     closest to the "credential injection" the positioning avoids, so opt-in + documented.
   - **(b) CDP attach.** Connect to the user's *already-running* Chrome via `cdp_url` (Chrome
     started with `--remote-debugging-port`); the live session already holds decrypted
     cookies, no key handling — but needs the debug flag and drives the real browser.

   Ship default = isolated profile; `--from-chrome` = opt-in via **(a)**. Keep the
   throwaway-account guidance prominent (importing an everyday Chrome usually means a main account).

## 4. Command surface (the primitives the skill will chain)

Every command emits the **same output contract** as `fetch` today (JSON array / NDJSON,
default output under the data dir, never cwd; `--format`, `--output`, `--limit`, exit codes).
Every post output already carries `id`, `url`, `author_url`, `author_id` — **these are the
handles the LLM uses to chain to the next call.** Keep them populated everywhere.

| Command | Surface / query | Notable flags | Output |
|---|---|---|---|
| `fetch <profile>` *(existing)* | profile timeline (`ProfileCometTimelineFeedRefetchQuery`) | `--limit --since --until` — **now precise** via `afterTime/beforeTime` when active (recon §2) | `Post[]` |
| `feed` *(new)* | home news feed (`CometNewsFeedPaginationQuery`) | `--limit` (`--since/--until` best-effort — home feed has no clean date filter; document it) | `Post[]` |
| `comments <post-url-or-id>` *(new)* | `CometSinglePostDialogContentQuery` | `--limit --sort top\|recent --replies` (recon §3) | `Comment[]` |
| `post <post-url-or-id>` *(new, small)* | same dialog query | — | one `Post` (fills the gap that permalink pages yield 0 feed-graphql, recon §4) |
| `search <query>` *(new)* | `SearchCometResultsPaginatedResultsQuery` | `--type top\|posts\|people\|pages\|groups --limit` | typed results |
| `group <group-url-or-id>` *(new)* | specific-group feed (confirm exact query in Phase 0; cross-group = `GroupsCometCrossGroupFeedPaginationQuery`) | `--limit` | `Post[]` |
| `tokens` *(new, internal-ish)* | — | `--refresh` | prints token/doc_id freshness; drives refresh |

Design rule (D3): **no `crawl` command.** If the user is tempted, that's the skill's job.

## 5. Schema changes (additive — D6)

- **`Post`**: add `source: str` (`"timeline" | "newsfeed" | "group" | "search"`) so chained
  outputs are self-describing. Everything else unchanged. `schema`/`json_schema` auto-update
  (they derive from `to_dict()`).
- **New `Comment`** dataclass + `to_dict()` + schema entry:
  `id, post_id, author_name, author_url, author_id, text, created_at, depth, parent_id,
  reaction_count, reply_count, captured_at`.
- Search results: reuse `Post` for post-type hits; add a light `Entity` shape
  `{type: "person"|"page"|"group", name, url, id, verified}` for non-post hits.
- Bump `schema` subcommand to cover the new objects. Keep the co-located
  `FIELD_DESCRIPTIONS` discipline (model.py) so docs never drift from fields.

## 6. The guardrail, re-expressed for active mode (D4 — do not skip)

The current non-bypassable floor is `MIN_SCROLL_PAUSE_SECONDS` — a *passive* concept.
Active mode fires HTTP POSTs with no scrolling, so **that floor no longer constrains
volume.** Introduce an **active-request floor**: `MIN_REQUEST_INTERVAL_SECONDS`
(e.g. 1.0s, clamped, non-bypassable, jittered) enforced in `graphql.paginate()`. This
keeps the project's stated identity ("one hard limit that keeps this from being a
mass-scraper", README/DISCLAIMER §1) true in the new transport. One profile per
invocation stays. Document that deep pagination = more requests = more ban risk.

## 7. Testing strategy

- **Unit (CI, PII-free):** skeletonize today's captured responses into new fixtures under
  `tests/fixtures/` (scrub names/urls/tokens — reuse `scratch/dump_skeleton.py` + `redact`).
  New tests: `paginate()` cursor loop (mocked bytes), `build_body`/`jazoest`, token
  extraction from an HTML fixture, comment parsing (depth 0/1), search result typing,
  login-form detection (the §5 status bug). Existing 75 tests must stay green (parser unchanged).
- **Live (opt-in, `SFB_LIVE_TESTS=1`, never CI):** `tests/live/` — currently empty. Promote
  the recon scripts (scratchpad) into real opt-in live tests: login-state check → active
  `feed`/`fetch` → assert ≥1 parseable post; active-vs-passive parity on the same target.
- **Verify gates** are named per phase in §9.

## 8. Packaging & the eventual skill (D7)

- Ship **0.3.0** (additive). Update README/DISCLAIMER: reframe positioning (D6), document
  active mode, the active-request floor, and the (larger) comment PII surface. Bump
  `schema`. Publish path is unchanged (GitHub Release → PyPI Trusted Publishing).
- **`.claude/skills/facebook`** (separate follow-up session, after PyPI): a skill that
  (1) ensures/refreshes login, (2) teaches Claude to chain primitives for real tasks
  ("what is X's circle discussing?" = `fetch X` → collect `author_url`s of sharers →
  `fetch` each → `search` topics), (3) carries the ban/PII guidance as *why*-backed rules,
  (4) documents the schema so Claude parses outputs without guessing. It installs the
  published package (`uv tool install agentic-facebook`) and shells out to `agentic-facebook`.
  Build it with the `harness-creator` skill.

## 9. Implementation phases (ordered; each has a verify gate)

**Phase 0 — Live re-validation (MUST be first; doc_ids rotate).**
Re-run the recon (scripts below) against a fresh login to (a) refresh every `doc_id` in
`queries.py`, (b) capture the **comment-pagination** query that eluded this pass (recon §3
gap) by opening a post dialog and clicking "view more comments", (c) confirm the server
honors `afterTime`/`beforeTime` on the timeline query.
*Verify:* `poc_replay.py`-style active call returns parseable posts with today's-fresh ids.

**Phase 1 — Active transport core + `fetch` parity.**
Build `tokens.py`, `queries.py`, `graphql.py`, `transport.py`. Rewire `retrieve.py` to be
transport-agnostic; make `fetch` active-first with passive fallback. Add the active-request
floor (§6).
*Verify:* `fetch <profile>` returns the same posts active vs passive (parity test); unit tests green; active-request floor enforced (test it can't be set to 0).

**Phase 2 — `feed` (home news feed).**
*Verify:* `feed --limit N` returns N home-feed posts with populated `author_url`/`url` (chainability); `source=="newsfeed"`.

**Phase 3 — `comments` + `post`.**
Parse `CometSinglePostDialogContentQuery`; `Comment` model; `--replies` toggles depth.
*Verify:* `comments <url>` returns top-level comments (author/text/date); `--replies` adds depth≥1; `post <url>` returns the single post permalink pages can't yield via feed-graphql.

**Phase 4 — `search`.**
Result-type handling (§5).
*Verify:* `search "x" --type posts` returns posts; `--type people` returns person entities; pagination cursor advances.

**Phase 5 — `group`.**
Confirm the specific-group query in Phase 0; implement.
*Verify:* `group <id> --limit N` returns that group's posts.

**Phase 6 — Hardening + release.**
Fix `status`/`detect_wall` login-form detection (recon §5.1); fix `login` for non-interactive
drivers (recon §5.3); README/DISCLAIMER reposition; new fixtures + tests; bump to 0.3.0; tag/release.
*Verify:* full suite green; `status` correctly reports a logged-out stale session; `--version` == 0.3.0.

**Phase 7 — (separate session) build `.claude/skills/facebook`** via `harness-creator`.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `doc_id`/variable rotation breaks active mode | Passive fallback (same parser) + `tokens --refresh` / `refresh_doc_ids()` re-harvest; treat every active call as fallible (fall back, don't crash). |
| Fast HTTP → mass-scraping / ban | Active-request floor §6 (non-bypassable, jittered); throwaway account (D4); one profile/invocation. |
| `fb_dtsg` expiry mid-run | Re-extract on auth-shaped error; cache with `is_stale()`. |
| Silent logged-out state (recon §5.1) | Detect login-form response shape, raise `SessionExpiredError`, don't emit empty success. |
| Comment PII (larger surface) | Reaffirm DISCLAIMER; comment-specific note; redaction path covers comment text in diagnostics. |
| Agent can't complete `login`'s `input()` (recon §5.3) | Replace with browser-state polling / signal handshake before the skill relies on it. |
| Scope creep vs CLAUDE.md | No `crawl`, no speculative config; each phase's diff traces to a listed command. |

## 11. Recon reproduction (for Phase 0)

The scratchpad recon scripts (not committed; recreate under `tests/live/` or scratch):
`recon_capture_v2.py` (multi-surface request capture), `recon_comments.py` (open a post's
comment UI), `poc_replay.py` (browser-extract tokens → pure-HTTP GraphQL replay → parse).
All reuse the `default` login profile and `scrapling`'s `DynamicSession`/`FetcherSession`.
See recon-findings §1 for the exact token regexes, minimal body, and headers.
