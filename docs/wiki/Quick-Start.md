# Quick Start

This page walks through the whole flow once, slowly, with real terminal output at each step. If you just want the condensed version, see the [main README](../README.md#quick-start). If you haven't installed the tool yet, start with [Installation](Installation.md) instead — this page assumes `scrape-fb` is already on your PATH.

Five steps: `setup` → `login` → `status`/`doctor` → `fetch` → look at the output.

## 1. One-time setup

`scrape-fb` drives a real Chromium browser under the hood (via Playwright), and that browser binary doesn't ship inside the Python package — it has to be downloaded separately. `scrape-fb setup` does that download, into a cache directory this tool owns exclusively (never a browser install shared with any other Playwright-based tool on your machine):

```bash
$ scrape-fb setup
```

```
Browser provisioned.
```

This can take a minute or two the first time (it's downloading a Chromium build). You only need to run it once per machine — after that, every `scrape-fb` command reuses the same cached browser. If you ever suspect the browser install got corrupted, `scrape-fb setup --force` reinstalls it.

## 2. Log in

```bash
$ scrape-fb login
```

```
A browser window should now be open. Log in to Facebook there, then press Enter here to continue...
```

At this point a **real, visible Chromium window** opens on your screen. This isn't a headless trick — you log in exactly like you would in any browser: type your email/password, clear any 2FA prompt, solve a captcha if Facebook throws one at you. Nothing is automated about this step on purpose. Once you're looking at your actual timeline in that window, go back to the terminal and press Enter.

`scrape-fb` then checks the page it's currently on: if it doesn't look like a login wall or checkpoint page anymore, it considers you logged in and saves that session:

```
Logged in. Profile saved at /Users/you/Library/Application Support/scraper-for-facebook/profiles/default
```

What actually got saved there is your session — cookies and local storage, `chmod 0700` so only your user account can read it. There's no password stored, but anyone who can read that directory can act as your logged-in Facebook session just as well as you can. Treat it accordingly: don't back it up to iCloud/Dropbox/Time Machine, don't commit it, and if the machine is ever lost or compromised, revoke the session from facebook.com itself (Settings → Security → Where You're Logged In), not just by deleting the folder.

**Use a dedicated or throwaway Facebook account for this, not your main one.** Automating any Facebook account — including "automating" by just reading what a real logged-in browser loads — is against Facebook's Terms of Service, and enforcement shows up as checkpoints or account bans. Read [../DISCLAIMER.md](../DISCLAIMER.md) in full before you go further; this isn't boilerplate legal filler, it covers real account and data risk.

If you mistype something or the browser closes before you finish, just run `scrape-fb login` again — it's idempotent.

## 3. Check your session: `status` vs `doctor`

Two different commands answer two different questions. Reach for the fast one first.

**`scrape-fb status`** — "is my saved session still good?" It reuses your saved profile headlessly (no visible window), loads facebook.com, and looks at where you land: your timeline (logged in), a login page (session expired), or a checkpoint page (account flagged). It does not check whether post-scraping actually works.

```bash
$ scrape-fb status
```

```
status: logged_in (logged in 640s ago)
```

Add `--json` if you want to consume this from a script:

```bash
$ scrape-fb status --json
```

```json
{"status": "logged_in", "session_age_seconds": 640.2}
```

**`scrape-fb doctor`** — "does a real capture round-trip end-to-end?" This is the heavier check: it launches the browser, navigates to facebook.com, and confirms that at least one GraphQL response was actually captured off the wire — the exact mechanism `fetch` depends on. `status` can say `logged_in` while `doctor` still fails, if e.g. Facebook changed something about how its GraphQL traffic looks, or your network is blocking XHRs.

```bash
$ scrape-fb doctor
```

```
OK - captured 14 graphql response(s)
```

Use `status` for a quick "am I still logged in" check before a fetch. Use `doctor` when something's not working and you want to know whether the problem is your login, or the capture pipeline itself.

## 4. Your first fetch

Now the actual scrape. Pick a profile you're logged in and able to view — your own timeline, a friend's, anyone whose posts your logged-in account can already see (this tool never bypasses Facebook's own visibility rules; it only sees what your account sees).

```bash
$ scrape-fb fetch https://www.facebook.com/some.profile --limit 30
```

While this runs, a **headless** browser (no visible window, unless you pass `--headed`) scrolls the profile's timeline, pausing between scrolls, reading the same GraphQL responses your browser would normally just render. When it's done, you'll see a one-line summary on stderr:

```
30 posts, range 2026-03-12..2026-07-04, stop reason: limit_reached. Saved to /Users/you/Library/Application Support/scraper-for-facebook/output/some-profile-20260705T031813123456Z.json
```

That summary always tells you three things, so a partial run is never mistaken for a complete one:
- **how many posts** were retrieved,
- the **date range** actually observed (oldest..newest), and
- the **stop reason** — why scrolling stopped (`limit_reached` here, because `--limit 30` was hit; other reasons include `feed_exhausted`, `feed_stalled`, or `max_scrolls` — see [CLI Reference](CLI-Reference.md#exit-codes) for the full list and what each means for your exit code).

Notice where the file landed: **not** your current directory, and not stdout. By default, output goes under this tool's own per-user data directory (via [`platformdirs`](https://pypi.org/project/platformdirs/) — on macOS, `~/Library/Application Support/scraper-for-facebook/output/`), named `<profile>-<UTC timestamp>.json`. That's deliberate, not an accident of implementation: captured posts contain other people's names, text, and signed media URLs (real third-party personal data — see [../DISCLAIMER.md](../DISCLAIMER.md) §3–4), and a default that lands quietly in your current directory is a default that eventually gets `git add`ed by accident. Pass `--output some/path.json` if you want it somewhere specific.

## 5. A quick look at the output

Open the file and you'll see a JSON array of post objects (or one JSON object per line, if you used `--format ndjson`):

```json
[
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
]
```

This page won't repeat the full field list — see [Output Schema](Output-Schema.md) for what every field means, including the `media`, `links`, and `shared_post` shapes for posts that attach photos, link previews, or quote another post.

## What's next

- **[CLI Reference](CLI-Reference.md)** — every flag on every subcommand, the full exit-code table, and what each stop reason implies.
- **[Python API Reference](Python-API-Reference.md)** — use `FacebookScraper` directly from Python instead of shelling out to the CLI.
- **[Configuration](Configuration.md)** — multiple login profiles, environment variables, and tuning scroll pacing (`--scroll-pause`, `--max-scrolls`) without tripping the non-bypassable floor.
- If something looks wrong or a fetch returns 0 posts, check [FAQ & Troubleshooting](FAQ-and-Troubleshooting.md) before filing an issue.
