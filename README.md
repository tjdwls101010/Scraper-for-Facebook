# scraper-for-facebook

[![PyPI](https://img.shields.io/pypi/v/scraper-for-facebook.svg)](https://pypi.org/project/scraper-for-facebook/)
[![Python versions](https://img.shields.io/pypi/pyversions/scraper-for-facebook.svg)](https://pypi.org/project/scraper-for-facebook/)
[![CI](https://github.com/tjdwls101010/Scraper-for-Facebook/actions/workflows/ci.yml/badge.svg)](https://github.com/tjdwls101010/Scraper-for-Facebook/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Read **your own logged-in Facebook** — timelines, your news feed, comments, search, groups — into a clean JSON schema, over the same `/api/graphql/` endpoint your browser already uses. You log in once by hand; the tool then uses *your own session's* `fb_dtsg`/`lsd`/cookies the way your browser uses them. **No credential injection, no foreign tokens, no Graph API, no app review.**

> **Read [DISCLAIMER.md](DISCLAIMER.md) before using this.** Automating a Facebook account violates its Terms of Service, publishing this tool exposes its maintainer, and scraping other people's posts can make *you* a data controller over their personal data. Use a dedicated/throwaway account, not your primary one.

**This is not the first tool that does this.** [`facebook-graphql-scraper`](https://pypi.org/project/facebook-graphql-scraper/) captures GraphQL responses via Selenium + `selenium-wire` with credential-based login. This project's difference is incremental, not categorical: it reuses a **persisted browser-login profile** instead of injecting a username/password, and builds on [scrapling](https://github.com/D4Vinci/Scrapling)'s modern, actively-maintained fetch stack (Playwright-driven Chromium) instead of the largely-unmaintained `selenium-wire`.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Install](#install)
- [Quick start](#quick-start)
- [Example output](#example-output)
- [CLI reference](#cli-reference)
- [Guardrails](#guardrails)
- [Limitations](#limitations)
- [Python API](#python-api)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **No Graph API, no app review, no credential injection** — reuses your own persisted, logged-in browser session.
- **Composable primitives**: `fetch` (a timeline), `feed` (your news feed), `comments`, `post`, `search`, `group`. Every post carries `id`/`url`/`author_url`/`author_id`, so one command's output is the next one's input.
- **Active mode (v0.3.0)**: reads GraphQL over plain HTTP — no scrolling. Faster, and `--since`/`--until` become a **precise server-side filter** instead of scroll-until-you-see-it. Falls back to the browser automatically if it fails.
- Full post schema: body text (truncation-resolved), media and link attachments, reaction/comment/share counts, pinned flag, edited time, and one level of shared/quoted posts. Plus `Comment` and `Entity` schemas — see `scrape-fb schema`.
- JSON or NDJSON output, plus a typed Python API (`FacebookScraper`) for programmatic use.
- **Non-bypassable** pacing floors — the hard limit that keeps this from being usable as a mass-scraping tool, enforced in code, not just asked for in prose.

## How it works

`scrape-fb` never calls Facebook's Graph API, and never injects credentials or replays somebody else's token. You log in once, by hand, in a real browser; that session is persisted, and everything after that reads the same `/api/graphql/` endpoint your browser reads, with **your own** session's tokens.

There are two transports over that one endpoint, and they share a single parser — so both produce byte-identical JSON and therefore identical output:

| | **Active** (default) | **Passive** (fallback) |
|---|---|---|
| How | HTTP POST to `/api/graphql/`, paginated by cursor | Drives Chromium and scrolls, capturing the XHRs it fires |
| Browser | Only to log in and refresh tokens | In the hot path for every fetch |
| Speed | Seconds | Tens of seconds |
| `--since`/`--until` | **Precise** — a server-side date filter | Best-effort; can stall before reaching the date (exit 7) |

Active mode is tried first and falls back to the browser automatically when it fails — because the query ids it replays (`doc_id`s) rotate whenever Facebook ships a client build. `--mode active` or `--mode passive` forces one.

The tradeoff either way: this only ever sees what your logged-in account can already see, and it degrades when Facebook's response shape changes (see [Limitations](#limitations)).

## Install

This package depends on `scrapling[fetchers]`, which pins exact Playwright/patchright versions. Installing it into a shared environment alongside other Playwright-based tools can fail to resolve, or silently break one of them. **Always install this tool in an isolated environment:**

```bash
uv tool install scraper-for-facebook
# or
pipx install scraper-for-facebook
```

Do **not** `pip install scraper-for-facebook` into a general-purpose virtualenv you share with other projects.

After installing, provision the browser (into its own isolated cache — this never touches a browser install any other tool manages):

```bash
scrape-fb setup
```

**Platform:** macOS is the tested, first-class target (v1). Linux likely works for the fetch/parse/CLI layer but is untested against a live Facebook session. Windows is unsupported.

## Quick start

```bash
# 1. One-time interactive login — opens a real browser window, you log in by hand.
scrape-fb login

# 2. Verify the session (and that the browser + capture pipeline actually work).
scrape-fb doctor

# 3. Fetch the last 30 posts from a profile you're logged in and able to view.
scrape-fb fetch https://www.facebook.com/some.profile --limit 30

# ...or read your own news feed, a post's comments, or search.
scrape-fb feed --limit 20
scrape-fb comments https://www.facebook.com/some.profile/posts/pfbid02example --limit 50
scrape-fb search "seoul" --type people --limit 10
```

Because every post carries `url`, `author_url` and `author_id`, these compose:
`feed` gives you posts, each post's `url` feeds `comments`, and each commenter's
`author_url` feeds `fetch`. Chaining is deliberately left to the caller — this
tool stays a set of primitives and never crawls on its own.

Output defaults to a JSON file under this tool's own data directory (never your current directory or stdout — see `--output` below), because captured posts contain other people's personal data (§4 of the disclaimer) that shouldn't casually end up in a git-tracked path.

## Example output

Each post in the JSON/NDJSON output looks like this (values below are illustrative, not a real capture):

```json
{
  "id": "ZmVlZGJhY2s6MTIzNDU2Nzg5MDEyMzQ1",
  "url": "https://www.facebook.com/some.profile/posts/pfbid02example",
  "type": "status",
  "is_pinned": false,
  "author_name": "Jane Example",
  "author_url": "https://www.facebook.com/some.profile",
  "author_id": "100000000000001",
  "created_at": "2026-06-30T09:15:36Z",
  "edited_at": null,
  "text": "Full post body, truncation-resolved if it was ever cut short...",
  "text_truncated": false,
  "text_resolved": false,
  "media": [],
  "links": [],
  "reaction_count": 370,
  "comment_count": 32,
  "share_count": 14,
  "shared_post": null,
  "source": "timeline",
  "captured_at": "2026-07-05T03:18:13.385206Z"
}
```

`source` (`timeline` | `newsfeed` | `group` | `search`) is new in v0.3.0: once you start chaining commands, output from several of them ends up in one pile, and each post has to be able to say where it came from.

See [Output Schema](wiki/Output-Schema.md) for a field-by-field reference, including `media`/`links`/`shared_post` shapes.

## CLI reference

```
scrape-fb --version
scrape-fb login    [--profile NAME] [--profile-dir PATH] [--timeout-seconds N]
                   [--from-chrome [--chrome-profile NAME]]
scrape-fb status   [--profile NAME] [--profile-dir PATH] [--json]
scrape-fb setup
scrape-fb doctor   [--profile NAME] [--profile-dir PATH]
scrape-fb schema   [--json]

scrape-fb fetch    <profile_url_or_username>   # a profile's timeline  -> Post[]
scrape-fb feed                                 # your home news feed   -> Post[]
scrape-fb post     <post_url>                  # one post              -> Post
scrape-fb comments <post_url>                  # a post's comments     -> Comment[]
scrape-fb search   <query>                     # search                -> Post[] | Entity[]
scrape-fb group    <group_url_or_id>           # a group's feed        -> Post[]
```

Shared by every retrieval command:

```
    --profile NAME            persisted login profile (default: "default")
    --profile-dir PATH        override where the login profile is stored
    --limit N                 max results
    --format json|ndjson      default: json
    --output PATH             default: a non-repo path under this tool's data directory
    --request-interval MIN,MAX  seconds between active requests; MIN clamped to >= 1.0
    --max-pages N             active pagination budget (default 20)
    --headed                  show the browser (debugging)
    --raw                     include the raw captured node (debug; contains PII).
                              Redacted by default — combine with --no-redact for the
                              truly raw node (prints an on-screen PII warning).
    --no-redact               disable redaction of --raw output (only affects --raw)
    -v / --verbose            extra diagnostics (redaction-scrubbed by default)
```

Command-specific:

```
fetch     --since / --until YYYY-MM-DD   date bounds (inclusive). Precise in active mode.
          --mode auto|active|passive     transport (default: auto)
          --scroll-pause MIN,MAX         passive only; MIN clamped to >= 0.5
          --max-scrolls N                passive only; scroll budget (default 40)
comments  --sort top|recent              comment ordering (default: top)
          --replies                      also fetch replies (depth >= 1); one extra
                                         request per comment that has any
search    --type top|posts|people|pages|groups   (default: top)
```

`fetch`, `feed`, `post`, `search`, `group` emit `Post` objects (`search --type
people|pages|groups` emits `Entity` objects); `comments` emits `Comment`
objects. Run `scrape-fb schema` for every field, or `scrape-fb schema --json`
for JSON Schema.

**`scrape-fb catalog`** prints all of the above — commands, flags, exit codes,
output contract, object types, known limitations — in one call, generated from
the CLI itself. It's the authoritative version for whatever release you have
installed, and it's what a script or an agent should read instead of this page.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success — limit met, requested date window fully reached, or feed genuinely exhausted |
| 1 | Other/unexpected error |
| 2 | Login required or session expired — run `scrape-fb login` |
| 3 | Account checkpoint (Meta flagged the session) — log in again in a real browser |
| 4 | Zero posts returned — possibly parser drift against a Facebook response-shape change |
| 5 | Profile unavailable (memorialized, blocked, restricted, or nonexistent) |
| 7 | Partial: `--since` was requested but not confirmed reached within `--max-scrolls` |

A one-line summary on stderr always states the post count, observed date range, and *why* the run stopped — so a partial `--since` run is never mistaken for a complete one.

## Guardrails

Two pacing floors, one per transport. Both are clamped in code and **cannot be set to 0**, no matter how they arrive (CLI flag, env, or direct Python call):

- **Active**: `--request-interval` MIN is clamped to **≥ 1.0s**, jittered, and applies to *every* HTTP request including the plain GETs used to resolve ids.
- **Passive**: `--scroll-pause` MIN is clamped to **≥ 0.5s**.

The active floor exists because active mode fires HTTP POSTs with no scrolling at all — the scroll floor stops constraining anything the moment the fast transport is used, so "one hard limit that keeps this from being a mass-scraper" would quietly have become false without it.

- One target per invocation; no batch/multi-target mode; no built-in scheduler, daemon loop, or `crawl` command. Chaining commands is the caller's job.
- `--max-pages` (default 20) bounds how deep a single run paginates. Deeper runs mean more requests and more ban risk.
- Comments with `--replies` cost one extra request per commented comment — a 100-comment post can be a lot of requests. Prefer a `--limit`.

## Limitations

- Facebook only — no Instagram, no Threads (see roadmap).
- **`doc_id` rotation**: active mode replays query ids that change whenever Facebook ships a client build. When that happens `fetch` falls back to the browser automatically; the newer commands (`feed`, `comments`, `post`, `search`, `group`) have no passive equivalent and will error until the ids are refreshed.
- `--since`/`--until` are precise in active mode but **best-effort in passive** (exit code `7` says so).
- **Passive mode cannot see a profile's newest post.** The first timeline batch is server-rendered into the HTML document rather than fetched as a GraphQL XHR, so the browser-capture transport never observes it. Active mode does not have this gap.
- `post`/`comments` need a real post permalink; **reel URLs are not supported** (a reel page embeds no story id).
- `--replies` fetches depth-1 replies, not replies-to-replies.
- Media is captured as URLs only (no file download) — and those URLs are signed, expire, and are scoped to your viewing session; treat them as sensitive.
- No incremental `--since-last` state (yet).

## Python API

```python
from scraper_for_facebook import FacebookScraper, Post, Media, LinkAttachment
from scraper_for_facebook.errors import (
    LoginRequiredError, SessionExpiredError, ChallengeError,
    ProfileUnavailableError, SessionClosedError,
)

# One-time interactive login (opens a headed browser; you log in by hand).
FacebookScraper(profile="default").login()

with FacebookScraper(profile="default") as fb:                 # headless reuse
    posts: list[Post] = fb.fetch_profile(
        "https://www.facebook.com/some.profile", limit=30, since="2026-01-01",
    )
    for post in fb.iter_profile("https://www.facebook.com/some.profile", limit=30):
        ...  # must be consumed inside the `with` block

FacebookScraper(profile="default").status()   # -> Status.LOGGED_IN | EXPIRED | CHECKPOINT
```

## Documentation

This README covers the essentials. For everything else, see the **[wiki](wiki/README.md)**:

- [Installation](wiki/Installation.md) — platform notes, upgrading, uninstalling
- [Quick Start](wiki/Quick-Start.md) — a longer walkthrough than this README's
- [CLI Reference](wiki/CLI-Reference.md) — every flag, every exit code, with examples
- [Python API Reference](wiki/Python-API-Reference.md)
- [Output Schema](wiki/Output-Schema.md) — every `Post`/`Media`/`LinkAttachment` field explained
- [Configuration](wiki/Configuration.md) — profiles, environment variables, tuning scroll pacing
- [FAQ & Troubleshooting](wiki/FAQ-and-Troubleshooting.md)
- [Security & Privacy](wiki/Security-and-Privacy.md) — the full threat model behind [DISCLAIMER.md](DISCLAIMER.md)
- [Contributing](wiki/Contributing.md) — dev setup, testing, release process

## Contributing

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install
pytest
```

Unit tests run against synthetic, PII-free fixtures (`tests/fixtures/`) — never against real captures. Live integration tests (`tests/live/`) are opt-in (`SFB_LIVE_TESTS=1`) and never run in CI. See the design doc in this repo's history for the full architecture and the reasoning behind each guardrail.

## License

MIT — see [LICENSE](LICENSE). The license covers the code; it does not cover what you do with the data you collect (see [DISCLAIMER.md](DISCLAIMER.md)).
