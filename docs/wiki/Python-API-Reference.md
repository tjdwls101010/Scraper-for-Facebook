# Python API Reference

The public `scraper_for_facebook` Python API — `FacebookScraper`, its two retrieval methods, the result object, and the exception hierarchy — documented as it actually is in v0.3.1.

Read [DISCLAIMER.md](../../DISCLAIMER.md) before pointing any of this at an account you care about.

## Read this first: the Python API covers profile timelines only

`FacebookScraper` exposes exactly **two** retrieval methods, `fetch_profile()` and `iter_profile()`, and both do the same thing: fetch posts from a **profile timeline**.

There is **no Python method** for the other surfaces. In v0.3.1 these are **CLI-only**:

| Surface | CLI | Python |
|---|---|---|
| Profile timeline | `scrape-fb fetch` | `fetch_profile()` / `iter_profile()` |
| Home news feed | `scrape-fb feed` | *(none — shell out)* |
| Comments on a post | `scrape-fb comments` | *(none — shell out)* |
| Single post by URL | `scrape-fb post` | *(none — shell out)* |
| Search | `scrape-fb search` | *(none — shell out)* |
| Group feed | `scrape-fb group` | *(none — shell out)* |

If you need feed, comments, post, search, or group from Python, shell out to the CLI and parse its JSON. That is the supported path, not a workaround — the CLI writes the same objects documented in [Output Schema](Output-Schema.md):

Note that `scrape-fb` writes results to a **file**, not to stdout — `--output` names that file, and the progress/summary lines go to stderr. So the shell-out helper points `--output` at a path you control and reads it back:

```python
import json
import subprocess
import tempfile
from pathlib import Path

NO_RESULTS = 4   # zero results: no file is written and the exit code is 4, not 0

def scrape_fb(*args: str) -> list[dict]:
    """Run a scrape-fb subcommand and return its parsed results."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "results.json"
        proc = subprocess.run(["scrape-fb", *args, "--format", "json", "--output", str(out)])
        if proc.returncode == NO_RESULTS:
            return []
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"scrape-fb {args[0]} failed with exit code {proc.returncode}")
        return json.loads(out.read_text())

comments = scrape_fb("comments", "https://www.facebook.com/permalink.php?story_fbid=123&id=456")
top_level = [c for c in comments if c["depth"] == 0]
```

Exit code `4` means "zero results" and exit code `7` means "partial: `--since` was requested but never confirmed reached" — both are non-zero but neither is a crash, so decide deliberately how your wrapper treats them (the snippet above tolerates `4` and rejects `7`). The full table is in [CLI Reference](CLI-Reference.md).

Check `scrape-fb <command> --help` for the exact flags each subcommand accepts, or `scrape-fb catalog` for a machine-readable description of the whole CLI — every command, its flags, the exit codes, and the output contract. Both run offline.

## Contents

- [Imports](#imports)
- [FacebookScraper](#facebookscraper)
- [The `with` block requirement](#the-with-block-requirement)
- [login()](#login)
- [status()](#status)
- [fetch_profile()](#fetch_profile)
- [iter_profile()](#iter_profile)
- [last_result — RetrieveResult](#last_result--retrieveresult)
- [Exceptions](#exceptions)
- [Active mode comes for free](#active-mode-comes-for-free)
- [Full example](#full-example)

## Imports

Everything in `__all__` is importable from the top-level package:

```python
from scraper_for_facebook import (
    FacebookScraper,
    Post, Media, LinkAttachment,
    Status, RetrieveResult,
    ScraperForFacebookError,
    LoginRequiredError,
    SessionExpiredError,
    ChallengeError,
    ProfileUnavailableError,
    SessionClosedError,
    InvalidIdentifierError,
)
```

One exception is **not** re-exported at the top level and must be imported from its own module:

```python
from scraper_for_facebook.errors import ActiveTransportError
```

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

One instance = one persisted login profile + one set of retrieval settings.

| Parameter | Default | Meaning |
|---|---|---|
| `profile` | `"default"` | Name of the persisted login profile — the same name `scrape-fb login --profile <name>` creates. Also keys the active-mode token cache. |
| `headless` | `True` | Run the browser without a visible window. Set `False` when you want to watch what it does, or when a page needs a human glance. |
| `profile_dir` | `None` | Explicit directory for the browser profile, overriding the name-based lookup. `None` resolves from `profile` — see [Configuration](Configuration.md). |
| `scroll_pause` | `(2.0, 4.0)` | `(min, max)` seconds to wait between scrolls, sampled randomly in that range. A non-bypassable floor applies; see [Configuration](Configuration.md). |
| `max_scrolls` | `40` | Hard cap on scrolls in the passive browser path, so a long timeline can't loop forever. |

`profile` and `profile_dir` travel together into every retrieval call. This matters: active mode keys its token cache by profile **name** while the browser session is keyed by **directory**, so passing a custom `profile_dir` without a matching `profile` name would have the two disagree. The class handles this for you — just don't try to route around it.

Attributes you can read:

- `profile`, `headless`, `scroll_pause`, `max_scrolls` — as constructed.
- `last_result` — a [`RetrieveResult`](#last_result--retrieveresult), or `None` before the first fetch.

## The `with` block requirement

`FacebookScraper` is a context manager and is meant to be used inside a `with` block:

```python
with FacebookScraper(profile="default") as fb:
    posts = fb.fetch_profile("https://www.facebook.com/jordan.reyes.90", limit=25)
```

Leaving the block marks the instance closed. After that:

- `fetch_profile()` raises `SessionClosedError` immediately.
- `iter_profile()` raises `SessionClosedError` when it is **advanced**, not when it is called (it's a generator, so the guard can't run at call time).

Which leads to the one real footgun:

```python
# WRONG — the generator escapes the block and raises on the first next()
with FacebookScraper() as fb:
    stream = fb.iter_profile(url)
for post in stream:      # SessionClosedError
    print(post.text)

# RIGHT — consume inside the block
with FacebookScraper() as fb:
    for post in fb.iter_profile(url):
        print(post.text)
```

## login()

`login` has two call forms, on the class and on an instance:

```python
# Class form — constructs an instance with these keywords, then logs it in.
FacebookScraper.login()                                    # the "default" profile
FacebookScraper.login("research")                          # a named profile
FacebookScraper.login("research", profile_dir="/data/fb")  # explicit directory

# Instance form — takes NO keywords; the profile is already fixed.
fb = FacebookScraper(profile="research")
fb.login()
```

Both return `bool`. The class form accepts `profile` and `profile_dir` because it has to build the session it is about to log into — that's what lets a caller with a custom `profile_dir` log in and fetch against the *same* directory. The instance form deliberately rejects those keywords with a `TypeError` rather than guessing whether you meant its own profile or a different one.

`login()` opens a **real, visible browser window** and waits for you to complete the login interactively. It is not usable headlessly or unattended.

## status()

```python
def status(self) -> Status
```

Reports whether the instance's profile currently has a usable session. `Status` is an enum:

| Member | Value | Meaning |
|---|---|---|
| `Status.LOGGED_IN` | `"logged_in"` | The session works. |
| `Status.EXPIRED` | `"expired"` | Facebook is serving a login wall — log in again. |
| `Status.CHECKPOINT` | `"checkpoint"` | The account is flagged with a security checkpoint. Stop and resolve it in a normal browser. |

```python
from scraper_for_facebook import FacebookScraper, Status

with FacebookScraper() as fb:
    if fb.status() is not Status.LOGGED_IN:
        raise SystemExit("session is not usable; run scrape-fb login")
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

Fetches a profile timeline and returns a list of `Post` objects, newest first (pinned posts first, then undated posts last).

| Parameter | Meaning |
|---|---|
| `url` | Profile URL, username, or numeric id. Normalized internally; an unusable identifier raises `InvalidIdentifierError`. |
| `limit` | Stop after this many posts. `None` means "until the feed is exhausted or a cap trips". |
| `since` / `until` | Date window, as `datetime.date` or a strict `"YYYY-MM-DD"` string. A malformed string raises `ValueError`. Pinned and undated posts bypass the window (see [Output Schema](Output-Schema.md)). |
| `raw` | Attach the raw captured story node to each `Post.raw`. PII-heavy — off by default. |

Side effect: sets `self.last_result` to the full [`RetrieveResult`](#last_result--retrieveresult) for this call.

```python
from datetime import date

with FacebookScraper() as fb:
    posts = fb.fetch_profile("jordan.reyes.90", since=date(2026, 1, 1), limit=100)

for post in posts:
    stamp = post.created_at.isoformat() if post.created_at else "undated"
    print(f"{stamp}  {post.reaction_count or 0:>5} reactions  {post.text[:60]!r}")
```

`Post`, `Media`, and `LinkAttachment` are plain dataclasses. Access fields as attributes (`post.created_at` is a real `datetime | None`), or call `post.to_dict()` to get the JSON-shaped dict documented in [Output Schema](Output-Schema.md) — `to_dict()` is where `datetime` becomes an ISO-8601 `Z` string.

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

The generator form of `fetch_profile()`, with identical parameters.

Be clear about what this does and does not buy you: **it is not lazy retrieval.** The full scroll-capture-parse cycle happens before the first post is yielded, exactly as in `fetch_profile()`; the posts are simply handed to you one at a time afterwards. Breaking out of the loop early does not reduce browser work that has already happened. Use it when you want to start processing without materializing your own list, not as a way to fetch less.

It must be consumed inside the owning `with` block — see [The `with` block requirement](#the-with-block-requirement).

```python
with FacebookScraper() as fb:
    for post in fb.iter_profile("jordan.reyes.90", limit=50):
        if post.type == "shared" and post.shared_post is not None:
            print(f"{post.author_name} shared {post.shared_post.author_name}")
```

## last_result — RetrieveResult

`fetch_profile()` returns only the posts. Everything else about the run lands on `scraper.last_result`, a `RetrieveResult` dataclass:

| Attribute | Type | Meaning |
|---|---|---|
| `posts` | `list[Post]` | The same list `fetch_profile()` returned. |
| `stop_reason` | `str` | Why retrieval stopped (table below). |
| `since_reached` | `bool` | Whether a requested `since` was confirmed crossed (or was moot). `False` means your window may be incomplete. |
| `oldest_seen` | `datetime \| None` | Oldest post timestamp observed during the run. |
| `newest_seen` | `datetime \| None` | Newest post timestamp observed during the run. |
| `scrolls_performed` | `int` | How many scrolls the browser path did. `0` on a pure active-mode run. |
| `transport` | `str` | `"active"` or `"passive"` — which transport actually produced these posts. |

`stop_reason` values:

| Value | Meaning |
|---|---|
| `"feed_exhausted"` | Reached the end of the available feed. The clean finish. |
| `"limit_reached"` | Your `limit` was satisfied. |
| `"since_crossed"` | Retrieval passed the `since` boundary, so everything you asked for is present. |
| `"max_scrolls"` | The `max_scrolls` cap tripped. There is probably more; raise the cap. |
| `"max_pages"` | The active-mode pagination cap tripped. Same implication. |
| `"feed_stalled"` | Scrolling stopped producing new posts before the feed ended. |
| `"unknown_error"` | Retrieval raised before it could record a reason. Treat the result as partial. |

Anything other than `feed_exhausted`, `limit_reached`, or `since_crossed` means your result is truncated — check it before drawing conclusions from a count:

```python
with FacebookScraper(max_scrolls=80) as fb:
    posts = fb.fetch_profile("jordan.reyes.90", since="2025-01-01")

result = fb.last_result
print(f"{len(posts)} posts via {result.transport}, stopped: {result.stop_reason}")
if not result.since_reached:
    print("warning: never confirmed reaching 2025-01-01 — the window is incomplete")
```

## Exceptions

Every error this package raises inherits from `ScraperForFacebookError`, so a single `except` is a safe outer net:

```
ScraperForFacebookError
├── LoginRequiredError        no persisted session for this profile
├── SessionExpiredError       a session existed but Facebook is showing a login wall
├── ActiveTransportError      an active HTTP GraphQL request failed (recoverable)
├── ChallengeError            Meta flagged the account with a security checkpoint
├── ProfileUnavailableError   target is memorialized, blocked, restricted, or absent
├── SessionClosedError        the instance's `with` block already exited
└── InvalidIdentifierError    the target identifier/URL failed validation
```

Notes that matter when you branch on these:

- **`LoginRequiredError` vs `SessionExpiredError`.** The first means you never logged in on this profile; the second means the session was valid once and has since died. Both are fixed by `scrape-fb login --profile <name>`, but only the second indicates something changed underneath you.
- **`ActiveTransportError` is not an auth error.** A rotated GraphQL `doc_id`, a transport hiccup, or a non-200 all land here, and the correct response is to retry through the browser transport — which the default mode already does for you automatically. You will normally never see it. Import it from `scraper_for_facebook.errors`, not the package root.
- **`ChallengeError` is never retried automatically.** Hammering a checkpointed account raises ban risk. Stop, open Facebook in a normal browser, clear the checkpoint, then log in again.
- **`ProfileUnavailableError` is a confirmed "nothing here"**, deliberately distinct from a zero-post result — the latter could be parser drift, this one could not.
- **`InvalidIdentifierError` is also a `ValueError`**, so existing `except ValueError` handlers catch it.

```python
from scraper_for_facebook import (
    FacebookScraper, ChallengeError, LoginRequiredError,
    ProfileUnavailableError, SessionExpiredError, ScraperForFacebookError,
)

try:
    with FacebookScraper(profile="research") as fb:
        posts = fb.fetch_profile("jordan.reyes.90", limit=50)
except (LoginRequiredError, SessionExpiredError):
    raise SystemExit("run: scrape-fb login --profile research")
except ChallengeError:
    raise SystemExit("account checkpointed — resolve it in a normal browser, do not retry")
except ProfileUnavailableError:
    posts = []          # confirmed empty, not a parsing failure
except ScraperForFacebookError as exc:
    raise SystemExit(f"scrape failed: {exc}")
```

## Active mode comes for free

`fetch_profile()` and `iter_profile()` call the same retrieval layer the CLI does, so the library gets active mode with no extra configuration.

Retrieval is **active-first with a passive fallback**: it tries the fast HTTP GraphQL transport, and if that fails with an `ActiveTransportError` it retries the same target through the real browser. You don't opt in, and you don't handle the fallback — it happens inside the call. The fallback is never silent: it prints a one-line notice to stderr, and `last_result.transport` tells you which path produced the posts you got.

```python
with FacebookScraper() as fb:
    posts = fb.fetch_profile("jordan.reyes.90", limit=30)

if fb.last_result.transport == "passive":
    print("fell back to the browser — slower, but the posts are the same shape")
```

The output is identical either way: the parser is transport-agnostic, so a `Post` from active mode and a `Post` from the browser path are indistinguishable. The only visible differences are speed and `scrolls_performed` (`0` on an active run).

The Python API always uses the default `"auto"` mode. Forcing active-only or passive-only is a CLI-level choice; it is not exposed as a `FacebookScraper` parameter in v0.3.1.

## Full example

A complete script: verify the session, fetch a windowed timeline, check for truncation, and report what happened.

```python
#!/usr/bin/env python3
"""Fetch one profile's 2026 posts and summarize the run."""

from datetime import date

from scraper_for_facebook import (
    ChallengeError,
    FacebookScraper,
    LoginRequiredError,
    ProfileUnavailableError,
    ScraperForFacebookError,
    SessionExpiredError,
    Status,
)

TARGET = "https://www.facebook.com/jordan.reyes.90"


def main() -> int:
    try:
        with FacebookScraper(profile="default", headless=True, max_scrolls=60) as fb:
            if fb.status() is not Status.LOGGED_IN:
                print("session unusable — run: scrape-fb login")
                return 1

            posts = fb.fetch_profile(TARGET, since=date(2026, 1, 1), limit=200)
            result = fb.last_result

    except (LoginRequiredError, SessionExpiredError):
        print("no usable session — run: scrape-fb login")
        return 1
    except ChallengeError:
        print("account checkpointed — resolve it in a browser before retrying")
        return 1
    except ProfileUnavailableError:
        print(f"{TARGET} is unavailable (memorialized, blocked, restricted, or gone)")
        return 0
    except ScraperForFacebookError as exc:
        print(f"scrape failed: {exc}")
        return 1

    print(f"{len(posts)} posts via {result.transport} transport")
    print(f"stop reason: {result.stop_reason}  (scrolls: {result.scrolls_performed})")
    if not result.since_reached:
        print("warning: the 2026-01-01 boundary was never confirmed — window incomplete")

    dated = [p for p in posts if p.created_at is not None]
    print(f"{len(posts) - len(dated)} posts had no locatable date")

    unresolved = [p for p in posts if p.text_truncated and not p.text_resolved]
    if unresolved:
        print(f"{len(unresolved)} posts still have truncated text")

    for post in sorted(dated, key=lambda p: p.reaction_count or 0, reverse=True)[:5]:
        print(f"  {post.created_at:%Y-%m-%d}  {post.reaction_count or 0:>5}  {post.text[:60]!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

---

**Next:** [Chaining Recipes](Chaining-Recipes.md) for combining the CLI surfaces this API doesn't cover, and [FAQ & Troubleshooting](FAQ-and-Troubleshooting.md) when a run stops early or returns nothing. Back to the [wiki index](README.md).
