---
name: Facebook retrieval
description: Read Facebook via the scrape-fb CLI — a profile's posts, your home feed, a post's comments, search (people/pages/groups/posts), or a group's feed — and chain those results to answer multi-hop questions. Use whenever the user wants something off Facebook, however they phrase it: "what has <person> been posting", "who commented on this", "what is <person>'s circle talking about", "find groups about X", "check my feed", "look up <name> on Facebook". Also use when the user hands over a facebook.com URL and wants its contents. NOT for developing or testing the scraper-for-facebook package itself (that is ordinary repo work), and not for any other social network.
allowed-tools: Bash(scrape-fb:*), Read
---

# Facebook retrieval

`scrape-fb` gives you fast, structured retrieval. **You supply the navigation.** The CLI is deliberately a set of single-purpose primitives with no `crawl` command — deciding which handle to follow next is your job, and it is the whole reason this skill exists.

## Start here: ask the tool what it can do

```bash
scrape-fb catalog          # or: scrape-fb catalog --json
```

That prints every command with its real flags, the exit-code contract, the output contract, the object types, and the known limitations — **in one call.** Run it at the start of a task and work from what it says.

This file deliberately does **not** restate that list. The catalog is generated from the CLI's own parser, so it is correct for the version actually installed; a table copied into this file would silently describe the wrong version the moment the package updates, and you would trust the copy over the truth. Anything you need to *call* a command comes from the catalog. What follows is only the part the catalog can't carry: how to decide what to call next.

## The one thing that will trip you up

**Every retrieval command writes its results to a JSON *file* and prints only a one-line summary to stderr. Nothing useful goes to stdout.** Run a command and read the file — never expect to parse the command's own output.

```bash
scrape-fb feed --limit 10 --output /tmp/feed.json    # stderr: "10 posts, range ... Saved to /tmp/feed.json"
```

Then `Read /tmp/feed.json`. Always pass `--output` with a path you choose; without it the file lands under the platform data directory with a timestamped name you'd then have to go hunting for.

## Preflight

Retrieval needs a logged-in session. Check once at the start of a task, not before every command:

```bash
scrape-fb status          # exit 0 = ready; exit 2 = needs login; exit 3 = checkpoint
```

If it is not installed: `uv tool install scraper-for-facebook` then `scrape-fb setup` (provisions its own isolated browser). If exit 2: **`scrape-fb login` opens a real browser window and needs a human to log in** — it detects completion automatically and times out. You cannot complete it for the user; ask them to do it, then re-check `status`.

Any other non-zero exit → see "When something fails" at the end of this file. Read it *before* improvising a retry: for one of these codes, retrying is the wrong move and can get the account banned.

## What each primitive is *for*

The catalog gives you the flags; this is the judgment about which to reach for.

- **`fetch <profile>`** — one person's timeline. The only surface with a real date filter, so any "what did X post in <period>" question starts here.
- **`feed`** — your own news feed. Use for "what's happening", never for a question about a specific person (their timeline is more complete and filterable).
- **`post <url>`** / **`comments <url>`** — a specific post you already have a URL for. `post` fills the gap that a feed query cannot return a single permalink.
- **`search <query>`** — discovery when you have no handle yet. Returns *Entities* (people/pages/groups) or *Posts* depending on `--type`; entities are handles to fetch with, not answers.
- **`group <group>`** — one group's feed, once search or a link has given you the group.

## Chaining — the actual work

Every `Post` carries `url`, `author_url`, `author_id`; every `Comment` carries `author_url`; every `Entity` carries `id` and `url`. Those are the handles:

- a post's **`url`** → `comments` or `post`
- any **`author_url`** (post author, or commenter) → `fetch`
- a group Entity's **`id`** → `group`

**"What is X's circle discussing?"** → `fetch X` → read the file → collect `author_url` of the people X shares from → `fetch` each (with a `--limit`) → summarize across the results.

**"Who engaged with this post, and what are they into?"** → `comments <url> --limit 20` → collect distinct `author_url` → `fetch` each `--limit 5`.

**"Find the active groups about <topic>"** → `search "<topic>" --type groups` → take each Entity's `id` → `group <id> --limit 10` to see whether it is actually alive.

Two rules that keep a chain from turning into a crawl. **Bound the fan-out before you start it** — decide "the top 5 commenters", not "everyone", because each hop is a real request against a real account (see Ban risk). And **report the shape of what you did**: which hops you took, how many you skipped, and why. A chain that silently sampled 5 of 60 commenters and presents itself as "what the commenters think" is a wrong answer wearing a confident summary.

## Reading the output

Three object types. Tell them apart by a field, never by guessing from context:

- **`Post`** — has **`source`** (`timeline` | `newsfeed` | `group` | `search`), telling you which surface it came from; matters once you merge results from several commands into one pile.
- **`Comment`** — has **`depth`** (`0` = top-level, `≥1` = a reply) and `parent_id`. Its `post_id` matches the parent post's `id`, so comments and posts join on that.
- **`Entity`** — has **`kind`** (`person` | `page` | `group`). Only `search --type people|pages|groups` returns these. It is a *light* record — name/url/id/verified, no posts — so an Entity is a handle to fetch with, not an answer in itself.

For the full field list run **`scrape-fb schema`** (or read `object_types` in `scrape-fb catalog --json`). Prefer that over assuming: both are generated from the code itself, so they cannot drift the way a copy in this file would.

Two fields that mislead if you skim: `captured_at` is when *you* scraped it, never a dedup or sort key — use `id` to dedup and `created_at` to sort. And `created_at` can be `null` when the date could not be located, so filter before comparing dates.

## Ban risk — why this stays slow

The account doing the scraping is at genuine risk of a checkpoint or permanent ban; automating any Meta account violates its Terms of Service. This is why the package clamps a **≥1.0s floor between active requests** and **≥0.5s between scrolls**, in code, un-bypassable — do not try to work around them, and do not fabricate concurrency by launching several `scrape-fb` processes at once, which defeats the floor just as effectively as disabling it.

What that means for how you work: **a deep chain costs real requests and real risk.** `comments --replies` spends one extra request per commented comment, so a 100-comment post is a burst. Deep pagination (`--max-pages`, default 20) multiplies it. So prefer a `--limit` that answers the question over one that exhausts the source, and when a user asks for something genuinely large, say what it will cost before starting rather than discovering it halfway. If a command returns exit 3 (checkpoint), **stop entirely** — retrying a flagged account is how a temporary block becomes a permanent one.

## Third-party data — why the output is sensitive

Scraped output is other people's personal data: names, profile URLs, full comment text, and signed media URLs. Collecting it can make the *user* a data controller under GDPR/CCPA, with real obligations. `comments` and `search` are the sharp edge here — they collect people who never posted anything to the user and have no relationship with them.

So: **write output to a temp path, not into the repo**, and never `git add` it (the repo gitignores `*.json`/`*.ndjson` precisely because of this — don't defeat it with `--output` into a tracked path). Retrieve the narrowest thing that answers the question rather than everything available. When the task is done, say that the files can be deleted, and delete them if you created them for an intermediate step. Quote individuals' text only when the user's question actually needs the quote — a summary usually does the job with less exposure.

`--raw` embeds the unparsed node and is redacted by default; `--no-redact` disables even that. Neither belongs in normal use — they are debugging aids for working on the scraper itself.

## When something fails

`scrape-fb catalog` prints what each exit code *means*. Below is what to *do* — and the theme is that **most failures here are informative, not transient. Retrying the same command is almost never the fix.**

**Exit 3 — checkpoint. Stop immediately.** Meta has flagged the account with a security challenge, and retrying is *actively harmful*: hammering a checkpointed account is how a temporary block becomes a permanent ban. Abandon the task, tell the user their account needs clearing by hand in a real browser, and run no further `scrape-fb` commands this session. If checkpoints recur across sessions, that's a signal about volume — the fix is smaller `--limit`s and fewer hops, not a fresh login.

**Exit 2 — session expired.** Routine; sessions die. `scrape-fb login` opens a real browser and needs a human — you cannot complete it. Ask the user, then re-check `status`. Note `status` inspects the response body, not just the URL, because Facebook serves its login form in place at `facebook.com` with HTTP 200 and no redirect: a dead session looks perfectly healthy from outside. If `status` says expired while a browser looks logged in, trust `status`.

**Exit 4 — zero results is ambiguous.** Either genuinely nothing there (empty timeline, no hits, no comments) or parser drift / `doc_id` rotation. Distinguish with one command: run something you *know* returns data (`scrape-fb feed --limit 3`). If that also returns 0, it isn't your target — see rotation below. If the feed works, the emptiness is real; report it.

**Exit 7 — `--since` unconfirmed.** You have *some* posts but can't claim they're all of them in that range. Never present it as complete: either say the range is partial, or re-run with `--mode active` (if it had fallen back) or a larger `--max-scrolls`.

**`doc_id` rotation — the one real fragility.** Active mode replays Facebook query ids that rotate when Facebook ships a client build. `fetch` survives it (falls back to the browser automatically — you'll see `active mode failed ...; falling back to browser`, and it'll be much slower). `feed`, `comments`, `post`, `search`, `group` do **not**: they're active-only and simply fail. The signature is several active-only commands failing at once while `fetch --mode passive` still works. That's a package-level fix, not something to work around — tell the user and check for a newer release (`scrape-fb catalog` reports the installed version).

**Not bugs, though they look like it:** a hop that fell back to passive is missing the profile's newest post (structural — re-run that hop with `--mode active`); `post`/`comments` on a **reel URL** fails with `could not find a story id` and needs a regular permalink; a comment's `reply_count` can exceed what `--replies` returned, because the count includes deeper nesting and only depth-1 is fetched.
