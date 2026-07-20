# scraper-for-facebook wiki

`scrape-fb` scrapes posts from a **logged-in personal Facebook timeline** by observing the GraphQL responses your own browser session already makes — no Graph API, no token replay, no credential injection. You log in once by hand in a real browser; the tool just reads what comes back.

> **Read [../DISCLAIMER.md](../DISCLAIMER.md) before you use this.** Automating a Facebook account violates its Terms of Service, publishing this tool exposes its maintainer, and scraping other people's posts can make *you* a data controller over their personal data. Use a dedicated/throwaway account, not your primary one.

## Getting started

- [Installation](Installation.md) — platform notes, upgrading, uninstalling
- [Quick Start](Quick-Start.md) — logging in, running your first fetch, reading the output

## Reference

- [CLI Reference](CLI-Reference.md) — every subcommand, every flag, every exit code
- [Python API Reference](Python-API-Reference.md) — `FacebookScraper`, exceptions, usage inside your own code
- [Output Schema](Output-Schema.md) — every `Post` / `Media` / `LinkAttachment` field explained
- [Configuration](Configuration.md) — login profiles, environment variables, tuning scroll pacing
- [FAQ and Troubleshooting](FAQ-and-Troubleshooting.md) — common errors, exit codes, "why did it stop early"
- [Security and Privacy](Security-and-Privacy.md) — the full threat model behind [../DISCLAIMER.md](../DISCLAIMER.md)

## Project

- [Contributing](Contributing.md) — dev setup, running tests, release process

## Elsewhere

- [Main README](../README.md)
- [PyPI package](https://pypi.org/project/scraper-for-facebook/)
