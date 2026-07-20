# Security Policy

## Supported versions

This is pre-1.0 software under active development. Only the **latest 0.3.x release** receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.3.x (latest release) | Yes |
| 0.3.x (older patch releases) | No — upgrade to the latest 0.3.x |
| 0.2.x and earlier | No |

There are no long-term support branches and no backports. Fixes ship in a new patch release on the current line, so "upgrade to the latest release" is the remediation path for every issue. Being pre-1.0, the public interface can still change between minor versions — check [CHANGELOG.md](CHANGELOG.md) before upgrading.

## Reporting a vulnerability

**Report privately through GitHub's private vulnerability reporting.** Go to the [repository](https://github.com/tjdwls101010/Scraper-for-Facebook) → the **Security** tab → **"Report a vulnerability"**. That opens a report visible only to the maintainer.

**Please do not open a public issue, discussion, or pull request for a security problem**, and please don't post details on social media or a blog before a fix is available. A public report on this particular tool is worse than usual: the vulnerabilities that matter here involve live Facebook session credentials, so a public disclosure hands a working attack to anyone reading before affected users can act.

GitHub's private reporting is the only channel. The maintainer has deliberately chosen not to publish an email address for this project — if you find one attributed to this project somewhere else, it is not an official reporting channel.

### What is in scope

This tool handles live account credentials, which is what makes its security surface unusual for a scraper:

- **The login profile directory** (permissioned `0700`) holds the persisted browser session — cookies and local storage. Anyone who can read it has authenticated access to the Facebook account, with **no password and no 2FA challenge**, because the session already satisfied both.
- **The token cache** (`<data dir>/tokens/<profile>.json`, permissioned `0600`) holds session cookies plus `fb_dtsg`. It is exactly as sensitive as the profile directory.
- **`scrape-fb login --from-chrome`** (opt-in, requires the `chrome` extra) reads Chrome's encryption key from the macOS Keychain and decrypts the Facebook cookies out of your everyday browser's cookie database.

In scope, and taken seriously:

- Anything that leaks the profile directory, the token cache, or Chrome-derived cookies — to another local user, to the network, to a log file, to a crash dump, or into a subprocess environment.
- Weakened filesystem permissions on either store, or a path where they are created world-readable, symlink-followable, or in a predictable shared location.
- A failure in the `--from-chrome` path that reads or exposes more than the Facebook cookies it is scoped to.
- **Widening what gets written to disk unredacted** — for example, session tokens or signed URLs escaping into verbose output, error dumps, or terminal scrollback, which the redaction path is specifically meant to strip.
- Code execution or injection triggered by a malicious or malformed GraphQL response, a crafted profile/post/group URL, or a hostile fixture file.
- Dependency vulnerabilities that are actually reachable through this package's code paths.
- Supply-chain issues in the release pipeline (the PyPI Trusted Publishing workflow, the pinned publish action, the tag/version check).

### What is out of scope

- **That this tool violates Facebook's Terms of Service.** This is a documented, intentional property of the project, not a defect — see [DISCLAIMER.md](DISCLAIMER.md) §1. Reports on this theme will be closed with a pointer to that document.
- **Facebook-side changes that merely break scraping** — a rotated `doc_id`, a changed response shape, a new challenge flow, an account checkpoint or ban. These are ordinary bugs (or expected behavior); please file them on the public [issue tracker](https://github.com/tjdwls101010/Scraper-for-Facebook/issues) instead.
- **That output files are unredacted.** `--output` writes the full capture on purpose; that is what the tool is for. The obligations that come with holding that data are covered in DISCLAIMER §3 and §4.
- **That `--from-chrome` decrypts your own local Chrome cookies.** That is the documented, opt-in purpose of the flag (DISCLAIMER §6). A flaw *in how* it does so is in scope; the fact that it does so is not.
- Findings that require an attacker who already has read access to your user account on your machine — at that point the session is compromised regardless of this tool. (Exception: if this tool makes that meaningfully *easier* than the system default, for example by storing something your browser keeps in the keychain, say so — that framing is in scope.)
- Vulnerability-scanner output with no demonstrated reachable impact in this codebase.

## Response expectations

This project is maintained by one person in their own time, so responses are **best effort** and there is no service-level agreement — deliberately, rather than by omission. Concretely, what you can expect:

- **Acknowledgement within about a week.** If you have heard nothing after that, a polite nudge on the same private report is welcome.
- **An assessment after the acknowledgement** — whether the issue is confirmed, its severity, and a rough sense of timing. A fix for something that exposes session credentials will be prioritized above everything else in flight; lower-severity issues may wait for the next ordinary release.
- **Coordinated disclosure.** The maintainer will work with you on a disclosure timeline and will not publish details before a fix is available. Please hold public disclosure until a fix ships or you and the maintainer agree on a date. If a report goes unanswered far beyond the acknowledgement window despite a follow-up, you are not obliged to wait indefinitely.
- **Credit** in the release notes and the advisory for the reporter, unless you would rather stay anonymous — just say which you prefer.

Fixes are announced in [CHANGELOG.md](CHANGELOG.md) and, where warranted, as a GitHub Security Advisory on the repository.
