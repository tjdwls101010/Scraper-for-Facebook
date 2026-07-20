# CLI Reference

The complete, flag-by-flag reference for `scrape-fb`. The [README](../README.md) has a condensed version of this; this page is the authoritative one — every default and every exit code here is read directly out of `build_parser()` and `_cmd_fetch` in `src/scraper_for_facebook/cli.py`, not copied from memory.

If you haven't run either of these yet, do them in this order first: [Installation](Installation.md), then `scrape-fb setup`, then `scrape-fb login`.

## Global

```
scrape-fb --version
```

Prints `scrape-fb <version>` and exits 0. This is the only thing you can do without a subcommand — `scrape-fb` with no arguments (or an unrecognized one) is a usage error (see [Exit codes](#exit-codes) below).

Every subcommand below also accepts `-h`/`--help`.

## `login`

One-time interactive login. Opens a real, visible Chromium window (via Playwright) so you can log in to Facebook by hand — including any 2FA challenge Facebook throws at you. The tool then prints `Log in to Facebook there, then press Enter here to continue...` and waits; once you press Enter, it checks whether the page still looks like a login wall, and if not, persists the session — cookies and local storage — to disk under the named profile.

You only need to do this once per profile, and again whenever [`status`](#status) reports the session has expired or been checkpointed.

| Flag | Default | Meaning |
|---|---|---|
| `--profile NAME` | `default` | Name of the login profile to create/overwrite. |
| `--profile-dir PATH` | none (falls back to the platform data dir, or `$SFB_PROFILE_DIR`) | Override where this profile's session is stored on disk. See [Configuration](Configuration.md) for the resolution order. |

**Example:**

```bash
scrape-fb login
```

```
Logged in. Profile saved at /Users/you/Library/Application Support/scraper-for-facebook/profiles/default
```

A second profile, e.g. for a throwaway account kept separate from your main one:

```bash
scrape-fb login --profile burner
```

**Exit codes:** `0` on confirmed login, `2` if the tool still sees a login wall after you pressed Enter (try again), `1` on any other failure (browser crash, permissions error, etc. — the message is printed to stderr).

## `status`

Checks whether a profile's persisted session is still logged in, without opening a visible browser or touching the target timeline. Useful to run before a `fetch` you don't want to fail midway through, or in a script that wants to branch on session health.

| Flag | Default | Meaning |
|---|---|---|
| `--profile NAME` | `default` | Which profile to check. |
| `--profile-dir PATH` | none | Same override as `login`. |
| `--json` | off | Emit a single JSON object to stdout instead of a human-readable line to stderr. |

**Example (human-readable):**

```bash
scrape-fb status
```

```
status: logged_in (logged in 3421s ago)
```

**Example (`--json`, for scripting):**

```bash
scrape-fb status --json
```

```json
{"status": "logged_in", "session_age_seconds": 3421.0}
```

`session_age_seconds` is `null`/omitted-looking (`unknown` in the human form) if the tool can't determine how old the session is — treat that as "don't know," not as "just logged in."

**Exit codes:** `0` = `logged_in`, `2` = `expired`, `3` = `checkpoint`, `1` = the status check itself failed unexpectedly (not the same as the session being expired — see the [exit-code table](#exit-codes) for why these are kept distinct).

## `setup`

Provisions the isolated Playwright browser install this tool uses. This does not touch a login profile or Facebook at all — it just downloads/installs the Chromium build into this package's own cache directory, kept separate from any other tool's Playwright install (see [Configuration](Configuration.md)).

You normally run this exactly once, right after installing the package, before your first `login`.

| Flag | Default | Meaning |
|---|---|---|
| `--force` | off | Reinstall even if a browser is already provisioned. Use this if `doctor` reports a broken install. |

**Example:**

```bash
scrape-fb setup
```

```
Browser provisioned.
```

**Exit codes:** `0` on success, `1` if provisioning fails (network error, disk space, unsupported platform — message on stderr).

## `doctor`

Launches the browser against a profile and verifies the full round trip actually works: browser starts, the profile's session is usable, and a GraphQL capture can be observed and parsed. This is the "is everything actually wired up correctly" check — broader than `status`, which only checks the session, not the capture pipeline.

Run this after `setup` and after `login`, and any time `fetch` behaves strangely and you want to rule out an environment problem before suspecting a Facebook-side change.

| Flag | Default | Meaning |
|---|---|---|
| `--profile NAME` | `default` | Which profile's session to exercise. |
| `--profile-dir PATH` | none | Same override as `login`/`status`. |

**Example:**

```bash
scrape-fb doctor
```

```
OK - captured 3 graphql response(s)
```

If the browser can't even launch or navigate, or navigates but never sees a matching GraphQL response, you'll instead see `browser launch/navigation failed: <error>` or `browser launched and navigated, but no graphql XHR was captured` — either way, exit code `1`. The message is always redaction-scrubbed before printing, per [Security & Privacy](Security-and-Privacy.md).

**Exit codes:** `0` if the round trip succeeds, `1` if any part of it fails.

## `fetch`

The main command: scrape posts from one profile timeline.

```
scrape-fb fetch <identifier> [flags]
```

`<identifier>` is required and positional — a profile URL, a bare vanity name (e.g. `some.profile`), a bare numeric id, or a `profile.php?id=...` path. Anything that isn't one of those shapes, or a URL on a host other than `facebook.com`/`www.facebook.com`/`m.facebook.com`, is rejected before the browser ever opens (exit code `1`, see [Exit codes](#exit-codes)).

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--profile NAME` | `default` | Which login profile's session to use. |
| `--profile-dir PATH` | none | Override where that profile is stored. |
| `--limit N` | none (unbounded) | Stop after this many posts. |
| `--since YYYY-MM-DD` | none | Only keep posts on or after this date. Best-effort — see [`--since` vs `--limit`](#--since-vs---limit-and-exit-code-7) below. |
| `--until YYYY-MM-DD` | none | Only keep posts on or before this date. |
| `--format json\|ndjson` | `json` | Output format. `json` is a single array; `ndjson` is one JSON object per line. |
| `--output PATH` | a generated path under this tool's data directory (see below) | Where to write the result. |
| `--scroll-pause MIN,MAX` | `2.0,4.0` | Random delay range (seconds) between scrolls. See [the floor](#--scroll-pause-and-its-05s-floor) below — this cannot go below 0.5s no matter what you pass. |
| `--max-scrolls N` | `40` | Scroll budget. The run stops once this many scroll iterations happen, regardless of `--limit`/`--since`. |
| `--headed` | off (headless) | Show the browser window while fetching. Useful for debugging what the scroller is actually doing. |
| `--raw` | off | Include the raw captured GraphQL story node on each post, under a `raw` key (and on any nested `shared_post`, recursively). Meant for debugging parser drift — see [`--raw`/`--no-redact`](#--raw-and---no-redact) below. |
| `--no-redact` | off | Only has an effect combined with `--raw`: disables PII scrubbing of the raw node before it's written to the output file. Prints an on-screen warning every time. |
| `-v`, `--verbose` | off | On an unexpected error, print the full (redaction-scrubbed) exception text instead of just the exception type name. |

If `--output` is omitted, the file is written under this package's own data directory (never your current working directory), named `<sanitized-identifier>-<UTC timestamp>.<json|ndjson>` — e.g. `some-profile-20260705T031813385206Z.json`. This is deliberate: captured posts contain other people's personal data, and a default that lands in a repo you might `git add .` in is the wrong default (see [DISCLAIMER.md §4](../DISCLAIMER.md)).

### Example invocations

```bash
# Last 30 posts, defaults everywhere else.
scrape-fb fetch https://www.facebook.com/some.profile --limit 30

# Everything from the last 90 days, as NDJSON, to a specific file.
scrape-fb fetch some.profile --since 2026-04-01 --format ndjson --output ~/fb-export.ndjson

# A numeric-id profile, watching the browser do it.
scrape-fb fetch 100000000000001 --limit 10 --headed

# Debugging a suspected parser issue against a specific post shape.
scrape-fb fetch some.profile --limit 5 --raw -v
```

**Example stderr summary (success):**

```
30 posts, range 2026-04-02..2026-07-04, stop reason: limit_reached. Saved to /Users/you/Library/Application Support/scraper-for-facebook/output/some-profile-20260705T031813385206Z.json
```

**Example stderr summary (`--since` not confirmed reached — see below):**

```
12 posts, range 2026-05-14..2026-07-04, stop reason: max_scrolls (requested --since NOT confirmed reached). Saved to /Users/you/.../some-profile-....json
```

### `--scroll-pause` and its 0.5s floor

`--scroll-pause MIN,MAX` takes two comma-separated numbers, e.g. `--scroll-pause 3,6`. Each scroll waits a random duration in that range before the next one.

The minimum is **clamped to 0.5 seconds and cannot be bypassed** — this is the one hard limit in the whole tool (`clamp_scroll_pause` in `config.py`). Pass `--scroll-pause 0,0` and you'll get:

```
scrape-fb: --scroll-pause 0,0 raised to 0.5,0.5 (minimum is 0.5s)
```

This applies no matter how the value arrives — CLI flag or the Python API — and exists specifically so this can't be turned into a fast mass-scraping tool by just cranking the pacing to zero (see [Guardrails in the README](../README.md#guardrails)).

### `--raw` and `--no-redact`

`--raw` adds the full captured GraphQL story node to each post's output, under `raw` (and recursively on any `shared_post`). It's meant for debugging — e.g. figuring out why a field parsed wrong, or filing an issue about a Facebook response-shape change.

By default, `--raw` output is **redacted before it's written to the output file**: every post's `raw` node (and its `shared_post.raw`, all the way down the chain) is passed through the same scrubbing path used for diagnostics — sensitive keys (`fb_dtsg`, `lsd`, `datr`, `xs`, `access_token`, etc.) are replaced with `[REDACTED]`, free-text fields are truncated, and signed `fbcdn`/`scontent` URLs have their query string (the signing material) stripped.

`--no-redact` disables that scrubbing for the `--raw` node specifically, and prints this every time:

```
WARNING: --no-redact leaves --raw output unscrubbed. The saved file will contain unredacted third-party data. See DISCLAIMER.md.
```

Note this is the reverse of every other redaction path in the tool: normal `-v`/error/diagnostic output is *always* scrubbed with no way to turn it off, but `--raw`'s node is written to the *output file* — which is unredacted by design everywhere else (see [DISCLAIMER.md §5](../DISCLAIMER.md)) — so `--no-redact` exists to let `--raw` opt into that same "fully raw" behavior on purpose, deliberately, with a warning attached. Only use it locally when you specifically need the untouched node; the resulting file is exactly as sensitive as the disclaimer describes.

### `--since` vs `--limit`, and exit code 7

`--limit` and `--since` compose: the fetch stops as soon as either condition is satisfied, whichever triggers first. That "first trigger wins" behavior is exactly why exit code 7 is scoped the way it is.

Internally, `retrieve.py` tracks a stop reason for every run: `limit_reached`, `since_crossed`, `feed_exhausted`, `max_scrolls`, `feed_stalled`, or (a fallback) `unknown_error`. Whether `--since` was actually *confirmed reached* is judged only from `since_crossed`/`feed_exhausted` — deliberately **not** from `limit_reached`, because the scroll loop checks `--limit` before `--since` on every batch. That means a run can hit `--limit` long before scrolling anywhere near the `--since` date — hitting the limit proves nothing about whether `--since` would also have been reached.

The CLI then makes its own, separate judgment call on top of that: hitting `--limit` is still reported as a full, ordinary success (exit `0`), even when `--since` was never independently confirmed — because you got exactly what you asked for (N posts), on purpose, by design. Exit code `7` is reserved for a narrower, genuinely uncertain case: `--since` was requested, but the run stopped for a reason that says nothing about whether that date was reached — `max_scrolls` (ran out of scroll budget) or `feed_stalled` (Facebook stopped returning new posts). In both of those cases the tool honestly doesn't know if it reached your requested date, so it says so instead of guessing.

Concretely:

- `--limit 30` only, feed pagination hits the limit first → stop reason `limit_reached` → **exit 0**.
- `--since 2020-01-01` only, and pagination actually crosses that date or the feed runs dry first → stop reason `since_crossed` or `feed_exhausted` → **exit 0**.
- `--since 2020-01-01` (deep history), but `--max-scrolls` (or a scroll budget default of 40) runs out before getting anywhere near 2020 → stop reason `max_scrolls` → **exit 7**, with `(requested --since NOT confirmed reached)` in the stderr summary.
- `--limit 30 --since 2020-01-01` together, and the limit is hit first (the common case, since `--limit` is checked first) → stop reason `limit_reached` → **exit 0**, even though `--since` was never verified. This is intentional, not a bug — see above.

If you're scripting against this, exit `7` is your signal to either raise `--max-scrolls`, narrow `--since`, or accept the partial result — the stderr line always tells you the actual post count and observed date range either way, so a partial run is never silently indistinguishable from a complete one.

## Exit codes

### `status`

| Code | Meaning |
|---|---|
| 0 | `logged_in` — session is valid. |
| 2 | `expired` — a profile exists but Facebook is showing a login wall. Run `scrape-fb login`. |
| 3 | `checkpoint` — Meta has flagged the session with a security checkpoint. Log in again in a real (headed) browser. |
| 1 | The status check itself failed unexpectedly — not the same as `expired`; something (browser launch, disk read) went wrong before a status could even be determined. |

### `fetch`

| Code | Meaning | Where it comes from |
|---|---|---|
| 0 | Success — `--limit` satisfied, `--since`/`--until` window fully covered, or the feed was genuinely exhausted. | Default, unless the `--since`-inconclusive case below applies. |
| 1 | Invalid identifier, or any other/unexpected error. | `InvalidIdentifierError` on the positional argument, or the catch-all `except Exception` around `retrieve.fetch_profile`. Also: **any argparse usage error** (bad/missing flag, unknown subcommand) — see note below. |
| 2 | Login required or session expired. | `LoginRequiredError` / `SessionExpiredError` from `retrieve.fetch_profile`. Message includes `Run: scrape-fb login --profile <name>`. |
| 3 | Account checkpoint. | `ChallengeError` — Meta flagged the session mid-run. Never retried automatically. |
| 4 | Zero posts retrieved. | `result.posts` is empty. The stderr message distinguishes two cases: if the stop reason is `unknown_error`, it says scrolling was interrupted before any post was captured (rerun with `-v`); otherwise it suggests a possible Facebook response-shape change and links the issue tracker. |
| 5 | Profile unavailable. | `ProfileUnavailableError` — the target is memorialized, blocked, restricted, or doesn't exist. |
| 7 | Partial: `--since` requested but not confirmed reached. | `args.since is not None` and stop reason is `max_scrolls` or `feed_stalled`. See [above](#--since-vs---limit-and-exit-code-7). |

**Argparse usage errors are exit code 1, not argparse's usual 2.** This CLI overrides `argparse.ArgumentParser.error()` (the `_ArgumentParser` class in `cli.py`) specifically so that a typo'd flag or missing required argument exits `1`, not `2` — because exit `2` already has a specific, different meaning in this CLI's contract ("login required or session expired"). Without this override, a script checking `if exit_code == 2: run login` could be fooled by an unrelated CLI typo into thinking the session had expired. So: `scrape-fb fetch` with no identifier, an unknown flag, or `scrape-fb bogus-subcommand` all exit `1`, printing usage to stderr — same code as "other/unexpected error," on purpose.

## See also

- [Quick Start](Quick-Start.md) — a walkthrough of `setup` → `login` → `fetch` for a first-time user.
- [Configuration](Configuration.md) — profile storage resolution order, environment variables, browser cache location.
- [Output Schema](Output-Schema.md) — what actually ends up in the `--output` file.
- [Security & Privacy](Security-and-Privacy.md) — the full redaction/threat model referenced throughout this page.
- [FAQ & Troubleshooting](FAQ-and-Troubleshooting.md)
- [../DISCLAIMER.md](../DISCLAIMER.md)
