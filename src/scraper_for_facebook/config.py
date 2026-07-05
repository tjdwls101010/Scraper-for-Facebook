"""Defaults and the one non-bypassable guardrail (see plan §9).

Everything here is a soft, overridable default except ``MIN_SCROLL_PAUSE_SECONDS``,
which ``clamp_scroll_pause`` enforces regardless of what the caller asks for.
"""

from __future__ import annotations

import sys
from pathlib import Path

import platformdirs

APP_NAME = "scraper-for-facebook"

#: capture_xhr regex passed to scrapling's DynamicSession — proven during planning;
#: the tighter-looking r"/api/graphql/" under-captures.
CAPTURE_XHR_PATTERN = r"graphql"

DEFAULT_PROFILE_NAME = "default"

#: Non-bypassable floor: 0-delay scrolling is both the most ban-inducing setting
#: and the thing that makes this a mass-scraping tool rather than a personal one.
MIN_SCROLL_PAUSE_SECONDS = 0.5

DEFAULT_SCROLL_PAUSE = (2.0, 4.0)
DEFAULT_MAX_SCROLLS = 40

ENV_PROFILE_DIR = "SFB_PROFILE_DIR"


def browsers_dir() -> Path:
    """Isolated Playwright browser cache — never shared with any other tool's
    browser install (plan §14/§16 G-cache-isolation)."""
    return Path(platformdirs.user_data_dir(APP_NAME)) / "browsers"


def default_output_dir() -> Path:
    """Never cwd, never a repo — captured posts carry third-party PII (plan §10)."""
    return Path(platformdirs.user_data_dir(APP_NAME)) / "output"


def clamp_scroll_pause(pause: tuple[float, float]) -> tuple[float, float]:
    """Enforce the non-bypassable minimum inter-scroll delay.

    A ``(min, max)`` pair below the floor is silently raised to it, with a stderr
    note — this is the one hard limit in the tool, so it must actually apply no
    matter how the pair arrives (CLI flag, env, or direct API call).
    """
    lo, hi = pause
    clamped_lo = max(lo, MIN_SCROLL_PAUSE_SECONDS)
    clamped_hi = max(hi, clamped_lo)
    if clamped_lo != lo or clamped_hi != hi:
        print(
            f"scrape-fb: --scroll-pause {lo},{hi} raised to {clamped_lo},{clamped_hi} "
            f"(minimum is {MIN_SCROLL_PAUSE_SECONDS}s)",
            file=sys.stderr,
        )
    return (clamped_lo, clamped_hi)
