# Contributing

Thanks for considering a contribution to `agentic-facebook`.

This is a small, single-maintainer project. There is no CLA, no template gauntlet, and no review board — an issue or a pull request is enough. In exchange, please keep changes focused and read the two documents that shape what is acceptable here:

- **[DISCLAIMER.md](DISCLAIMER.md)** — the account-ban risk, the maintainer-exposure risk, and the third-party personal-data risk. These are not disclaimers bolted on after the fact; they are why several parts of the design look the way they do.
- **[CLAUDE.md](CLAUDE.md)** — the repository's own engineering guidelines: minimum code that solves the problem, surgical changes, no speculative abstraction, no configurability that nobody asked for. It was written for AI coding assistants, but it describes the standard human patches are held to as well. Please skim it before writing anything substantial.

**Scope.** This tool reads *your own* logged-in Facebook session. Contributions that push it toward mass collection are out of scope: anything that weakens or makes bypassable the pacing floors (≥ 1.0s between active requests, ≥ 0.5s between scrolls), anything that adds credential injection or foreign-token replay, and anything that turns it into a general crawler. Those floors are enforced in code rather than requested in prose on purpose — that is the property that keeps this a personal-scale tool.

## Ways to contribute

- **Bug reports** — especially the "Facebook changed something" class, where a `doc_id` rotated or a response shape moved and the parser now returns empty or partial results.
- **Parser fixes** — when a field stops being extracted correctly.
- **New primitives** that fit the existing composable model (a command whose output is the same contract `fetch` emits).
- **Documentation** — `README.md`, `docs/wiki/`, and the `--help` strings. Note that `agentic-facebook catalog` and `agentic-facebook schema` are *derived* from the live parser and the real `to_dict()` output, not authored by hand; fix the source, not a transcription of it.
- **Tests** — particularly around parser edge cases, using synthetic fixtures (see the rule below).

## Development setup

Requires **Python 3.11 or newer**. macOS is the first-class, tested target; the fixture, parse, and CLI layers are browser-agnostic and are exercised on Linux in CI too.

```bash
git clone https://github.com/tjdwls101010/Agentic-Facebook.git
cd Agentic-Facebook

uv venv
uv pip install -e ".[dev]"
```

(`python -m venv .venv && pip install -e ".[dev]"` works identically if you would rather not use `uv`.)

The `dev` extra pulls `pytest`, `ruff`, `pre-commit`, and `build`. There is also an optional `chrome` extra, which pulls `cryptography` — it is needed only for the opt-in `agentic-facebook login --from-chrome` path, and is deliberately kept out of the base install so the common path stays dependency-light:

```bash
uv pip install -e ".[dev,chrome]"
```

Then install the git hooks:

```bash
pre-commit install
```

Running the browser transport for real additionally needs a Chromium binary, which `agentic-facebook setup` installs. You do **not** need it to run the unit tests.

## Tests and checks

**Unit tests** — fast, offline, no network and no browser. They run entirely against the synthetic fixtures in `tests/fixtures/`:

```bash
python -m pytest -q tests --ignore=tests/live
```

That is 145 tests and takes well under a second. This is the suite to run constantly while working.

**Live tests** — opt-in, and they are exactly what they sound like: they hit real Facebook with a real logged-in session, so they need a **throwaway account** you are willing to lose, logged in via `agentic-facebook login`. They assert shapes and invariants only, never specific content, because the account's timeline changes and asserting on real posts would bake third-party personal data into the repo.

```bash
SFB_LIVE_TESTS=1 python -m pytest tests/live -v
```

Without `SFB_LIVE_TESTS=1` they skip themselves, which is why they **never run in CI** even though CI invokes plain `pytest` over the whole `tests/` tree. Do not add a live test that runs unconditionally, and do not remove the env gate.

**Lint and format** — `ruff`, line length 100:

```bash
ruff check src tests
ruff format src tests
```

**Pre-commit** runs `ruff` (with `--fix`), `ruff-format`, and the fixture PII scan. You can run the whole set manually:

```bash
pre-commit run --all-files
```

**What CI enforces** on every pull request, on both macOS and Ubuntu: `ruff check .`, `ruff format --check .`, `python scripts/check_fixtures_pii.py`, and `pytest`. A separate `build-and-smoke` job builds the wheel, installs it into a clean virtualenv, and runs `agentic-facebook --version`, `--help`, and `schema` — that job exists to catch a broken entry point or a missing runtime dependency, which the fixture tests cannot see. Get all of it green locally before opening a PR.

## Never commit captured Facebook data

**This is the one rule in this repository that matters more than the others.**

A raw capture is not test data. It is third-party personal data: real people's names, the full text of their comments, their profile URLs, and signed media URLs. Those people did not consent to appearing in a public git repository, and once a capture is committed it is in the history permanently — deleting the file later does not remove it. Committing one would also make the repository itself a privacy incident, which is a far worse outcome than a missing test case.

So: **every fixture under `tests/fixtures/` must be hand-authored synthetic data, or a skeletonized and scrubbed structure with all real values replaced.** Never a mutated real capture — mutating a capture reliably leaves something behind.

Three mechanisms back this up, and you should understand all three:

1. **`.gitignore` blanket-ignores `*.json`, `*.ndjson`, and `*.jsonl`**, plus `scratch/`, `*.raw.ndjson`, and `profiles/`. The default state of any capture file is "cannot be committed."

2. **Committed fixtures are un-ignored by explicit filename**, one line each — deliberately *not* a wildcard like `!tests/fixtures/*.ndjson`, because a wildcard would silently re-include any new `.ndjson` dropped into that directory and defeat the blanket ignore entirely. **This means adding a new fixture requires adding its filename to `.gitignore` in the same commit.** If `git add` seems to ignore your new fixture, that is the mechanism working, not a bug.

3. **`scripts/check_fixtures_pii.py`** runs in pre-commit and in CI as a backstop. Read its limitations honestly: it is **structural only**. It matches real `fbcdn`/`scontent` CDN hosts, token-shaped keys (`fb_dtsg`, `c_user`, `xs`, …), email and phone shapes, and high-entropy token-shaped strings. It has **no detector for free-text personal data** — a real person's actual name, or real message content, in a line with no token, email, phone, CDN host, or high-entropy string, passes this gate silently. The script is a seatbelt, not a certification. **Human review is the actual control**, so every fixture diff gets read by eye before merge, including yours.

`scripts/record_fixture.py` exists to capture real GraphQL bodies when the parser needs re-anchoring after a Facebook response-shape change. It writes to the gitignored `scratch/` directory as `*.raw.ndjson`. That output is a real capture: derive a synthetic skeleton from it, commit the skeleton, and delete the capture.

The same instinct applies outside `tests/` — do not paste raw captures into issues, pull-request descriptions, or commit messages. If you need to show a response shape, redact it or reconstruct it synthetically.

## Making a change

1. **Open an issue first for anything non-trivial.** A quick sketch of the approach saves both of us a rewrite — especially for parser changes, where the maintainer may already know why a field is extracted the way it is.
2. **Branch off `main`.** Any reasonable branch name is fine.
3. **Keep the diff small and traceable.** Per `CLAUDE.md`: every changed line should trace directly to the stated goal. Don't reformat adjacent code, don't refactor what isn't broken, don't add abstraction for a single call site. If you spot unrelated dead code, mention it in the PR rather than deleting it.
4. **Add a test.** For a bug fix, the ideal shape is a test that reproduces the bug first, then the fix that makes it pass. For a parser fix, that usually means a new synthetic fixture — and its `.gitignore` line.
5. **Run lint, format, and the unit suite** before pushing.
6. **Update `CHANGELOG.md`** under `## [Unreleased]`, following the existing Keep a Changelog headings (`Added` / `Changed` / `Fixed`). Do not bump the version in `pyproject.toml` yourself; the maintainer does that when cutting a release.
7. **Open the PR** describing what changed and why, and say explicitly whether you ran the live tests — the maintainer cannot reproduce your session, so your word on that is the only signal.

Behavior changes should also reach the places that describe behavior: the `--help` strings (which are meant to be authoritative standalone), `README.md`, and `docs/wiki/`. `catalog` and `schema` update themselves from the source, so they need no manual edit.

## Code style

- **`ruff` decides formatting.** Line length 100, target `py311`. Lint rules enabled: `E`, `F`, `I`, `UP`, `B`. If `ruff format` disagrees with you, `ruff format` wins.
- **Match the surrounding code.** This codebase has a consistent voice; a patch written in a different one costs review time.
- **Comments explain *why*, not *what*.** The existing comments are unusually load-bearing — they record why a floor is non-bypassable, why a `.gitignore` un-ignore is enumerated rather than globbed, why a workflow is pinned to a commit. Preserve that habit and don't strip those comments while editing nearby code.
- **Type hints on public functions**, with `from __future__ import annotations` as the file header, as elsewhere in the codebase.
- **Prefer the simplest thing that works.** If it came out at 200 lines and it could be 50, rewrite it.

## Reporting bugs and requesting features

Use the [issue tracker](https://github.com/tjdwls101010/Agentic-Facebook/issues).

For a **bug**, please include:

- `agentic-facebook --version`, your Python version, and your OS.
- The exact command you ran, and the exit code.
- Output from a `-v`/`--verbose` run. Verbose output is passed through a redaction path that strips signed media URLs and token-shaped fields and truncates message text — but that path is a risk reduction, not a guarantee, so **read what you are about to paste** and remove anything about a real person. Never paste an `--output` file: those are the full, unredacted capture by design.
- What you expected, and what happened instead.

If the tool suddenly returns zero or partial results and it worked yesterday, that is very likely a `doc_id` rotation or a response-shape change on Facebook's side. Say so in the report — it points straight at the parser and its fixtures.

For a **feature**, describe the use case rather than the implementation, and check it against the scope note at the top: personal-scale reading of your own session, composable primitives, no mass collection. A "please make it faster by removing the request interval" request will be declined, and the reasoning is in DISCLAIMER §1.

**Security vulnerabilities do not belong in the issue tracker.** See [SECURITY.md](SECURITY.md) for the private reporting channel.

## Code of Conduct

This project follows the Contributor Covenant v2.1. By participating you are expected to uphold it — please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Reports are handled through the same private channel described in [SECURITY.md](SECURITY.md).
