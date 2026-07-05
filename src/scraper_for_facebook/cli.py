"""``scrape-fb`` command-line entry point (plan §10)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from . import __version__, profiles, redact, retrieve, session
from .config import (
    DEFAULT_MAX_SCROLLS,
    DEFAULT_PROFILE_NAME,
    DEFAULT_SCROLL_PAUSE,
    default_output_dir,
)
from .errors import (
    ChallengeError,
    InvalidIdentifierError,
    LoginRequiredError,
    ProfileUnavailableError,
    SessionExpiredError,
)
from .model import Post
from .session import Status


def _parse_scroll_pause(value: str) -> tuple[float, float]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected MIN,MAX (e.g. 2.0,4.0), got {value!r}")
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--scroll-pause values must be numbers, got {value!r}"
        ) from None


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrape-fb", description="Scrape your own logged-in Facebook timeline."
    )
    parser.add_argument("--version", action="version", version=f"scrape-fb {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_p = subparsers.add_parser(
        "login", help="One-time interactive login (opens a real browser window)."
    )
    login_p.add_argument("--profile", default=DEFAULT_PROFILE_NAME)
    login_p.add_argument("--profile-dir", default=None)

    status_p = subparsers.add_parser("status", help="Check whether a profile is logged in.")
    status_p.add_argument("--profile", default=DEFAULT_PROFILE_NAME)
    status_p.add_argument("--profile-dir", default=None)
    status_p.add_argument("--json", action="store_true")

    setup_p = subparsers.add_parser("setup", help="Provision the browser into an isolated cache.")
    setup_p.add_argument(
        "--force", action="store_true", help="Reinstall even if already provisioned."
    )

    doctor_p = subparsers.add_parser(
        "doctor", help="Launch the browser and verify a capture round-trips."
    )
    doctor_p.add_argument("--profile", default=DEFAULT_PROFILE_NAME)
    doctor_p.add_argument("--profile-dir", default=None)

    fetch_p = subparsers.add_parser("fetch", help="Fetch posts from a profile timeline.")
    fetch_p.add_argument("identifier", help="Profile URL, vanity name, or numeric id.")
    fetch_p.add_argument("--profile", default=DEFAULT_PROFILE_NAME)
    fetch_p.add_argument("--profile-dir", default=None)
    fetch_p.add_argument("--limit", type=int, default=None)
    fetch_p.add_argument("--since", type=_parse_iso_date, default=None)
    fetch_p.add_argument("--until", type=_parse_iso_date, default=None)
    fetch_p.add_argument("--format", choices=["json", "ndjson"], default="json")
    fetch_p.add_argument("--output", default=None)
    fetch_p.add_argument("--scroll-pause", type=_parse_scroll_pause, default=DEFAULT_SCROLL_PAUSE)
    fetch_p.add_argument("--max-scrolls", type=int, default=DEFAULT_MAX_SCROLLS)
    fetch_p.add_argument("--headed", action="store_true", help="Show the browser (debugging).")
    fetch_p.add_argument(
        "--raw", action="store_true", help="Include the raw captured story node per post."
    )
    fetch_p.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable PII scrubbing on --raw output (prints an on-screen warning).",
    )
    fetch_p.add_argument("-v", "--verbose", action="store_true")

    return parser


def _cmd_login(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    if session.run_login(profile_dir):
        print(f"Logged in. Profile saved at {profile_dir}", file=sys.stderr)
        return 0
    print(
        "Could not verify login (still see a login wall). Try again: scrape-fb login",
        file=sys.stderr,
    )
    return 2


_STATUS_EXIT_CODES = {Status.LOGGED_IN: 0, Status.EXPIRED: 2, Status.CHECKPOINT: 3}


def _cmd_status(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    status = session.run_status(profile_dir)
    age = session.session_age_seconds(profile_dir)
    if args.json:
        print(json.dumps({"status": status.value, "session_age_seconds": age}))
    else:
        age_str = f"{age:.0f}s ago" if age is not None else "unknown"
        print(f"status: {status.value} (logged in {age_str})", file=sys.stderr)
    return _STATUS_EXIT_CODES[status]


def _cmd_setup(args: argparse.Namespace) -> int:
    try:
        session.run_setup(force=args.force)
    except Exception as exc:
        print(redact.redact_raw_text(f"setup failed: {exc}"), file=sys.stderr)
        return 1
    print("Browser provisioned.", file=sys.stderr)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    ok, message = session.run_doctor(profile_dir)
    print(redact.redact_raw_text(message), file=sys.stderr)
    return 0 if ok else 1


def _default_output_path(identifier: str, fmt: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_identifier = re.sub(r"[^A-Za-z0-9]+", "-", identifier).strip("-") or "profile"
    ext = "ndjson" if fmt == "ndjson" else "json"
    return default_output_dir() / f"{safe_identifier}-{timestamp}.{ext}"


def _write_output(posts: list[Post], path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "ndjson":
        with path.open("w", encoding="utf-8") as fh:
            for post in posts:
                fh.write(json.dumps(post.to_dict(), ensure_ascii=False))
                fh.write("\n")
    else:
        with path.open("w", encoding="utf-8") as fh:
            json.dump([post.to_dict() for post in posts], fh, ensure_ascii=False, indent=2)


def _cmd_fetch(args: argparse.Namespace) -> int:
    try:
        normalized_url = profiles.normalize_target_identifier(args.identifier)
    except InvalidIdentifierError as exc:
        print(f"invalid identifier: {exc}", file=sys.stderr)
        return 1

    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)

    try:
        result = retrieve.fetch_profile(
            normalized_url,
            profile_dir=profile_dir,
            headless=not args.headed,
            limit=args.limit,
            since=args.since,
            until=args.until,
            scroll_pause=args.scroll_pause,
            max_scrolls=args.max_scrolls,
            raw=args.raw,
        )
    except (LoginRequiredError, SessionExpiredError) as exc:
        print(f"{exc} Run: scrape-fb login --profile {args.profile}", file=sys.stderr)
        return 2
    except ChallengeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ProfileUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except Exception as exc:  # noqa: BLE001 - last-resort CLI boundary
        if args.verbose:
            print(redact.redact_raw_text(f"unexpected error: {exc}"), file=sys.stderr)
        else:
            print(
                f"unexpected error: {type(exc).__name__} (rerun with -v for details)",
                file=sys.stderr,
            )
        return 1

    if not result.posts:
        print(
            f"0 posts retrieved (stop reason: {result.stop_reason}). If this profile is "
            "known-good, this may indicate a Facebook response-shape change — see "
            "https://github.com/tjdwls101010/Scraper-for-Facebook/issues",
            file=sys.stderr,
        )
        return 4

    if args.raw:
        if args.no_redact:
            print(
                "WARNING: --no-redact leaves --raw output unscrubbed. The saved file "
                "will contain unredacted third-party data. See DISCLAIMER.md.",
                file=sys.stderr,
            )
        else:
            for post in result.posts:
                if post.raw is not None:
                    post.raw = redact.redact(post.raw)

    output_path = (
        Path(args.output) if args.output else _default_output_path(args.identifier, args.format)
    )
    _write_output(result.posts, output_path, args.format)

    exit_code = 7 if (args.since is not None and not result.since_reached) else 0
    oldest = result.oldest_seen.date().isoformat() if result.oldest_seen else "unknown"
    newest = result.newest_seen.date().isoformat() if result.newest_seen else "unknown"
    reached_note = "" if result.since_reached else " (requested --since NOT confirmed reached)"
    print(
        f"{len(result.posts)} posts, range {oldest}..{newest}, stop reason: "
        f"{result.stop_reason}{reached_note}. Saved to {output_path}",
        file=sys.stderr,
    )
    return exit_code


_HANDLERS = {
    "login": _cmd_login,
    "status": _cmd_status,
    "setup": _cmd_setup,
    "doctor": _cmd_doctor,
    "fetch": _cmd_fetch,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
