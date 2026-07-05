# FAQ and Troubleshooting

Questions people actually ask about this tool, and the errors people actually hit. If your issue isn't here, check [open issues](https://github.com/tjdwls101010/Scraper-for-Facebook/issues) before filing a new one.

## FAQ

### Will this get my account banned?

It can. Read [../DISCLAIMER.md](../DISCLAIMER.md) — it's not boilerplate. Automating any Meta account, including just driving a real logged-in browser session to read what it loads, is against Facebook's Terms of Service, and Meta enforces that with temporary bans, permanent bans, and checkpoint/"login approval" challenges.

The guardrails in this tool reduce risk, they don't remove it:

- The scroll-pause floor (`--scroll-pause`, minimum 0.5s, non-bypassable) keeps scrolling from happening at inhuman speed — the single hardest lever on checkpoint/ban risk, and the one thing in this tool that isn't just a suggestion.
- One target profile per run, no batch mode, no built-in scheduler or daemon loop — nothing here is built to run unattended at volume.
- Deeper `--since` history means more scrolling, and more scrolling means more risk. Prefer shallow/recent fetches when you can.
- `scrape-fb doctor` and `--headed` let you watch what's happening instead of running blind.

None of that makes this safe for your primary account. **Use a dedicated or throwaway Facebook account**, not the one you actually care about. See [DISCLAIMER.md §1](../DISCLAIMER.md#1-this-violates-facebooks-terms-of-service).

### Is this legal? Does it violate Facebook's ToS?

It violates Facebook's Terms of Service — that part isn't in question. Whether that's *illegal* depends on your jurisdiction, what you do with the data afterward, and facts specific to your situation, so no honest answer to that fits in a wiki FAQ. This is not legal advice, and [DISCLAIMER.md](../DISCLAIMER.md) says so explicitly. Read the whole thing, particularly §3 on becoming a "data controller" over other people's data once you've captured it — that has real legal weight (GDPR, CCPA, etc.) independent of whether scraping itself is illegal where you live. If it matters to your situation, talk to a lawyer.

### Why not just use the Facebook Graph API?

Because the Graph API can't do what this tool does. The Graph API is Meta's *sanctioned* integration surface — it requires app review, scoped permissions, and it fundamentally does not expose a personal, logged-in timeline the way your own browser session sees it when you're just scrolling Facebook. There's no Graph API endpoint that hands you "everything my logged-in account can currently see on this person's timeline."

This tool takes a different path entirely: it drives a real, logged-in browser session (yours) and reads the same `/graphql/`-shaped XHR responses your browser already receives while you scroll. No Graph API, no app review, no credential injection — see [How it works](../README.md#how-it-works) in the README.

### How is this different from `facebook-graphql-scraper`?

[`facebook-graphql-scraper`](https://pypi.org/project/facebook-graphql-scraper/) isn't a new idea — it already captures GraphQL responses this same general way, via Selenium + `selenium-wire` with credential-based (username/password) login. This project's difference is incremental, not categorical:

- **Persisted browser-login profile instead of credential injection.** You log in once, by hand, in a real browser window (`scrape-fb login`); the tool never sees or stores your password, it reuses the resulting session.
- **[scrapling](https://github.com/D4Vinci/Scrapling) (Playwright-driven Chromium) instead of `selenium-wire`.** `selenium-wire` is largely unmaintained; scrapling is actively developed and sits on top of Playwright's modern automation stack.

Same underlying technique (observe your browser's own GraphQL traffic), different login mechanism and different fetch stack under the hood.

### Does this work for Pages, Groups, or Instagram/Threads?

No, not in v1. This tool is **personal-profile timelines only**:

- No Facebook Pages, no Groups, no photo albums.
- No Instagram, no Threads — Facebook only.

See [Limitations (v1)](../README.md#limitations-v1) in the README. If those matter to you, they're roadmap territory, not "supported but buggy" — don't expect `fetch` to work against a Page or Group URL today.

### Why did I get 0 posts on a profile I know has posts?

That's exit code `4`. Zero posts back from a profile that definitely has visible posts usually means one of:

- **Parser drift** — Facebook changed the shape of its GraphQL responses, and the parser (`parse.py`) no longer recognizes the fields it's looking for. This tool works by pattern-matching a JSON shape that Meta doesn't publish or guarantee, so it *will* break silently like this eventually — see the "How it works" tradeoff in the README.
- An unexpected error interrupted scrolling before any post was captured — rerun with `-v` to see what actually happened.

Either way, if the profile is known-good (you can see posts scrolling it yourself, logged in, in a normal browser), **open a GitHub issue**: <https://github.com/tjdwls101010/Scraper-for-Facebook/issues>. Include the `-v` output (already redaction-scrubbed — see [Troubleshooting: filing a bug report](#filing-a-bug-report) below for what's safe to paste).

---

## Troubleshooting

Organized by what you're actually seeing.

### `scrape-fb login` opens a browser but it closes immediately / I can't finish logging in in time

`scrape-fb login` opens a real, headed Chromium window and then **blocks on a terminal prompt** — "press Enter here to continue" — waiting for you to finish logging in by hand. It does not close the browser or time out on its own; if the window closed, something else killed it (the process was interrupted, the terminal session ended, etc.).

If you're not seeing the prompt, check that you're actually looking at the terminal that ran `scrape-fb login` — it's easy to lose track of which window is waiting when a browser also popped up. The fix is almost always: switch back to that terminal, finish logging in in the browser, then press Enter there.

### `ProcessSingleton` / `SingletonLock` error when running `status` or `fetch`

This is a real, common issue, not a bug in the usual sense. Chromium refuses to launch two instances against the **same profile directory** at once and enforces that with a `SingletonLock` file.

**Cause:** you have a `scrape-fb login` process still running somewhere, sitting at the "press Enter here to continue" prompt (see above). That process is holding the browser open against your profile directory, which holds the lock. Any *other* `scrape-fb` command (`status`, `doctor`, `fetch`) that targets the same `--profile`/`--profile-dir` will fail with a `ProcessSingleton`/`SingletonLock`-shaped error, because Chromium won't let a second instance open that same profile concurrently.

**Fix:** find the terminal running `scrape-fb login` and either:
- press Enter to let it finish normally (finish logging in first if you haven't), or
- `Ctrl+C` it to kill it outright,

then retry the command that failed. The lock is released the moment that process exits.

If you're sure nothing is actually still running (e.g. a previous process crashed without cleaning up), the lock file will be stale — but check for a live process first rather than deleting lock files inside your profile directory as a first move.

### Exit code 2 — login required or session expired

Means either you've never run `scrape-fb login` for this `--profile`, or you did once but Facebook is now showing a login wall (the session expired, was logged out remotely, etc.). Fix is the same either way:

```bash
scrape-fb login --profile <name>
```

then retry whatever command gave you the `2`.

### Exit code 3 — account checkpoint

Meta has flagged the session mid-run with a security checkpoint ("login approval," identity verification, etc.). This is never retried automatically by design — hammering a checkpointed account is exactly the kind of behavior that turns a checkpoint into a ban.

**Fix:** log in again yourself, in a real, headed browser (`scrape-fb login`, not `--headed` on `fetch`), and actually resolve whatever Facebook is asking for. Don't script a retry loop around this exit code — if you're hitting it repeatedly, that's a signal to slow down (longer `--scroll-pause`, less frequent runs), not to retry harder.

### Exit code 5 — profile unavailable

The target profile is memorialized, blocked you, restricted its timeline, or doesn't exist. This is not a bug and not parser drift — it's a confirmed "there is nothing here for your logged-in account to see," distinct from exit code `4`'s "there might be posts but nothing came back." Double check the identifier/URL, and check (logged in, in a normal browser) whether you can actually view that profile's timeline yourself.

### Exit code 7 — `--since` not confirmed reached

This is **not an error** — it's an honest signal, not a failure. It means: the fetch stopped (ran out of `--max-scrolls`, or Facebook's feed stopped returning new posts) before this tool could confirm it had scrolled back far enough to reach your requested `--since` date. You still get whatever posts *were* captured, written to `--output` as usual — this exit code just tells you not to trust that the result covers your full requested window.

Why this happens: `--since`/`--until` is documented as **best-effort** (see [Limitations (v1)](../README.md#limitations-v1) in the README). This tool observes Facebook's own pagination as your browser scrolls — it doesn't control Facebook's server-side history retention or decide how far back infinite scroll is willing to go. Facebook can and does stall further pagination before your requested date is reached, especially for old history. The stderr summary always states the actual post count and observed date range, so a partial result is never silently mistaken for a complete one — that's the whole point of this exit code existing.

If you need deeper history reliably, there isn't a guaranteed way to force it in v1 (no `--since-last` incremental state yet either) — raising `--max-scrolls` may help, but raises checkpoint risk in the same breath (see the FAQ above).

### `scrape-fb setup` fails / can't download the browser

`scrape-fb setup` provisions Chromium into this tool's own isolated cache (never a browser install any other tool manages). Failures here are almost always:

- **Network/firewall issue** reaching the Playwright/Chromium download servers — check connectivity, proxy settings, or a corporate firewall blocking the download.
- **Partial or corrupted previous install** — re-run with `--force` to reinstall regardless of what's already there:
  ```bash
  scrape-fb setup --force
  ```

If it still fails after `--force` with a clean network connection, that's worth a GitHub issue with the `-v`-equivalent output (whatever the failure printed) attached.

### Filing a bug report

Open an issue at <https://github.com/tjdwls101010/Scraper-for-Facebook/issues>. Useful things to include:

- Your OS and Python version, and the `scrape-fb --version` output.
- The exact command you ran and its exit code.
- The `-v`/`--verbose` stderr output. This is safe to paste as-is — it's already routed through this tool's redaction path, which strips signed media URLs, session-token-shaped fields, and truncates message text before anything reaches your terminal.

**Never paste raw captured post bodies**, and never run with `--raw --no-redact` to generate a bug report. `--raw` alone still redacts the captured story node by default; `--no-redact` turns that off entirely and prints an on-screen warning for a reason — the result is other people's names, message text, and signed media URLs in the clear. If you need to show a maintainer what a malformed capture looks like, use the default redacted `--raw` output, not `--no-redact`, and still review it yourself before posting publicly. See [DISCLAIMER.md §5](../DISCLAIMER.md#5-diagnostics-are-redacted--but-redaction-is-not-a-certification) for exactly what redaction does and doesn't guarantee.
