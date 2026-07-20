"""Browser session mechanics: login persistence, status checks, setup, doctor
(plan §7, §14, §16).

``DynamicSession`` launches via vanilla Playwright (verified against
scrapling 0.4.10 source: ``playwright.chromium.launch_persistent_context``) —
not patchright. Patchright backs a separate, unused-here ``StealthySession``
fetcher. Worth knowing if checkpoint/detection risk ever needs revisiting.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from scrapling.fetchers import DynamicSession

from .config import CAPTURE_XHR_PATTERN, browsers_dir
from .profiles import ensure_profile_dir

# Playwright reads this from the process environment at browser-launch time.
# Set it before any DynamicSession is constructed so the browser cache is
# never shared with another tool's Playwright/patchright install (plan §14,
# §16 G-cache-isolation) — e.g. the web-fetch skill's own fetch venv.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_dir()))

_META_FILENAME = ".scrape_fb_meta.json"


class Status(Enum):
    LOGGED_IN = "logged_in"
    EXPIRED = "expired"
    CHECKPOINT = "checkpoint"


#: Markers of the login form Facebook serves **in place**, at ``/``, with HTTP
#: 200 and no redirect (recon §5.1). Confirmed live: a 15-day-old dead session
#: rendered these while ``status`` happily reported ``logged_in``.
_LOGIN_FORM_MARKERS = (
    "caa_login_form_data",
    "CAAFetaAYMHPasswordEntryQuery",
    "COMET_HEADLESS_LOGIN",
)

#: What every logged-in page carries. Its absence is the positive test that
#: catches logged-out shapes no marker list anticipated.
_LOGGED_IN_MARKER = '"DTSGInitialData"'


def detect_wall(url: str, html: str | None = None) -> str | None:
    """ "checkpoint" | "login" | None for the current page.

    The URL alone is not sufficient and was the source of a real false
    positive: Facebook serves the login form at ``https://www.facebook.com/``
    with HTTP 200 and **no redirect**, so a URL check sees a perfectly healthy
    page and reports a dead session as live (recon §5.1). When ``html`` is
    supplied the response body is checked too — both for login-form markers and
    for the *absence* of the token every logged-in page carries.
    """
    if "/checkpoint/" in url:
        return "checkpoint"
    if "/login" in url:
        return "login"
    if html is not None:
        if any(marker in html for marker in _LOGIN_FORM_MARKERS):
            return "login"
        if _LOGGED_IN_MARKER not in html:
            return "login"
    return None


def looks_logged_in(html: str, cookie_names: Iterable[str]) -> bool:
    """Whether a loaded page is a genuinely logged-in one."""
    return (
        _LOGGED_IN_MARKER in html
        and "c_user" in set(cookie_names)
        and not any(marker in html for marker in _LOGIN_FORM_MARKERS)
    )


def _meta_path(profile_dir: Path) -> Path:
    return profile_dir / _META_FILENAME


def _write_login_meta(profile_dir: Path) -> None:
    _meta_path(profile_dir).write_text(
        json.dumps({"logged_in_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )


def session_age_seconds(profile_dir: Path) -> float | None:
    """Seconds since the last successful ``scrape-fb login``, or ``None`` if unknown."""
    meta_path = _meta_path(profile_dir)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        logged_in_at = datetime.fromisoformat(data["logged_in_at"])
    except (OSError, ValueError, KeyError):
        return None
    return (datetime.now(UTC) - logged_in_at).total_seconds()


def build_session(profile_dir: Path, *, headless: bool) -> DynamicSession:
    # Every caller needs a profile dir that exists with the right permissions
    # before Chromium touches it — enforce it here once rather than trusting
    # each call site to remember (plan §7: it's a live session credential).
    ensure_profile_dir(profile_dir)
    return DynamicSession(
        user_data_dir=str(profile_dir),
        headless=headless,
        capture_xhr=CAPTURE_XHR_PATTERN,
    )


def run_login(profile_dir: Path, *, timeout_seconds: float = 300.0) -> bool:
    """Headed interactive login. Returns True once the session is really logged in.

    The wait has to happen INSIDE ``page_action`` — scrapling closes the page
    the instant ``fetch()`` returns (its ``_page_generator`` calls
    ``page.close()`` on exit), so waiting *after* ``fetch()`` would be waiting
    on a window that already closed.

    Waits by **polling the browser's own state** rather than blocking on
    ``input()``. The old prompt required a human at a TTY: under a
    non-interactive driver it hung forever holding the Chromium profile lock,
    which blocked every subsequent browser launch (recon §5.3). Polling lets an
    agent drive login and simply time out instead of deadlocking.
    """
    state = {"logged_in": False}

    def wait_for_login(page) -> None:
        print(
            "A browser window is open. Log in to Facebook there — this will "
            f"continue automatically once you are (waiting up to {timeout_seconds:.0f}s).",
            file=sys.stderr,
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                cookies = [c["name"] for c in page.context.cookies()]
                if looks_logged_in(page.content(), cookies):
                    state["logged_in"] = True
                    # Facebook finishes writing session cookies a beat after the
                    # feed renders; leaving immediately can persist a half-built
                    # profile that then reads as logged out.
                    page.wait_for_timeout(2000)
                    return
            except Exception:  # noqa: BLE001 - mid-navigation reads race; just retry
                pass
            page.wait_for_timeout(2000)
        print("Timed out waiting for login.", file=sys.stderr)

    with build_session(profile_dir, headless=False) as session:
        session.fetch("https://www.facebook.com/", page_action=wait_for_login, timeout=60000)

    if not state["logged_in"]:
        return False
    _write_login_meta(profile_dir)
    return True


def run_status(profile_dir: Path) -> Status:
    if not profile_dir.exists():
        return Status.EXPIRED

    holder: dict = {}

    def _capture(page) -> None:
        holder["html"] = page.content()

    with build_session(profile_dir, headless=True) as session:
        response = session.fetch("https://www.facebook.com/", page_action=_capture, timeout=60000)

    wall = detect_wall(response.url, holder.get("html"))
    if wall == "checkpoint":
        return Status.CHECKPOINT
    if wall == "login":
        return Status.EXPIRED
    return Status.LOGGED_IN


def run_doctor(profile_dir: Path) -> tuple[bool, str]:
    """Launch the browser and confirm a capture actually round-trips.

    A real functional check (browser launches, navigates, captures at least
    one matching XHR) rather than a ``--version``-style stand-in that only
    proves the entry point imports (plan §16).
    """
    try:
        with build_session(profile_dir, headless=True) as session:
            response = session.fetch("https://www.facebook.com/", timeout=60000)
    except Exception as exc:  # noqa: BLE001 - surfacing any failure is the point of `doctor`
        return False, f"browser launch/navigation failed: {exc}"
    if not response.captured_xhr:
        return False, "browser launched and navigated, but no graphql XHR was captured"
    return True, f"OK - captured {len(response.captured_xhr)} graphql response(s)"


def run_setup(*, force: bool = False) -> None:
    """Provision the browser into our isolated ``PLAYWRIGHT_BROWSERS_PATH`` (plan §14).

    Invokes scrapling's own documented ``scrapling install`` mechanism
    in-process rather than shelling out to a bare ``scrapling`` command:
    under an isolated install (``uv tool``/``pipx``), only THIS package's own
    console script (``scrape-fb``) is guaranteed to be on PATH — scrapling's
    ``scrapling`` script is not exposed by the tool installer, so invoking it
    by name would fail there even though it works in a plain dev venv.
    """
    browsers_dir().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir())
    args = ["install"]
    if force:
        args.append("--force")
    subprocess.run(
        [sys.executable, "-c", "from scrapling.cli import main; main()", *args],
        env=env,
        check=True,
    )
