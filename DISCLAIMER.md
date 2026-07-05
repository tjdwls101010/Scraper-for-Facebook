# Disclaimer — read before you use this

This is not legal advice. It is a plain-language summary of risks you take on by using this tool. If any of this matters to your situation, talk to a lawyer.

## 1. This violates Facebook's Terms of Service

Automating any Meta account to collect data — including logging in with a real browser and reading what it loads — is against Facebook's Terms of Service. Meta enforces this via account bans (temporary or permanent), checkpoints/"login approval" challenges, cease-and-desist letters, and in some cases litigation. Using this tool is entirely at your own risk. Use a **dedicated or throwaway account**, not your primary one, and keep volume low (§9 of the design doc; the CLI's scroll-pause floor and per-run scope exist because of this).

## 2. Publishing this tool exposes its maintainer, not just its users

This package is named `scraper-for-facebook`, published under a real GitHub identity, and distributed via PyPI Trusted Publishing, which binds each release to a named GitHub repository and account. That is a deliberate, informed choice by the maintainer — but it means the maintainer is identifiable in a way an anonymous or unpublished tool would not be. Meta has previously pursued named authors and operators of public Facebook/Instagram scrapers, historically skewed toward commercial mass-scraping and data-broker operations rather than small personal-scale tools — but the exposure exists regardless of scale, and this is recorded here so the choice stays informed.

## 3. You may become a "data controller" for other people's data

Posts you scrape belong to other people — authors, commenters, anyone tagged or mentioned. Collecting identifiable personal data about other people can make *you* a data controller under GDPR, CCPA, or similar law, with real obligations: a lawful basis for processing, honoring data-subject access/deletion requests, and limiting retention. "I did this for personal use" is not automatically a lawful basis. Minimize what you keep, and delete captured output once you're done with it. The MIT license on this code says nothing about, and does not excuse, privacy-law obligations around the *data* you collect with it.

## 4. Output files are not scrubbed — treat them as sensitive

Captured posts contain third-party names, message text, and signed media URLs. This tool:
- never writes output to a location you'd casually commit to git (default `--output` is outside any repo; see README),
- never redacts the *output* files themselves (only diagnostic/verbose logs go through redaction — see below),
- relies on you to delete output you no longer need.

Don't commit scraped output to a public (or even private) git repository, and don't share it beyond what you'd be comfortable being responsible for under §3.

## 5. Diagnostics are redacted — but redaction is not a certification

`-v`/`--verbose` output, error dumps, and anything printed to your terminal are passed through a single redaction path that strips signed media URLs, token-shaped fields, and truncates message text. This reduces accidental leakage into terminal scrollback, bug reports, or screenshots — it is **not** a guarantee that every sensitive value is caught, and it does not apply to the actual `--output` file, which is the full, unredacted capture by design (that's the point of the tool). `--raw --no-redact` disables this path entirely for debugging; only use it locally.

## 6. Your login profile is a live, unencrypted session credential

`scrape-fb login` persists your Facebook session (cookies, local storage) to a directory on disk, permissioned `0700`. Anyone who can read that directory has authenticated access to your Facebook account — no password or 2FA required, because the session already satisfied both. This is **less** protected than your regular browser's keychain-encrypted cookie store. Concretely:
- **Do not** back this directory up to Time Machine, sync it via iCloud/Dropbox, or commit it anywhere.
- If the machine or disk is lost or compromised, **revoke the session immediately** by logging out of that session from facebook.com (Settings → Security → Where You're Logged In), not just by deleting the local directory.

## 7. No warranty

This software is provided "as is" under the MIT License, without warranty of any kind. See [LICENSE](LICENSE). Facebook's internal API can and does change without notice; this tool may stop working, or silently return incomplete data, at any time (see the design doc's durability section).
