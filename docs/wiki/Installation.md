# Installation

## Why an isolated install is mandatory

`scraper-for-facebook` depends on `scrapling[fetchers]>=0.4.9,<0.5`, which in turn pins exact Playwright/patchright versions to match the browser build it drives. If you `pip install` this into a general-purpose virtualenv that already has (or later gets) a different Playwright version for some other project, one of two things happens: the resolver fails outright, or it "succeeds" and quietly leaves one tool pointed at a Playwright version/browser build it wasn't built against. Either way you find out at runtime, usually as a confusing browser-launch error that has nothing to do with your actual code.

The fix is to never let this package share a Python environment with anything else. That's what `uv tool install` and `pipx` are for: each gives `scrape-fb` its own private virtualenv, so its pinned `scrapling`/Playwright versions can never collide with another project's.

**Do not** run `pip install scraper-for-facebook` into a shared venv — the one you use for other projects, or your system Python. It will work today and become a debugging session later.

## Install

Pick one. Both give you an isolated environment and put the `scrape-fb` command on your `PATH`.

**uv (recommended if you have it):**

```bash
uv tool install scraper-for-facebook
```

**pipx:**

```bash
pipx install scraper-for-facebook
```

Either way, requires Python 3.11, 3.12, or 3.13.

## Set up the browser

Installing the package does not install a browser — that's a separate step, and it's separate on purpose (see [Why an isolated install is mandatory](#why-an-isolated-install-is-mandatory) above: browser provisioning is exactly the part that must stay isolated).

```bash
scrape-fb setup
```

This provisions a Chromium build into a cache directory this tool owns exclusively — set via `PLAYWRIGHT_BROWSERS_PATH`, under this package's own `platformdirs` data directory — so it never touches, shares, or gets confused with a Playwright/patchright browser cache any other tool on your machine manages. Under the hood it calls `scrapling`'s own install routine in-process rather than shelling out to a bare `scrapling` command, because under a `uv tool`/`pipx` install, only `scrape-fb` itself is guaranteed to be on your `PATH` — `scrapling`'s own console script isn't exposed there.

If you need to force a clean reinstall of the browser (e.g. it got corrupted, or you're troubleshooting):

```bash
scrape-fb setup --force
```

### Verify it worked

```bash
scrape-fb doctor
```

This is a real functional check, not a version stand-in: it launches the isolated browser headless, navigates to facebook.com, and confirms at least one `graphql` XHR response was actually captured. Exit code `0` and a `captured N graphql response(s)` message means the browser is provisioned correctly and the capture pipeline works end-to-end. Anything else prints what failed (e.g. the browser never launched, or navigation succeeded but nothing was captured) — see [FAQ & Troubleshooting](FAQ-and-Troubleshooting.md) if `doctor` doesn't come back clean.

Note that `doctor` checks the browser/capture pipeline, not login state — you can run it before `scrape-fb login` and it will still report a working capture pipeline against Facebook's logged-out page. See [Quick Start](Quick-Start.md) for the full first-run flow (`login` → `doctor` → `fetch`).

## Platform support

| Platform | Status |
|---|---|
| macOS | Tested, first-class target (v1). This is what CI actually exercises against the real browser layer today. |
| Linux | Untested against a live Facebook session. The fixture/parse/CLI layer (everything that doesn't touch a real logged-in browser) runs in CI on `ubuntu-latest` alongside macOS, so that slice is verified cross-platform — but no CI leg installs an actual browser binary or hits live Facebook, on either OS. |
| Windows | Unsupported. Not in the `pyproject.toml` classifiers, not in the CI matrix, and the smoke-test tooling assumes a POSIX venv layout (`bin/`, not `Scripts\`). |

If you're on Linux and hit something macOS doesn't, that's expected territory — file an issue with what you saw.

## Upgrading

```bash
uv tool upgrade scraper-for-facebook
# or
pipx upgrade scraper-for-facebook
```

Because `scrape-fb setup` provisions a Chromium build tied to the `scrapling`/Playwright version pinned in this package, an upgrade that bumps `scrapling` can leave your existing browser provisioning mismatched with the new version. If `scrape-fb doctor` fails after an upgrade, re-run setup:

```bash
scrape-fb setup --force
```

## Uninstalling

```bash
uv tool uninstall scraper-for-facebook
# or
pipx uninstall scraper-for-facebook
```

This removes the package and its isolated environment, but it does **not** touch the browser cache or your login profile — both live outside the tool's own venv, under your `platformdirs` user data directory, so they survive an uninstall/reinstall cycle. If you want those gone too:

- **Browser cache** — the `PLAYWRIGHT_BROWSERS_PATH` this tool provisioned into (`scrape-fb setup`'s target directory).
- **Login profile** — remember that this directory holds a live, unencrypted Facebook session (see [DISCLAIMER.md §6](../DISCLAIMER.md)). If you're deleting it because the machine or disk may be compromised, that's not enough on its own — revoke the session from facebook.com (Settings → Security → Where You're Logged In) too.

Exact paths are platform- and username-dependent (`platformdirs` resolves them per-OS); run `scrape-fb status` or check your `platformdirs` user-data directory for `scraper-for-facebook` to find them on your machine. See [Configuration](Configuration.md) for how profile storage is resolved (including the `SFB_PROFILE_DIR` override) if you use a non-default location.

---

Next: [Quick Start](Quick-Start.md) walks through first login and your first fetch. For the full list of risks you're taking on before you go further, read [../DISCLAIMER.md](../DISCLAIMER.md).
