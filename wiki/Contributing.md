# Contributing

Thanks for considering it. This is a solo-maintained, personal-scale tool, so the bar for contributions is less "does this scale" and more "is this correct, and does it not make the account-ban/PII risk in [../DISCLAIMER.md](../DISCLAIMER.md) worse."

## Dev environment setup

```bash
git clone https://github.com/tjdwls101010/Scraper-for-Facebook.git
cd Scraper-for-Facebook
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install
```

`.[dev]` pulls in `pytest`, `ruff`, `pre-commit`, and `build` (see `pyproject.toml`'s `[project.optional-dependencies]`). It does **not** install a browser — you only need `scrape-fb setup` (see [Installation](Installation.md)) if you're going to run live integration tests or `scripts/record_fixture.py` against a real, logged-in profile. Everything else (unit tests, lint, the fixture scan) runs against synthetic fixtures and needs no browser at all.

`pre-commit install` wires up the hooks in `.pre-commit-config.yaml` so lint/format/PII issues get caught locally, before CI does:

- `ruff` (`--fix`) and `ruff-format`, against every file.
- A local `fixture-pii-scan` hook, scoped to `tests/fixtures/*.ndjson`, that runs `scripts/check_fixtures_pii.py` (see below).

## Running tests

```bash
pytest
```

That's it — no flags, no environment variables, no browser. Tests run against the fixtures in `tests/fixtures/*.ndjson`.

### Why fixtures are synthetic, not real captures

Every `.ndjson` file in `tests/fixtures/` is **hand-authored** — a synthetic skeleton built to exercise a specific shape the parser needs to handle (a plain status post, a pinned post next to a decoy, a shared/quoted post, a truncated body that needs resolving, a `@defer`/`@stream` split response that needs merging, and so on). None of them are a real Facebook capture with names swapped out. That distinction matters mechanically, not just ethically: `parse.py`'s module docstring documents that its field paths (`creation_time`, `permalink_url`/`wwwURL`, `message.text`, the `interesting_top_level_comments` trap, etc.) were confirmed by probing a real, logged-in session and reading what actually came back — the fixtures encode the *shapes* that probing discovered, as inert synthetic data, so the test suite can pin those shapes down without ever holding onto a real capture. If a fixture were "real data with the names changed," it would still contain whatever else was inline in that response — other people's names, message text, signed media URLs — which is exactly what [DISCLAIMER.md](../DISCLAIMER.md) says you should never casually hold onto.

When you add a new fixture, remember to add its exact filename to the `!tests/fixtures/...` allowlist in `.gitignore` — the ignore rules there deliberately don't wildcard-un-ignore `tests/fixtures/*.ndjson`, so a new fixture is invisible to git (and silently skipped by tests) until you add it by name.

### The fixture PII/secret scan

```bash
python scripts/check_fixtures_pii.py
```

This runs automatically in the pre-commit hook and in CI, scoped to every `tests/fixtures/*.ndjson` file. It's a coarse, allowlist-based gate that flags lines matching:

- a real `fbcdn.net`/`scontent-*.fbcdn.net`/`fbstatic-a.akamaihd.net` CDN host
- a token-shaped cookie/auth key (`fb_dtsg`, `lsd`, `jazoest`, `datr`, `sb`, `c_user`, `xs`)
- an email-shaped string
- a phone-shaped string
- a high-entropy (Shannon entropy ≥ 4.0), 40+ character base64/hex-ish run — the shape of a real signed token

**Its own docstring states the honest limitation plainly:** this has no detector for free-text PII. A real person's actual name, or sensitive message content, with none of the patterns above anywhere on the line, passes this scan silently. It exists to catch structural artifacts of a real capture leaking in by accident — not to certify a fixture is safe. **Human review of every fixture diff is still required** before merge; if you're adding or changing a fixture, read the whole diff yourself and make sure nothing in it reads like it came from an actual profile.

If the scan flags something you're confident is a deliberately-fake placeholder (e.g. a made-up-but-plausible-looking token string), don't disable the check — change the fixture to use a more obviously-fake value instead.

### Live integration tests

```bash
SFB_LIVE_TESTS=1 pytest tests/live/
```

`tests/live/` is reserved for tests that run against your own real, logged-in Facebook session (via `scrape-fb login`) instead of static fixtures — the only way to catch a live response-shape change that the synthetic fixtures, by construction, can't reproduce. The convention (see the README) is that anything added here is opt-in via the `SFB_LIVE_TESTS=1` environment variable and **never runs in CI** — CI has no logged-in profile to run against, and even if it did, running live Facebook traffic automatically and repeatedly would be exactly the kind of automated, unattended access this project is trying not to encourage (see [../DISCLAIMER.md §1](../DISCLAIMER.md)). If you're adding a live test, gate it behind that environment variable and keep it out of the default `pytest` run and out of CI. Only run these locally, against your own account, when you're deliberately checking something.

## Re-anchoring the parser after a Facebook response-shape change

Facebook's internal GraphQL response shape isn't a stable contract — see [Limitations (v1)](../README.md#limitations-v1) and the parser durability notes. When `fetch` starts returning zero posts or missing fields on a shape it used to handle, you'll want a real capture to work from:

```bash
python scripts/record_fixture.py <profile_url_or_username> --profile default --limit 10
```

This logs in via your existing profile (from `scrape-fb login`), drives a real scroll, and writes the raw captured GraphQL response bodies to `scratch/<name>.raw.ndjson`. **Never commit anything under `scratch/`** — it's gitignored specifically because it's real, unscrubbed data (other people's names, message text, signed URLs), the exact thing [DISCLAIMER.md](../DISCLAIMER.md) warns about. Use it locally to see what actually changed, then hand-author a new synthetic fixture (or edit an existing one) that reproduces just the shape that broke — never derive a committed fixture by lightly editing the scratch output.

## CI

Every push to `main` and every pull request runs `.github/workflows/ci.yml`, on both `macos-latest` and `ubuntu-latest` (neither leg installs an actual browser binary):

1. Install pinned dev dependencies from `requirements-dev.lock`, then install the package itself with `--no-deps` (dependencies are already pinned).
2. `ruff check .`
3. `ruff format --check .`
4. `python scripts/check_fixtures_pii.py`
5. `pytest`

A separate `build-and-smoke` job (same OS matrix) builds a wheel, installs it into a clean venv with `scrapling` as a real dependency but **no** browser binary provisioned, and runs `scrape-fb --version` / `scrape-fb --help` against it — catching a broken entry point or an import that only fails once `scrapling` is genuinely installed, which the fixture-based tests above can't see.

Nothing in CI touches a live Facebook session; nothing in CI can, since there's no logged-in profile available there.

## Release process

Releases are the one part of this workflow where getting the order wrong actually breaks things. Follow this exactly:

1. **Bump the version and changelog.** Edit `version` in `pyproject.toml`, and add a dated entry to `CHANGELOG.md` under a new heading (see the existing `[0.1.0] - 2026-07-05` entry for the format — this project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/)).
2. **Commit and push to `main`.**
3. **Create and publish a GitHub Release** for a tag matching the new version exactly (`vX.Y.Z`, e.g. `v0.2.0` for `pyproject.toml`'s `0.2.0`) — either through the GitHub web UI ("Releases" → "Draft a new release" → pick or create the tag → "Publish release") or with the CLI:

   ```bash
   gh release create v0.2.0
   ```

**Publishing the Release is what triggers the build** — `.github/workflows/publish.yml` fires on the `release: published` event, not on a bare `git push --tags`. Pushing a tag without turning it into a published Release does nothing; the workflow never sees it.

Once triggered, the workflow:

1. Runs `scripts/check_tag_version.py "<tag>"`, which parses `pyproject.toml` and fails the whole run immediately, loudly, if the tag doesn't match — before any build or upload happens. There's no silent partial-publish path; a mismatch is a hard CI failure with an explicit `::error::tag 'vX.Y.Z' does not match pyproject.toml version 'A.B.C'` message.
2. Builds the sdist and wheel (`python -m build`) and uploads them as a workflow artifact.
3. Publishes to PyPI via [`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish), pinned to a specific commit SHA (not a floating version tag) since it runs with publish credentials.

Publishing uses **PyPI Trusted Publishing (OIDC)** — the `publish` job requests `id-token: write` permission and mints a short-lived OIDC token itself. **There is no stored PyPI API token anywhere in this repo**, in any secret or workflow file. If you're setting up a fork or a new maintainer account, configure Trusted Publishing on the PyPI project settings side (linking this GitHub repo and the `publish.yml` workflow), not by adding a token.

If you get the version bump wrong (forgot to bump it, or the tag doesn't match), the workflow fails at step 1 above and nothing gets uploaded — fix `pyproject.toml`/the tag and try the Release again.

---

Questions before you send a PR are welcome — open an issue. See [the wiki index](README.md) for the rest of the wiki, or [../README.md](../README.md) for the project overview.
