# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] - 2026-07-21

### Fixed
- **`FacebookScraper(profile=...)` used the wrong account's cached credentials.** Active mode keys its token cache by profile *name* while the browser session is keyed by *directory*; the Python facade forwarded only the directory, so a non-default profile drove one account's browser while reading — and overwriting — the token cache belonging to `default`. With a populated cache that meant retrieving as the wrong account, and either way it corrupted the other profile's cached cookies. Silent rather than a crash. Affects the Python API only with a non-default `profile`; the CLI was never affected. Introduced in 0.3.0.

### Changed
- The PyPI summary and keywords now match the README and the repository description, instead of still describing the v0.2.0 browser-only scraper. Package metadata is frozen per release, so this could only be corrected by publishing.

### Documentation
- The whole documentation set rewritten for v0.3.x: twelve `docs/wiki/` pages (adding Architecture and Chaining-Recipes), a rewritten README, and CONTRIBUTING / SECURITY / CODE_OF_CONDUCT at the repository root. Pages now defer to `scrape-fb catalog` and `scrape-fb schema` for anything the CLI can describe about itself.


## [0.3.1] - 2026-07-20

### Added
- **`scrape-fb catalog [--json]`** — the CLI describing itself: every command and flag, the exit-code contract, the output contract, the object types, and the known limitations, in one call. It is **derived, not authored**: commands and flags are introspected from the live `argparse` parser, object types come from the same `to_dict()`-anchored functions `schema` uses, and exit codes come from a single table. Anything that needs to explain this tool (docs, an agent, a `.claude` skill) can now read it instead of transcribing it and drifting.
- `tests/test_catalog.py` enforces that derivation: adding a command or flag without it appearing in the catalog fails the suite, as does a subcommand with no handler.

### Changed
- Exit codes moved from scattered integer literals in `cli.py` into `exits.py`, which is now the single source for both the CLI's behavior and its description. No exit code changed value.


## [0.3.0] - 2026-07-20

Adds an **active transport** — reading Facebook's GraphQL API over plain HTTP,
with the browser needed only to log in — and turns the single-purpose scraper
into a set of composable primitives. Additive: `fetch`'s existing flags and
output schema are unchanged apart from one new field.

### Added
- **Active mode.** `fetch` now reads `/api/graphql/` over HTTP by default, paginating by cursor with no browser in the hot path, and falls back to the browser transport automatically when it fails (`--mode auto|active|passive`). Both transports share one parser, so their output is identical.
- **New commands**, each emitting the same output contract as `fetch`:
  - `feed` — your home news feed.
  - `comments <post_url>` — a post's comments, `--sort top|recent`, `--replies` for depth ≥ 1.
  - `post <post_url>` — a single post by permalink (which a feed query cannot return).
  - `search <query>` — `--type top|posts|people|pages|groups`.
  - `group <group_url_or_id>` — one group's feed.
- **`Comment` and `Entity` schemas**, both covered by `scrape-fb schema` / `schema --json`.
- `Post.source` (`timeline` | `newsfeed` | `group` | `search`) so chained output stays self-describing.
- `scrape-fb login --from-chrome` (opt-in): import an existing session from local Chrome by decrypting its cookie DB. Needs the `chrome` extra: `pip install 'scraper-for-facebook[chrome]'`. See DISCLAIMER §6 — this is literal cookie extraction and usually imports your main account.
- A **non-bypassable active-request floor** (`--request-interval`, MIN clamped to ≥ 1.0s, jittered), the active-mode counterpart to the scroll-pause floor. Applies to every active request, including id-resolution GETs.
- `--max-pages` (default 20) bounds active pagination depth.
- Opt-in live tests under `tests/live/` (`SFB_LIVE_TESTS=1`), including an active-vs-passive parity test.

### Fixed
- **`status` reported a dead session as `logged_in`.** `detect_wall()` only inspected the URL, but Facebook serves its login form in place at `https://www.facebook.com/` with HTTP 200 and no redirect. It now also inspects the response body, and treats a missing `DTSGInitialData` token as logged out.
- **`login` could not be driven non-interactively.** It blocked on `input()`, which hung forever under a non-TTY driver while holding the Chromium profile lock, blocking every later browser launch. It now polls the browser's own state and honors `--timeout-seconds`.

### Changed
- `--since`/`--until` are now a **precise server-side filter** in active mode (verified: they change which posts the server returns, not just which are kept). They remain best-effort in passive mode, still reported via exit code 7.
- Token refresh prefers a cheap HTTP re-read over relaunching the browser.
- README/DISCLAIMER repositioned: active mode uses *your own session's* tokens the way your browser does — still no credential injection and no foreign-token replay — and the DISCLAIMER now covers the much larger third-party PII surface that `comments`/`feed`/`search` collect.

### Known limitations
- `feed`/`comments`/`post`/`search`/`group` are active-only: they have no passive equivalent to fall back to if a `doc_id` rotates.
- Passive mode cannot see a profile's newest post (the first timeline batch is server-rendered, never fetched as a GraphQL XHR). Active mode can.
- `post`/`comments` do not support reel URLs (a reel page embeds no story id).
- `--replies` fetches depth-1 replies only.

## [0.2.0] - 2026-07-07

### Added
- `scrape-fb schema`: prints the `fetch` output object schema (field name, JSON type, one-line meaning), offline and always exit 0; `--json` emits JSON Schema (draft 2020-12). Anchored on `Post.to_dict()`'s actual output keys, not the dataclass fields, so it can't mis-document `raw` as always-present.
- Every `fetch`/`login`/`status`/`doctor` flag now has a `--help` string with its human-readable default, so `--help` is authoritative standalone without reading source.

### Changed
- No behavior change to `login`/`status`/`setup`/`doctor`/`fetch` themselves — additive only.

## [0.1.0] - 2026-07-05

### Added
- Initial release: `scrape-fb login` / `status` / `setup` / `doctor` / `fetch`.
- Logged-in Facebook timeline scraping via GraphQL XHR observation (no token replay).
- `--limit`, `--since`/`--until` retrieval with stop-reason reporting.
- JSON and NDJSON output formats.
- Python API: `FacebookScraper`, `Post`, `Media`, `LinkAttachment`.

[Unreleased]: https://github.com/tjdwls101010/Scraper-for-Facebook/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/tjdwls101010/Scraper-for-Facebook/releases/tag/v0.2.0
[0.1.0]: https://github.com/tjdwls101010/Scraper-for-Facebook/releases/tag/v0.1.0
