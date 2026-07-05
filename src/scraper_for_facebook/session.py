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


def detect_wall(url: str) -> str | None:
    """ "checkpoint" | "login" | None, from the current page URL.

    Best-effort pending live-probe validation (plan §7, §17 G-checkpoint) —
    the well-known Facebook redirect targets for an account checkpoint and a
    login wall, not yet confirmed against a live session from this codebase.
    """
    if "/checkpoint/" in url:
        return "checkpoint"
    if "/login" in url:
        return "login"
    return None


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


def run_login(profile_dir: Path) -> bool:
    """Headed interactive login. Returns True once no login wall is detected.

    The wait for the user to actually log in has to happen INSIDE
    ``page_action`` — scrapling closes the page the instant ``fetch()``
    returns (its ``_page_generator`` calls ``page.close()`` on exit), so
    prompting for input *after* ``fetch()`` would be prompting over a window
    that already closed.
    """

    def wait_for_manual_login(page) -> None:
        input(
            "A browser window should now be open. Log in to Facebook there, "
            "then press Enter here to continue... "
        )

    with build_session(profile_dir, headless=False) as session:
        response = session.fetch("https://www.facebook.com/", page_action=wait_for_manual_login)

    if detect_wall(response.url) is not None:
        return False
    _write_login_meta(profile_dir)
    return True


def run_status(profile_dir: Path) -> Status:
    if not profile_dir.exists():
        return Status.EXPIRED
    with build_session(profile_dir, headless=True) as session:
        response = session.fetch("https://www.facebook.com/", timeout=60000)
    wall = detect_wall(response.url)
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
