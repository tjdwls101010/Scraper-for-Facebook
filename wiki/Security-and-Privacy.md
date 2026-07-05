# Security and Privacy

> **Start with [DISCLAIMER.md](../DISCLAIMER.md).** That file is the authoritative, plain-language summary of the risks you take on by using this tool, and nothing here supersedes it. This page exists to go one level deeper — into the actual mechanics of what's stored, what's scrubbed, and what isn't — for anyone who wants to understand the threat model before pointing this tool at their real account.

None of this is legal advice. If any of it matters to your situation, talk to a lawyer.

## Your login profile is a live session credential

`scrape-fb login` opens a real Chromium window, you log in by hand, and Playwright persists that browser profile — cookies and local storage — to a directory on disk. That directory *is* your authenticated session. Whoever can read it can act as you on Facebook, no password and no 2FA prompt required, because your original login already cleared both and the profile is just the resulting session state sitting on disk.

Concretely, the profile directory holds whatever a normal logged-in Chromium session for facebook.com holds: session and auth cookies (`c_user`, `xs`, `datr`, `sb`, and friends), plus whatever Facebook's web client keeps in local storage/IndexedDB. This is not a scrape-for-facebook-specific format — it's the same on-disk shape Playwright/Chromium uses for any persistent browser context.

**Where it lives:** by default, under this tool's own per-user data directory (see [Configuration](Configuration.md) for the exact path and the `SFB_PROFILE_DIR`/`--profile-dir` overrides). You can point it elsewhere, but wherever it ends up, treat it as a bearer credential, not a config file.

### The 0700 enforcement, and why it's stricter than a chmod

The profile directory is created with `0700` permissions — owner read/write/execute only, nobody else on the machine can even list its contents. That part is straightforward. The detail worth knowing is *how* it gets there: `ensure_profile_dir` (in `profiles.py`) sets a restrictive `umask(0o077)` **before** calling `mkdir(parents=True)`, not just a `chmod` after the fact:

```python
old_umask = os.umask(0o077)
try:
    path.mkdir(parents=True, exist_ok=True)
finally:
    os.umask(old_umask)
os.chmod(path, _PROFILE_DIR_MODE)
```

Why this matters: `mkdir` followed by a *later* `chmod` has a window — however brief — where the directory exists at the ambient umask (often `0755`, world-readable) before the permissions get tightened. On a genuinely multi-user machine, that's a real race, not a theoretical one. Setting the umask first means every directory `mkdir` creates in that call — including the shared `profiles/` root, since `parents=True` creates it too — is born at `0700` directly; there's no gap for another local user to win. The explicit `chmod` calls afterward are a second, belt-and-suspenders layer, mostly there to correct a root directory that a version of this tool from before this fix left loose.

None of this helps against anyone with root, physical disk access, or a full-disk backup — see the next section.

### Why this is *less* protected than your regular browser

Chrome, Safari, and Firefox all encrypt their cookie stores using OS-level keychain/keyring integration (macOS Keychain, GNOME Keyring, DPAPI on Windows) — reading them requires either the logged-in user's session *and* going through the OS's decryption API, or the user's login password in some configurations. A `0700` directory has no such second factor: it's Unix permission bits, full stop. Anyone who obtains the raw bytes — via a `sudo`-capable process, a filesystem-level backup, a stolen unencrypted disk, or a misconfigured shared/multi-tenant environment — has everything they need, without touching a keychain. `0700` protects against *other unprivileged local users*; it does nothing against someone who already has root or a copy of the disk.

### What to actually do about it

- **Never sync, back up, or version this directory.** No Time Machine, no iCloud Drive/Dropbox/Google Drive folder, no `git add`. Each of those either encrypts-at-rest with keys you don't control, or doesn't encrypt at all, or hands a copy of your live session to a third-party service — any of which defeats the point of keeping it local and `0700`.
- **If the device or disk is lost, stolen, or compromised, don't just delete the local directory** — deleting your local copy does nothing to a session Facebook's servers still consider valid. Revoke it from Facebook's side: **facebook.com → Settings → Security and Login → Where You're Logged In**, and end that session remotely. That's the only action that actually invalidates the credential.
- If you use multiple profiles (`--profile NAME` / `scrape-fb status`, see [Configuration](Configuration.md)), each one is an independent live session — the same rules apply to every one of them individually.

## The redaction system

Everything the tool prints or writes as a *diagnostic* — not your requested output data — goes through one shared scrubbing path in `redact.py`, by design (its own docstring calls this out: every diagnostic surface must route through this module, precisely so a sensitive value doesn't leak through some path someone forgot to scrub).

**What routes through redaction:**

- `-v`/`--verbose` diagnostic output
- error messages (login failures, status-check failures, setup failures, unexpected errors during a fetch)
- `--raw` per-post debug output, **by default** (the raw captured GraphQL story node attached to each post) — `--raw` alone gives you the scrubbed version
- any other message printed to stdout/stderr by the CLI

**What does NOT route through redaction — deliberately:**

- **Your actual `--output` file.** The captured posts you asked for are written out full and unredacted, on purpose. That file *is* the tool's whole reason to exist — a scrubbed version would defeat the point. See [DISCLAIMER.md §4-5](../DISCLAIMER.md) and treat that file as sensitive from the moment it's written (see "Third-party data" below).
- `--raw` output when combined with `--no-redact` — this disables the scrub path entirely for that debug field and prints an on-screen warning when you do it. Only use this locally, for debugging a parser problem, never in a shared terminal or screen recording.

### What it actually scrubs

Reading `redact.py`, the module does four specific things, all structural/pattern-based rather than semantic:

1. **Session/token-shaped keys.** A fixed set of field names — `fb_dtsg`, `lsd`, `jazoest`, `datr`, `sb`, `c_user`, `xs`, `token`, `access_token`, `cookie`, `cookies`, `authorization` — are replaced with `[REDACTED]` wherever they appear as a dict key (structured redaction) or as a `key=value`/`"key":"value"` pair inside a raw text blob (regex-based redaction, for when a whole response body ends up dumped into an error message). These are exactly the fields that would let someone replay your session.
2. **Signed CDN URLs.** Facebook media URLs on `fbcdn.net` or `fbstatic-a.akamaihd.net` carry a signed, viewer-scoped, time-limited query string — anyone holding one of those URLs can fetch that specific media *as you*, until it expires. `redact_url` strips the query string off any URL matching those hosts, leaving the bare path. The host match is anchored (`(?:^|\.)fbcdn\.net$`, not a bare substring check) specifically so a lookalike host like `evilfbcdn.net` isn't falsely treated as trusted, and so the real host is never accidentally under-matched and left unredacted.
3. **Free-text fields.** Known text-bearing keys (`text`, `message`, `name`, `author_name`, `title`, `description`) longer than 40 characters get truncated to `first 40 chars...[redacted N more chars]` — so a diagnostic dump doesn't reproduce someone's full post or a person's full name in your terminal scrollback or a pasted bug report.
4. **Recursive structural scrubbing.** `redact()` walks dicts/lists/strings recursively, applying the above rule-by-rule to every nested value — it isn't just a top-level pass.

### Be honest about its limits

This is pattern matching against a known, fixed set of keys and URL shapes — **it is not a certification that every sensitive value is caught.** If Facebook adds a new token-shaped field with a name this list doesn't know about, or a sensitive value shows up somewhere other than a recognized key/URL shape, it will pass through unscrubbed. `--raw --no-redact` exists precisely because sometimes you need the truly raw node to debug a parser issue — treat anything produced that way as sensitive, ephemeral, and not for sharing. Redaction reduces the chance of an *accidental* leak into a bug report, a terminal screenshot, or scrollback history; it does not make output safe to publish or share.

## Third-party data and "you may become a data controller"

Every post you capture belongs to someone else — the author, and often commenters, tagged people, or anyone mentioned. [DISCLAIMER.md §3](../DISCLAIMER.md) frames this correctly: collecting identifiable personal data about other people can make *you* a data controller under GDPR, CCPA, or similar frameworks, with real, not hypothetical, obligations attached.

Practically, that means:

- **Retention:** don't keep captured output longer than you actually need it for. "I might want this later" is not a retention policy other people's data is entitled to wait around for.
- **Deletion:** delete output files once you're done with whatever you captured them for. There's no built-in expiry or cleanup — the tool writes a file and steps away; the deletion decision is yours, on an ongoing basis, not a one-time step.
- **Not sharing outputs:** because `--output` is deliberately full and unredacted (see above), never post it, attach it to an issue, paste it into a chat, or otherwise hand it to anyone else, even for something as reasonable-sounding as "can you help me debug this parse." If you need to share a capture for debugging, redact it by hand first, or better, reduce it to a synthetic/anonymized minimal repro.
- **"Personal use" is not automatically a lawful basis.** The MIT license on this code says nothing about, and does not excuse, whatever privacy-law obligations attach to the *data* you collect with it — that's a separate legal question from whether you're allowed to run the software.

## Supply chain

This tool's real-browser approach means its trust boundary includes more than its own source. It depends on:

- **[scrapling](https://github.com/D4Vinci/Scrapling)** — the fetch/session layer this tool builds on.
- **patchright/playwright** — the browser-automation drivers scrapling uses underneath.
- **A Chromium download from Google's CDN**, fetched by `scrape-fb setup` into this tool's own isolated browser cache (see [Installation](Installation.md)) — this is a real binary, hundreds of megabytes, pulled from Google's infrastructure at install time, not vendored or reviewed by this project.

Using this tool means trusting all of the above, not just this package's own code. None of it is unusual for a Playwright-based tool, but it's worth naming explicitly: a compromise anywhere in that chain (scrapling, patchright/playwright, or the Chromium binary itself) runs with the same access your logged-in session has.

## Maintainer exposure

This package is published under a real, named GitHub identity via PyPI's [Trusted Publishing](https://docs.pypi.org/trusted-publishers/), which cryptographically binds each release to a specific GitHub repository and account — there's no anonymous or pseudonymous publishing path here. [DISCLAIMER.md §2](../DISCLAIMER.md) covers this in full; the short version is that this was a deliberate, informed choice by the maintainer, made with the tradeoff (identifiability vs. the supply-chain integrity Trusted Publishing buys) explicit and on the record, not an oversight.

## If you find a security issue

Open a [GitHub issue](https://github.com/tjdwls101010/Scraper-for-Facebook/issues) on the repo.

Worth keeping in perspective: this is a scraper for a login-walled personal social network, not a hosted service. There's no server this project runs, no multi-tenant data store, no API this project exposes to anyone else — it runs entirely on your own machine, against your own already-authenticated session, and writes output only to your own disk. The threat surface is narrow and self-contained by construction; most of what can go wrong is covered above (profile-directory exposure, incomplete redaction, or an unreviewed dependency), not a remote attack on some service this project operates, because no such service exists.
