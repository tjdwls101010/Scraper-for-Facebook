# Configuration

This page covers login profiles, where things are stored on disk, and the two flags most worth tuning deliberately: `--scroll-pause` and `--max-scrolls`. For the full flag list see [CLI Reference](CLI-Reference.md); this page is about *why* the defaults are what they are and when to change them.

## Login profiles

A "profile" is just a persisted, logged-in browser session — cookies and local storage saved to disk after you run `scrape-fb login`. It's the same idea as a Chrome profile: everything needed to resume the session without logging in again.

Every command that touches the browser takes `--profile NAME`:

```bash
scrape-fb login   --profile work
scrape-fb status  --profile work
scrape-fb doctor  --profile work
scrape-fb fetch   --profile work https://www.facebook.com/some.profile
```

If you don't pass `--profile`, everything uses a profile named `default`. You only need more than one profile if you're logging into more than one Facebook account from this tool — most people never need this.

Profiles are stored under a platformdirs-managed data directory, one subdirectory per name. On macOS that's:

```
~/Library/Application Support/scraper-for-facebook/profiles/<name>/
```

So `scrape-fb login` (the default profile) and `scrape-fb login --profile work` end up at `.../profiles/default/` and `.../profiles/work/` respectively — fully independent sessions, no shared state.

Each profile directory is created at permission `0700` (owner read/write/execute only) — see [Security & Privacy](Security-and-Privacy.md) for why that matters. In short: that directory *is* an authenticated Facebook session with no password attached. Treat it accordingly, and read [DISCLAIMER.md](../DISCLAIMER.md) §6 before you back it up, sync it, or copy it anywhere.

## Overriding where profiles live: `--profile-dir` and `SFB_PROFILE_DIR`

If you don't want profiles under the default platformdirs path — e.g. you keep all app state on a separate encrypted volume — you can override the root directory profiles are stored under, two ways:

- `--profile-dir PATH` on the command line (`login`, `status`, `doctor`, `fetch` all accept it)
- the `SFB_PROFILE_DIR` environment variable

The precedence, exactly, is:

1. `--profile-dir PATH`, if given, always wins.
2. Otherwise, the `SFB_PROFILE_DIR` environment variable, if set.
3. Otherwise, the platformdirs default (`.../scraper-for-facebook/profiles/`).

Whichever root is in effect, the actual profile still lives at `<root>/<name>`, so `--profile` and `--profile-dir`/`SFB_PROFILE_DIR` compose normally:

```bash
export SFB_PROFILE_DIR=/Volumes/secure/fb-profiles
scrape-fb login --profile work
# -> session stored at /Volumes/secure/fb-profiles/work/
```

A `--profile-dir` passed on the command line overrides `SFB_PROFILE_DIR` for that invocation only, without unsetting the environment variable.

## The isolated browser cache

Separately from login profiles, this tool also keeps its own **Chromium install** isolated from every other Playwright-based tool on your machine. It does this by setting `PLAYWRIGHT_BROWSERS_PATH` to:

```
~/Library/Application Support/scraper-for-facebook/browsers/
```

before launching any browser session. `scrape-fb setup` installs Chromium into that path; every later `login`/`status`/`doctor`/`fetch` reads from it.

This isolation is deliberate, not incidental: Playwright and patchright pin exact browser build versions, and different tools on your system (this one, another scraper, an unrelated automation project) can easily want different versions of the same browser. Sharing a cache means one tool's `install` can silently break another's. Keeping `scraper-for-facebook`'s Chromium in its own directory means this tool never touches, and is never touched by, anyone else's Playwright browser cache — including if you also use the `web-fetch` skill or another Playwright-based tool on the same machine.

You should not normally need to think about this path at all — it's not user-configurable, and there's no flag or environment variable for it. It's documented here so that if you ever go looking for where `scrape-fb setup` put ~300MB of Chromium, you know where to look (and that deleting it just means the next `login`/`fetch` will need `scrape-fb setup` run again).

## Tuning `--scroll-pause` and `--max-scrolls`

`fetch` scrolls the timeline to load more posts, the same way you would by hand. Two flags control how that scrolling behaves:

| Flag | Default | Meaning |
|---|---|---|
| `--scroll-pause MIN,MAX` | `2.0,4.0` | Seconds to wait between scrolls, randomized in this range |
| `--max-scrolls N` | `40` | Maximum number of scroll actions in one `fetch` run |

**The tradeoff is real and it runs in one direction: faster/deeper scrolling raises your account's checkpoint/ban risk.** Facebook's abuse detection looks at exactly this kind of signal — a browser scrolling far faster or more persistently than a human would. Raising `--max-scrolls` lets a single run reach further back into a timeline's history (useful for a wide `--since` window); lowering `--scroll-pause` makes each run finish faster. Both of those wins come at the cost of looking less human to Facebook.

**One floor is non-bypassable:** `--scroll-pause` cannot go below `0.5` seconds no matter what you pass. `clamp_scroll_pause` enforces this in code — not just as documented advice — for both the low and high end of the range (if you pass a max below the clamped min, the max gets raised to match it). Passing something below the floor doesn't error; it gets silently raised, with a note on stderr telling you what actually got used:

```
scrape-fb: --scroll-pause 0,0.2 raised to 0.5,0.5 (minimum is 0.5s)
```

This applies regardless of how the value arrives — CLI flag or direct Python API call. There is no flag, environment variable, or config file that disables it. It exists specifically so this tool can't be turned into a mass-scraping tool by cranking pacing to zero — see [DISCLAIMER.md](../DISCLAIMER.md) and the "Guardrails" section of the [main README](../README.md).

**When it's reasonable to raise the defaults:**
- You need to reach further back in a timeline's history than 40 scrolls gets you (`--since` with an old date), and you're comfortable with the added checkpoint risk for that one run.
- You're doing a one-off deep pull and would rather it run slower and more human-like than fast — in that case, raise `--scroll-pause` *and* `--max-scrolls` together, not just `--max-scrolls` alone.

**When you should not lower them below the defaults:** essentially never. The defaults (`2.0`-`4.0` seconds, 40 scrolls) are already a deliberately cautious starting point, not an arbitrary one. Lowering `--scroll-pause` toward the floor to finish faster is exactly the behavior pattern Facebook's detection is built to catch, and the floor exists because "just this once" is how accounts get flagged. If you're tempted to lower it, prefer running with `--headed` instead so you can watch what's happening, rather than speeding up a headless run.

## Default output location and `--output`

`fetch` writes captured posts to a file — never to stdout, and never to your current directory by default. The default path is:

```
~/Library/Application Support/scraper-for-facebook/output/<identifier>-<timestamp>.<ext>
```

(`<ext>` is `json` or `ndjson` depending on `--format`.) This default is deliberate: captured posts contain other people's names, message text, and signed media URLs (see [DISCLAIMER.md](../DISCLAIMER.md) §4), and a default that lands outside any git-tracked path makes it harder to accidentally commit someone else's personal data.

Pass `--output PATH` to write somewhere else instead:

```bash
scrape-fb fetch https://www.facebook.com/some.profile --limit 30 --output ./out.json
```

`--output` is a plain path override — it doesn't change where profiles or the browser cache live, only where the fetched posts get written. Whatever directory you point it at, you're responsible for keeping that file as secure as its contents warrant (see [Security & Privacy](Security-and-Privacy.md)).
