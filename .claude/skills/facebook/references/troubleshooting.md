# When retrieval fails

Read this when a `scrape-fb` command exits non-zero, returns nothing, or returns less than expected.

**What each exit code *means* comes from `scrape-fb catalog`** (it prints the full table, generated from the CLI itself). This file covers what to *do* about them — the judgment the catalog can't carry. The theme throughout: **most failures here are informative, not transient. Retrying the same command is almost never the fix.**

## Exit 2 — session expired

Routine; sessions die. `scrape-fb login` opens a real browser and **needs a human**. You cannot complete it. Ask the user, then re-check `scrape-fb status`.

Note that `status` inspects the response body, not just the URL — Facebook serves its login form in place at `facebook.com` with HTTP 200 and no redirect, so a dead session can look perfectly healthy from outside. If `status` says expired while a browser looks logged in, trust `status`.

## Exit 3 — checkpoint. Stop.

Meta has flagged the account with a security challenge. Retrying is *actively harmful*: hammering a checkpointed account is how a temporary block becomes a permanent ban. Stop the whole task, tell the user their account needs clearing by hand in a real browser, and run no further `scrape-fb` commands this session.

If checkpoints recur across sessions, that is a signal about volume, not bad luck — the fix is smaller `--limit`s and fewer hops, not a fresh login.

## Exit 4 — zero results is ambiguous

Two very different causes wear this one code, and they need opposite responses:

1. **Genuinely nothing there** — an empty timeline, a search with no hits, a post with no comments. Correct answer: report the emptiness.
2. **Parser drift or `doc_id` rotation** — Facebook changed something and the tool no longer recognizes the response.

Distinguish them cheaply, with one command: run something you *know* should return data (`scrape-fb feed --limit 3`). If that also returns 0, it isn't about your target — it's (2), see below. If the feed works, the empty result is real.

## Exit 7 — `--since` not confirmed

You have *some* posts but cannot claim they're all of them in that range. Mostly a passive-mode outcome: passive scrolls until its budget runs out, whereas active mode hands the dates to the server as a real filter.

Never present exit-7 output as complete. Either say the range is partial, or re-run with `--mode active` (if it had fallen back) or a larger `--max-scrolls`.

## `doc_id` rotation — the one real fragility

Active mode replays Facebook query ids captured at a point in time; Facebook rotates them when it ships a client build, and a stale id fails.

**`fetch` survives this** — it falls back to the browser automatically (you'll see `active mode failed ...; falling back to browser` on stderr, and it will be much slower). **`feed`, `comments`, `post`, `search`, `group` do not** — they're active-only, having never had a browser-scroll implementation to fall back to.

The signature: several active-only commands failing at once while `fetch --mode passive` still works. That's a package-level fix (re-capturing ids), not something to work around from the CLI. Tell the user and check whether a newer `scraper-for-facebook` release exists — `scrape-fb catalog` reports the installed version.

## Behaviors that look like bugs but aren't

`scrape-fb catalog` lists these under `limitations` — the ones that most often get mistaken for a failure mid-task:

- A chain that **fell back to passive** will be missing the profile's newest post. That's structural, not a glitch; re-run that hop with `--mode active`.
- **`post`/`comments` on a reel URL** fails with `could not find a story id`. Not fixable from the CLI — you need a regular post permalink.
- A comment's **`reply_count` can exceed the replies you got** with `--replies`: the count includes deeper nested replies, and only depth-1 is fetched.
