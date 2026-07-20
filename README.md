<p align="center">
  <img src="https://raw.githubusercontent.com/tjdwls101010/tjdwls101010/refs/heads/main/Images/scraper%20for%20facebook.png" alt="scraper-for-facebook" width="640">
</p>

<h1 align="center">scraper-for-facebook</h1>

<p align="center">
  Read your own logged-in Facebook — timelines, feed, comments, search, groups — into clean JSON.
</p>

<p align="center">
  <a href="https://pypi.org/project/scraper-for-facebook/"><img src="https://img.shields.io/pypi/v/scraper-for-facebook.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/scraper-for-facebook/"><img src="https://img.shields.io/pypi/pyversions/scraper-for-facebook.svg" alt="Python versions"></a>
  <a href="https://github.com/tjdwls101010/Scraper-for-Facebook/actions/workflows/ci.yml"><img src="https://github.com/tjdwls101010/Scraper-for-Facebook/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

---

Facebook has no usable API for reading your own feed. The Graph API was closed to this years ago, and what remains needs app review for permissions it will not grant an individual. The usual workaround — automating a browser and scraping rendered HTML — is slow and breaks with every layout change.

`scrape-fb` takes a different route. Facebook's own web client gets its data from a single GraphQL endpoint; this reads that same endpoint using the session **your own browser already has**. You log in once, by hand, in a real browser. After that the tool stores no password, injects no credentials, and replays nobody else's token — it makes the request your browser would have made.

> **Read [DISCLAIMER.md](DISCLAIMER.md) before using this.** Automating a Facebook account violates its Terms of Service, publishing this tool exposes its maintainer, and scraping other people's posts can make *you* a data controller over their personal data. Use a dedicated/throwaway account, not your primary one.

**This is not the first tool that does this.** [`facebook-graphql-scraper`](https://pypi.org/project/facebook-graphql-scraper/) captures GraphQL responses via Selenium + `selenium-wire` with credential-based login. This project's difference is one of degree: it reuses a **persisted browser-login profile** instead of injecting a username/password, builds on [scrapling](https://github.com/D4Vinci/Scrapling)'s actively-maintained fetch stack instead of the largely-unmaintained `selenium-wire`, and since v0.3.0 reads the GraphQL API over plain HTTP with no browser in the hot path at all.

## Features

- **Six composable primitives** — `fetch` (a timeline), `feed`, `comments`, `post`, `search`, `group`. Every post carries `url`, `author_url`, and `author_id`, so one command's output is the next one's input.
- **Fast path by default** — reads GraphQL over plain HTTP with no browser in the loop, falling back to a real browser automatically when that fails.
- **Precise date filtering** — `--since`/`--until` are a server-side filter, not scroll-until-you-see-it.
- **Documented output** — `Post`, `Comment` and `Entity`, as JSON or NDJSON.
- **Self-describing** — `scrape-fb catalog` prints every command, flag, exit code and object type, generated from the code itself, so it cannot go stale.
- **Non-bypassable pacing floors** — clamped in code, not asked for in prose. This is what keeps it a personal tool rather than a mass-scraper.

## Quick start

Requires Python 3.11+. Install into an **isolated** environment — this package pins exact Playwright versions through `scrapling`, so sharing a virtualenv with another Playwright-based tool will break one of them:

```bash
uv tool install scraper-for-facebook     # or: pipx install scraper-for-facebook
scrape-fb setup                          # one-time: provisions its own browser
scrape-fb login                          # opens a real browser — log in by hand
scrape-fb status                         # exit 0 = ready
```

Then fetch something. **Results are written to a JSON file** — only a one-line summary goes to stderr — so pass `--output` and read the file:

```bash
scrape-fb fetch someone.profile --limit 20 --output posts.json
scrape-fb feed --limit 10 --output feed.json
scrape-fb comments "https://www.facebook.com/someone/posts/pfbid02example" --limit 50 --output comments.json
scrape-fb search "seoul" --type groups --limit 10 --output groups.json
```

## Usage overview

Each command does one thing; chaining them is where the value is. A post's `url` feeds `comments`; any `author_url` feeds `fetch`; a group entity's `id` feeds `group`. There is deliberately **no `crawl` command** — how deep to go is a judgment for the caller, not a flag.

```bash
# who engaged with this post, and what else do they post about?
scrape-fb comments "<post-url>" --limit 20 --output c.json
#   → read c.json, collect distinct author_url, then:
scrape-fb fetch "<author_url>" --limit 5 --output person.json
```

See [Chaining Recipes](docs/wiki/Chaining-Recipes.md) for worked multi-hop examples, and run `scrape-fb catalog` for the authoritative command surface of the version you have installed.

## Example output

```json
{
  "id": "ZmVlZGJhY2s6MTIzNDU2Nzg5MDEyMzQ1",
  "url": "https://www.facebook.com/some.profile/posts/pfbid02example",
  "type": "status",
  "author_name": "Jane Example",
  "author_url": "https://www.facebook.com/some.profile",
  "author_id": "100000000000001",
  "created_at": "2026-06-30T09:15:36Z",
  "text": "Full post body, truncation-resolved if it was ever cut short...",
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

`source` (`timeline` | `newsfeed` | `group` | `search`) means merged results from several commands stay self-describing. Full field reference: [Output Schema](docs/wiki/Output-Schema.md), or `scrape-fb schema`.

## Documentation

**[Full documentation lives in `docs/wiki/`](docs/wiki/README.md)** — installation, quick start, architecture, chaining recipes, the complete CLI and Python API references, configuration, troubleshooting, and the security and privacy posture.

## Project status

Alpha, pre-1.0, single maintainer. macOS is the tested, first-class platform; Linux likely works for the fetch/parse/CLI layer but is untested against a live session; Windows is unsupported. The output schema is additive-only — new fields are a minor bump; reinterpreting an existing one would be breaking.

Because it depends on Facebook's private GraphQL API, it will break when Facebook ships client changes. `fetch` falls back to a browser when that happens; the other commands need a package update. See [FAQ and Troubleshooting](docs/wiki/FAQ-and-Troubleshooting.md).

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). One rule matters more than the rest: **never commit captured Facebook data**, including as a test fixture.

## License

MIT — see [LICENSE](LICENSE).
