# Python API Reference

Everything in this page is importable from the top-level `scraper_for_facebook` package. If you only need the CLI, see [CLI Reference](CLI-Reference.md) instead — this page is for embedding scraping into your own Python code.

Read [DISCLAIMER.md](../DISCLAIMER.md) before writing anything that calls this on an account you care about.

```python
from scraper_for_facebook import (
    FacebookScraper, Post, Media, LinkAttachment, Status, RetrieveResult,
    ScraperForFacebookError, LoginRequiredError, SessionExpiredError,
    ChallengeError, ProfileUnavailableError, SessionClosedError, InvalidIdentifierError,
)
```

## Contents

- [FacebookScraper](#facebookscraper)
- [login() — two call forms](#login--two-call-forms)
- [status()](#status)
- [fetch_profile()](#fetch_profile)
- [iter_profile()](#iter_profile)
- [Exceptions](#exceptions)
- [Full example](#full-example)

## FacebookScraper

```python
class FacebookScraper:
    def __init__(
        self,
        profile: str = "default",
        *,
        headless: bool = True,
        profile_dir: str | Path | None = None,
        scroll_pause: tuple[float, float] = (2.0, 4.0),
        max_scrolls: int = 40,
    ) -> None: ...
```

One instance = one persisted login profile + one set of fetch settings. It's a context manager — always use it inside a `with` block:

```python
with FacebookScraper(profile="default") as fb:
    posts = fb.fetch_profile("https://www.facebook.com/some.profile", limit=30)
```

Exiting the `with` block just marks the instance closed (`self._closed = True`); it doesn't hold a browser or session open between calls — each `fetch_profile()` call launches and tears down its own browser session internally. The `with` block exists so the instance can refuse further use once you've said you're done with it (see [`SessionClosedError`](#sessionclosederror)).

### Constructor parameters

| Parameter | Default | Meaning |
|---|---|---|
| `profile` | `"default"` | Name of the persisted login profile to use. Maps to a directory under this tool's data dir (see [Configuration](Configuration.md#profiles)) unless `profile_dir` overrides it. Passed positionally or by keyword. |
| `headless` | `True` | Whether the underlying Chromium runs headless. `login()` always forces a headed browser internally regardless of this setting (see below) — this flag only affects `fetch_profile()`/`iter_profile()`/`status()`. Set `False` to watch a fetch run for debugging. |
| `profile_dir` | `None` | Explicit override for where the login profile lives on disk. `None` means "resolve from `profile` using the normal lookup" (env var, then the platform data directory — see [Configuration](Configuration.md)). Accepts a `str` or a `pathlib.Path`. |
| `scroll_pause` | `(2.0, 4.0)` | `(min, max)` seconds to randomly wait between scrolls. Silently clamped upward if `min` is below the tool's non-bypassable floor — see [Guardrails in the README](../README.md#guardrails). |
| `max_scrolls` | `40` | Hard cap on scroll iterations per fetch — the scroll budget. |

Two more things worth knowing about the instance:

- `fb.last_result` starts as `None` and is set to the `RetrieveResult` from the most recent `fetch_profile()` call (see [`fetch_profile()`](#fetch_profile) below) — useful for inspecting `stop_reason`/`since_reached`/scroll counts after the fact without threading extra return values through your own code.
- Construction itself never touches the network or the filesystem beyond resolving `profile_dir` — no browser is launched until you call `login()`, `status()`, `fetch_profile()`, or `iter_profile()`.

## login() — two call forms

`login()` opens a real, headed browser window and waits for you to log in to Facebook by hand, then persists the session to `profile_dir`. It deliberately behaves differently depending on how you call it:

```python
# Form 1 — instance method, no arguments.
FacebookScraper(profile="work").login()

# Form 2 — classmethod shim, takes the same keywords the constructor does.
FacebookScraper.login(profile="work", profile_dir="/custom/path")
```

Both end up doing the same underlying work (launch headed, wait for you to press Enter once you've logged in, then check for a login wall and persist). The reason both forms exist rather than just one:

- **`FacebookScraper(profile="work").login()`** — you already built an instance with a specific `profile`/`profile_dir`. Calling `login()` on it takes **no arguments**, because those are already fixed by the instance. Passing `profile=` again here would be ambiguous — log into *this* instance's profile, or silently construct and log into a different one? — so it's not accepted at all; passing anything raises a plain `TypeError`.
- **`FacebookScraper.login(profile=..., profile_dir=...)`** — called on the *class*, with no instance yet. This is a convenience shim: it constructs a throwaway instance from the keywords you pass, then logs that instance in. This is what lets a one-liner like `FacebookScraper.login(profile="work")` work without you first writing `FacebookScraper(profile="work").login()`.

The underlying mechanism (a descriptor the package calls `_HybridLogin`) exists specifically so a custom `profile_dir` you pass to `FacebookScraper.login(profile_dir=...)` is guaranteed to be the *same* directory that instance would then use to log in — a classmethod-only shim can't otherwise guarantee that without you repeating `profile_dir` a second time somewhere and risking it drifting out of sync.

Returns `True` if no login wall (`/login` or `/checkpoint/` redirect) is detected on `facebook.com` afterward, `False` otherwise. It does not raise on a failed login attempt — check the return value.

```python
if not FacebookScraper(profile="default").login():
    print("Login didn't go through — check the browser window and try again.")
```

## status()

```python
def status(self) -> Status
```

Launches a headless browser, navigates to `facebook.com`, and reports which of three states the persisted session is in:

| `Status` member | Meaning |
|---|---|
| `Status.LOGGED_IN` | Session is valid; `fetch_profile()`/`iter_profile()` should work. |
| `Status.EXPIRED` | No profile directory exists yet, or Facebook redirected to a login wall. Fix: call `login()`. |
| `Status.CHECKPOINT` | Facebook redirected to a security checkpoint. Fix: log in again from a real, headed browser and clear the checkpoint by hand before retrying. |

```python
from scraper_for_facebook import FacebookScraper, Status

fb = FacebookScraper(profile="default")
if fb.status() is not Status.LOGGED_IN:
    fb.login()
```

## fetch_profile()

```python
def fetch_profile(
    self,
    url: str,
    *,
    limit: int | None = None,
    since: str | date | None = None,
    until: str | date | None = None,
    raw: bool = False,
) -> list[Post]
```

Runs one full fetch (launch browser → navigate → scroll → capture GraphQL XHRs → parse → filter/sort → resolve truncated text) and returns the resulting posts as a plain `list[Post]`, already sorted (pinned posts first, then newest-first) and already limited/windowed. Must be called on an instance that hasn't exited its `with` block.

**Parameters:**

- `url` — a profile URL (e.g. `https://www.facebook.com/some.profile`) or bare username/`profile.php?id=...` form. Validated and normalized before use; an unparseable value raises [`InvalidIdentifierError`](#invalididentifiererror) immediately, before any browser is launched.
- `limit` — maximum number of posts to return. `None` means no count limit (bounded only by `max_scrolls` and feed exhaustion).
- `since` / `until` — inclusive date bounds, either an ISO `"YYYY-MM-DD"` string or a `datetime.date`. A malformed string raises `ValueError` (strict `date.fromisoformat` parsing) — this is a plain `ValueError`, not one of this package's typed errors. `since` is **best-effort**: see the caveat in the [README](../README.md#limitations-v1) and check `fb.last_result.since_reached` afterward if you need to know whether the bound was actually confirmed crossed.
- `raw` — when `True`, each `Post` also carries its raw captured story node for debugging. See [Output Schema](Output-Schema.md) for exactly what that includes and its redaction behavior.

For the full field-by-field shape of the returned `Post`/`Media`/`LinkAttachment` objects, see [Output Schema](Output-Schema.md) — this page only covers the method signatures.

### Full error-handling example

```python
from datetime import date
from scraper_for_facebook import FacebookScraper
from scraper_for_facebook.errors import (
    LoginRequiredError, SessionExpiredError, ChallengeError,
    ProfileUnavailableError, SessionClosedError, InvalidIdentifierError,
)

with FacebookScraper(profile="default") as fb:
    try:
        posts = fb.fetch_profile(
            "https://www.facebook.com/some.profile",
            limit=30,
            since=date(2026, 1, 1),
        )
    except InvalidIdentifierError:
        print("That doesn't look like a valid Facebook profile URL.")
    except LoginRequiredError:
        print("No saved session for this profile yet — run login() first.")
    except SessionExpiredError:
        print("Session expired — log in again.")
    except ChallengeError:
        print("Account is checkpointed. Clear it in a real browser before retrying.")
    except ProfileUnavailableError:
        print("Target profile is memorialized, blocked, restricted, or doesn't exist.")
    except SessionClosedError:
        print("Called after the `with` block exited — this shouldn't happen here.")
    else:
        print(f"Got {len(posts)} posts; stopped because {fb.last_result.stop_reason}")
```

## iter_profile()

```python
def iter_profile(
    self,
    url: str,
    *,
    limit: int | None = None,
    since: str | date | None = None,
    until: str | date | None = None,
    raw: bool = False,
) -> Iterator[Post]
```

Same parameters and same underlying fetch as `fetch_profile()` — this is the generator form. Two things about it are easy to get wrong:

**It must be consumed inside the owning `with` block.** Advancing it (the first `next()`, e.g. by starting a `for` loop over it) after the block has exited raises [`SessionClosedError`](#sessionclosederror), rather than silently touching an already-closed session. Because it's a generator, this check can't run at call time — calling `iter_profile(...)` itself never raises, even on an already-closed instance; only actually advancing it does:

```python
with FacebookScraper(profile="default") as fb:
    gen = fb.iter_profile("https://www.facebook.com/some.profile", limit=10)
# `with` block has exited here — `gen` was never advanced.
next(gen)  # raises SessionClosedError now, on first advance.
```

**It does NOT stream incrementally.** This is the point most people get wrong: `iter_profile()` still fully scrolls, captures every GraphQL response, and parses all of it *before yielding the first post* — exactly like `fetch_profile()`, just handing results back one at a time afterward instead of all at once. Breaking out of your loop early does not reduce browser work that's already been done, because that work happens before the loop's first iteration, not during it. If you want early-exit to actually save time, there isn't currently a way to do that — use `fetch_profile()` with a smaller `limit` instead.

```python
with FacebookScraper(profile="default") as fb:
    for post in fb.iter_profile("https://www.facebook.com/some.profile", limit=30):
        print(post.id, post.created_at)
        # By the time this loop starts, the full scroll/capture/parse pass has
        # already run — `break` here doesn't undo or skip any of that work.
```

## Exceptions

All exceptions live in `scraper_for_facebook.errors` and are also re-exported from the top-level package. All of them ultimately subclass `ScraperForFacebookError`, so `except ScraperForFacebookError:` catches anything this package raises on purpose.

```
ScraperForFacebookError (base)
├── LoginRequiredError
├── SessionExpiredError
├── ChallengeError
├── ProfileUnavailableError
├── SessionClosedError
└── InvalidIdentifierError (also subclasses ValueError)
```

#### `ScraperForFacebookError`

Base class for every error this package raises on purpose. Catch this if you just want to distinguish "this package failed in a known way" from an unexpected exception.

#### `LoginRequiredError`

No persisted, logged-in session exists yet for this profile — `profile_dir` doesn't exist on disk. **Fix:** call `login()` (or `scrape-fb login --profile <name>` from the CLI).

#### `SessionExpiredError`

A persisted session exists, but Facebook showed a login wall when this fetch tried to use it. Distinct from `LoginRequiredError`: this means the session *was* valid at some point and has since expired, rather than never having been created. **Fix:** call `login()` again.

#### `ChallengeError`

Facebook has flagged the account with a security checkpoint mid-session. This is never retried automatically — hammering a checkpointed account raises ban risk. **Fix:** log in again from a real, headed browser and manually clear the checkpoint before retrying.

#### `ProfileUnavailableError`

The target profile is memorialized, blocked, restricted, or doesn't exist. This is distinct from a fetch that just happens to return zero posts (which could be parser drift) — this is a confirmed "there's nothing to fetch here."

#### `SessionClosedError`

Either `fetch_profile()`/`iter_profile()` was called on an instance whose `with` block has already exited, or an `iter_profile()` generator was advanced after that point. **Fix:** don't hold onto a `FacebookScraper` instance (or a generator from it) past its `with` block.

#### `InvalidIdentifierError`

The `url` you passed to `fetch_profile()`/`iter_profile()` failed validation — wrong scheme, no profile path, malformed `profile.php` query string, etc. Also subclasses `ValueError`, so existing `except ValueError:` handling around URL parsing still catches it. Raised immediately, before any browser is launched.

## Full example

```python
from datetime import date

from scraper_for_facebook import FacebookScraper, Status
from scraper_for_facebook.errors import (
    LoginRequiredError, SessionExpiredError, ChallengeError,
    ProfileUnavailableError, InvalidIdentifierError,
)

PROFILE = "default"
TARGET = "https://www.facebook.com/some.profile"

fb = FacebookScraper(profile=PROFILE)

if fb.status() is not Status.LOGGED_IN:
    print("Not logged in yet — opening a browser window...")
    if not fb.login():
        raise SystemExit("Login failed; check the browser window and try again.")

with FacebookScraper(profile=PROFILE) as fb:
    try:
        posts = fb.fetch_profile(TARGET, limit=50, since=date(2026, 1, 1))
    except InvalidIdentifierError:
        raise SystemExit(f"Not a valid profile URL: {TARGET}")
    except LoginRequiredError:
        raise SystemExit("No saved session — call login() first.")
    except SessionExpiredError:
        raise SystemExit("Session expired — log in again.")
    except ChallengeError:
        raise SystemExit("Account is checkpointed — clear it in a real browser first.")
    except ProfileUnavailableError:
        raise SystemExit(f"Profile unavailable: {TARGET}")

    result = fb.last_result
    print(f"Fetched {len(posts)} posts ({result.stop_reason}, since_reached={result.since_reached})")
    for post in posts:
        print(post.created_at, post.author_name, (post.text or "")[:60])
```

Note the two separate `FacebookScraper(profile=PROFILE)` instances above are deliberate: `status()`/`login()` don't need to happen inside a `with` block (they don't return anything that depends on the session staying open), while `fetch_profile()`/`iter_profile()` should always be scoped to one.

See [Output Schema](Output-Schema.md) for what `post.author_name`, `post.created_at`, etc. actually contain, and [Configuration](Configuration.md) for how `profile`/`profile_dir` resolution and scroll-pacing tuning work in more depth.
