#!/usr/bin/env python3
"""Capture real Facebook GraphQL response bodies to a gitignored scratch file.

For building synthetic fixtures or re-anchoring the parser after a Facebook
response-shape change (plan §12). Requires a profile already logged in via
``scrape-fb login``. Output is a real capture — NEVER commit it; only
``build_fixture.py``-derived synthetic skeletons belong in tests/fixtures/.

Usage: record_fixture.py <profile_url_or_username> [--profile NAME] [--limit N] [--headed]
Output: scratch/<name>.raw.ndjson
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scraper_for_facebook import profiles, scroll
from scraper_for_facebook.session import build_session

SCRATCH_DIR = Path(__file__).resolve().parent.parent / "scratch"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("identifier", help="Profile URL, vanity name, or numeric id.")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-scrolls", type=int, default=10)
    parser.add_argument("--output", default="capture", help="Output filename stem.")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    url = profiles.normalize_target_identifier(args.identifier)
    profile_dir = profiles.resolve_profile_dir(args.profile)

    scroll_action, outcome = scroll.make_scroll_action(
        scroll_pause=(2.0, 4.0), max_scrolls=args.max_scrolls, limit=args.limit, since=None
    )
    with build_session(profile_dir, headless=not args.headed) as session:
        response = session.fetch(url, page_action=scroll_action)

    if outcome.wall_detected:
        print(f"wall detected: {outcome.wall_detected} — is the profile logged in?")
        return 2
    if outcome.profile_unavailable:
        print("profile appears unavailable (memorialized/blocked/restricted/nonexistent)")
        return 5

    SCRATCH_DIR.mkdir(exist_ok=True)
    out_path = SCRATCH_DIR / f"{args.output}.raw.ndjson"
    with out_path.open("wb") as f:
        for xhr in response.captured_xhr:
            f.write(xhr.body)
            f.write(b"\n")

    print(f"Wrote {len(response.captured_xhr)} captured bodies to {out_path}")
    print(f"Stop reason: {outcome.stop_reason}, scrolls performed: {outcome.scrolls_performed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
