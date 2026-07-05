# scraper-for-facebook

[![PyPI](https://img.shields.io/pypi/v/scraper-for-facebook.svg)](https://pypi.org/project/scraper-for-facebook/)
[![Python versions](https://img.shields.io/pypi/pyversions/scraper-for-facebook.svg)](https://pypi.org/project/scraper-for-facebook/)
[![CI](https://github.com/tjdwls101010/Scraper-for-Facebook/actions/workflows/ci.yml/badge.svg)](https://github.com/tjdwls101010/Scraper-for-Facebook/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Scrape posts from a **logged-in personal Facebook timeline** by observing the GraphQL responses your own browser session makes — no token replay, no credential injection. You log in once by hand; the browser generates its own `fb_dtsg`/`doc_id`/`lsd`, and this tool just reads what comes back.

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
- [Limitations (v1)](#limitations-v1)
- [Python API](#python-api)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **No Graph API, no app review, no credential injection** — reuses your own persisted, logged-in browser profile.
- Retrieval by count (`--limit`) or date window (`--since`/`--until`), with honest reporting of whether the requested window was actually reached (never silently reports a partial run as complete).
- Full post schema: body text (truncation-resolved), media and link attachments, reaction/comment/share counts, pinned flag, edited time, and one level of shared/quoted posts.
- JSON or NDJSON output, plus a typed Python API (`FacebookScraper`) for programmatic use.
- One **non-bypassable** floor on scroll pacing — the one hard limit that keeps this from being usable as a mass-scraping tool, enforced in code, not just asked for in prose.

## How it works

`scrape-fb` never calls Facebook's Graph API and never replays a token. It drives a real, logged-in Chromium session (via [Playwright](https://playwright.dev/)) against your own persisted profile, scrolls a target timeline, and reads the same `/api/graphql/` responses your browser already receives — then parses posts out of that JSON. Because the browser generates its own `fb_dtsg`/`doc_id`/`lsd` values on every request, there's no token to steal, maintain, or refresh; the tradeoff is that this only sees what your logged-in account can already see, and it degrades whenever Facebook's response shape changes (see [Limitations](#limitations-v1)).

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
```

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
  "captured_at": "2026-07-05T03:18:13.385206Z"
}
```

See [Output Schema](wiki/Output-Schema.md) for a field-by-field reference, including `media`/`links`/`shared_post` shapes.

## CLI reference

```
scrape-fb --version
scrape-fb login   [--profile NAME] [--profile-dir PATH]
scrape-fb status  [--profile NAME] [--profile-dir PATH] [--json]
scrape-fb setup
scrape-fb doctor  [--profile NAME] [--profile-dir PATH]
scrape-fb fetch <profile_url_or_username>
    --profile NAME            persisted login profile (default: "default")
    --limit N                 max posts
    --since YYYY-MM-DD        lower date bound (inclusive), best-effort (see "Limitations" below)
    --until YYYY-MM-DD        upper date bound (inclusive)
    --format json|ndjson      default: json
    --output PATH             default: a non-repo path under this tool's data directory
    --scroll-pause MIN,MAX    seconds between scrolls; MIN is clamped to >= 0.5 (see "Guardrails")
    --max-scrolls N           scroll budget (default 40)
    --profile-dir PATH        override where the login profile is stored
    --headed                  show the browser (debugging)
    --raw                     include the raw captured story node per post (debug; contains PII).
                              Redacted (scrubbed) by default — combine with --no-redact for the
                              truly raw, unscrubbed node (prints an on-screen PII warning).
    --no-redact               disable redaction of --raw output (only has an effect with --raw)
    -v / --verbose            extra diagnostics (redaction-scrubbed by default)
```

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

- The scroll-pause floor (`--scroll-pause`) is clamped to **≥ 0.5s and cannot be set to 0** — this is the one non-bypassable limit in this tool, and it exists both to reduce your account's checkpoint/ban risk and to keep this from being usable as a mass-scraping tool.
- One target profile per invocation; no batch/multi-profile mode; no built-in scheduler or daemon loop.
- Deeper `--since` runs scroll more, and more scrolling raises checkpoint risk. If you value the account, prefer shallow/recent fetches and `--headed` runs over deep history.

## Limitations (v1)

- Facebook only — no Instagram, no Threads (see roadmap).
- Personal-profile timeline posts only — no groups, pages, or photo albums.
- `--since` is **best-effort**: because this tool observes pagination rather than driving it, Facebook can stall further pagination before your requested date is reached. Exit code `7` and the stderr summary tell you when that happened.
- Media is captured as URLs only (no file download) — and those URLs are signed, expire, and are scoped to your viewing session; treat them as sensitive.
- No guaranteed deep-history reach; no incremental `--since-last` state (yet).

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
