# Contributing

Where the contributor guide lives — for anyone planning to open an issue or a pull request.

**The authoritative guide is [CONTRIBUTING.md](../../CONTRIBUTING.md) in the repository root.** This page is only a pointer to it, so the two can never drift apart.

The split exists because GitHub surfaces the root `CONTRIBUTING.md` automatically in its issue and pull-request UI, while this wiki page is where someone reading the docs would look — so the root file holds the content and this one holds the link.

There you will find:

- **Dev environment setup** — an editable install with `.[dev]`, and `pre-commit`.
- **Running the tests** — unit tests against synthetic, PII-free fixtures in `tests/fixtures/`, never real captures; live integration tests in `tests/live/` are opt-in via `SFB_LIVE_TESTS=1` and never run in CI.
- **What CI enforces** — `ruff check`, `ruff format --check`, a fixture PII/secret scan, and `pytest`, on macOS and Ubuntu, plus a wheel-install smoke test.
- **The guardrails you must not weaken** — the pacing floors and the no-crawler design are load-bearing, not preferences.
- **How releases are cut** — versioning, the changelog, and publishing.

Before contributing anything, read [../../DISCLAIMER.md](../../DISCLAIMER.md): the account-ban and third-party-PII risks shape what changes are acceptable here.

---

**Next:** [CONTRIBUTING.md](../../CONTRIBUTING.md) for the real thing, and [Architecture](Architecture.md) for how the pieces fit together before you change one. Back to the [wiki index](README.md).
