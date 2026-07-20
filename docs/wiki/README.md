# scraper-for-facebook — documentation

Full documentation for `scrape-fb`, a command-line tool that reads **your own logged-in Facebook** into clean JSON. The [repository README](../../README.md) is the short version; this is the complete one.

> **Read [DISCLAIMER.md](../../DISCLAIMER.md) before you use this.** Automating a Facebook account violates its Terms of Service, publishing this tool exposes its maintainer, and scraping other people's posts can make *you* a data controller over their personal data. Use a dedicated or throwaway account, never your primary one.

## What it is, and why it exists

Facebook has no usable API for reading your own feed. The Graph API was closed to this years ago, and what remains requires app review for permissions it will not grant an individual. The practical alternative has been browser automation that scrapes rendered HTML — slow, and broken by every layout change.

This tool takes a different route. Facebook's own web client gets its data from a single GraphQL endpoint; `scrape-fb` reads that same endpoint using the session **your own browser already has**. You log in once, by hand, in a real browser. After that the tool stores no password, injects no credentials, and replays nobody else's token — it makes the request your browser would have made.

What that buys you: a **profile timeline, your home feed, a post's comments, search results, or a group's feed**, each as a documented JSON object, and fast enough to chain several together to answer questions no single query answers — *what is this person's circle discussing, who engaged with this post and what else do they post about, which groups on this topic are actually alive.*

**What it deliberately is not.** Not a mass-scraping tool: two rate floors are clamped in code where no flag can reach them. Not a crawler: there is no `crawl` command, because how deep to go is a judgment the caller should make. Not multi-platform, not a scheduler, and not something to point at an account you would mind losing.

## Start here

New to the project: [Installation](Installation.md) → [Quick Start](Quick-Start.md). That gets you a JSON file of real posts.

## All pages

| Page | What's in it |
|---|---|
| [Installation](Installation.md) | Prerequisites, install methods, `setup`, platform support, upgrading |
| [Quick Start](Quick-Start.md) | Zero to a first real result, with worked examples |
| [Architecture](Architecture.md) | How it works: active vs passive transports, the vocabulary, the module map |
| [Chaining Recipes](Chaining-Recipes.md) | Feeding one command's output into the next for multi-hop questions |
| [CLI Reference](CLI-Reference.md) | Every command and flag, with the exit-code contract |
| [Configuration](Configuration.md) | Every knob, its default and effect; where data is stored |
| [Output Schema](Output-Schema.md) | `Post`, `Comment`, and `Entity`, field by field |
| [Python API Reference](Python-API-Reference.md) | The `FacebookScraper` library surface (profile timelines only) |
| [FAQ and Troubleshooting](FAQ-and-Troubleshooting.md) | Recurring questions, and failures mapped to fixes |
| [Security and Privacy](Security-and-Privacy.md) | Session credentials, third-party data, your obligations |
| [Contributing](Contributing.md) | Pointer to the contribution guide |

## Two things to know before reading anything else

**Results go to a file.** Every retrieval command writes JSON to disk and prints only a one-line summary to stderr — nothing useful reaches stdout. Pass `--output <path>`, then read that file.

**The CLI describes itself.** `scrape-fb catalog` prints every command, flag, exit code and object type, generated from the code of the version you actually have installed. Where these pages and that output disagree, the output is right and these pages are stale — please [open an issue](https://github.com/tjdwls101010/Scraper-for-Facebook/issues).

## Elsewhere

- [Main README](../../README.md) · [CHANGELOG](../../CHANGELOG.md) · [DISCLAIMER](../../DISCLAIMER.md)
- [PyPI package](https://pypi.org/project/scraper-for-facebook/)

---

**Next:** [Installation](Installation.md)
