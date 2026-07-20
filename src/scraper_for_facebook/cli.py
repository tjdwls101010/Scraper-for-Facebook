"""``scrape-fb`` command-line entry point (plan §10)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from . import __version__, catalog, exits, profiles, redact, retrieve, scroll, session, tokens
from .comments import json_schema as comment_json_schema
from .comments import schema_fields as comment_schema_fields
from .config import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_SCROLLS,
    DEFAULT_PROFILE_NAME,
    DEFAULT_REQUEST_INTERVAL,
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
from .model import Post, json_schema, schema_fields
from .queries import COMMENT_SORT_TOKENS
from .search import SEARCH_EXPERIENCE_TYPES
from .search import json_schema as entity_json_schema
from .search import schema_fields as entity_schema_fields
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


_PROFILE_DIR_HELP = (
    "Override where this profile's browser data lives "
    "(default: platform data dir, or $SFB_PROFILE_DIR)."
)


def _add_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="Named login session to use (default: 'default').",
    )
    parser.add_argument("--profile-dir", default=None, help=_PROFILE_DIR_HELP)


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    """The output contract every retrieval command shares (plan §4)."""
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after this many results (default: unbounded)."
    )
    parser.add_argument(
        "--format",
        choices=["json", "ndjson"],
        default="json",
        help="A single pretty-printed JSON array, or one NDJSON object per line (default: json).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Where to write results (default: a timestamped file under the "
            "platform data dir, not cwd)."
        ),
    )
    parser.add_argument(
        "--raw", action="store_true", help="Include the raw captured node per result."
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Disable PII scrubbing on --raw output (prints an on-screen warning).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Print the full (still redaction-scrubbed) error text instead of "
            "just the exception type name."
        ),
    )


def _add_active_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--request-interval",
        type=_parse_scroll_pause,
        default=DEFAULT_REQUEST_INTERVAL,
        help=(
            "MIN,MAX seconds between active-mode requests; MIN is clamped to >= 1.0s "
            "and cannot be bypassed (default: 1.0,2.0)."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Active-mode pagination ceiling (default: {DEFAULT_MAX_PAGES}).",
    )
    parser.add_argument("--headed", action="store_true", help="Show the browser (debugging).")


class _ArgumentParser(argparse.ArgumentParser):
    """Usage errors (bad flags, missing args) exit 1, not argparse's default 2.

    Exit code 2 already means "login required or session expired" in this
    CLI's contract — a caller scripting against exit codes couldn't otherwise
    tell a typo'd `--since` from an expired session.
    """

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="scrape-fb", description="Scrape your own logged-in Facebook timeline."
    )
    parser.add_argument("--version", action="version", version=f"scrape-fb {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_p = subparsers.add_parser(
        "login", help="One-time interactive login (opens a real browser window)."
    )
    login_p.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="Named login session to save (default: 'default').",
    )
    login_p.add_argument(
        "--profile-dir",
        default=None,
        help=_PROFILE_DIR_HELP,
    )
    login_p.add_argument(
        "--timeout-seconds",
        type=float,
        default=300.0,
        help=(
            "How long to wait for you to finish logging in before giving up "
            "(default: 300). Login completion is detected automatically."
        ),
    )
    login_p.add_argument(
        "--from-chrome",
        action="store_true",
        help=(
            "Opt-in: import an existing Facebook session from your local Chrome instead "
            "of logging in. This decrypts Chrome's cookies via the Keychain (may prompt) "
            "and usually means importing your MAIN account — against this tool's "
            "throwaway-account guidance. Needs: pip install 'scraper-for-facebook[chrome]'."
        ),
    )
    login_p.add_argument(
        "--chrome-profile",
        default="Default",
        help="Which Chrome profile to import from (default: Default).",
    )

    status_p = subparsers.add_parser("status", help="Check whether a profile is logged in.")
    status_p.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="Named login session to check (default: 'default').",
    )
    status_p.add_argument(
        "--profile-dir",
        default=None,
        help=_PROFILE_DIR_HELP,
    )
    status_p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout instead of a human summary to stderr.",
    )

    setup_p = subparsers.add_parser("setup", help="Provision the browser into an isolated cache.")
    setup_p.add_argument(
        "--force", action="store_true", help="Reinstall even if already provisioned."
    )

    doctor_p = subparsers.add_parser(
        "doctor", help="Launch the browser and verify a capture round-trips."
    )
    doctor_p.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="Named login session to check (default: 'default').",
    )
    doctor_p.add_argument(
        "--profile-dir",
        default=None,
        help=_PROFILE_DIR_HELP,
    )

    schema_p = subparsers.add_parser(
        "schema", help="Print the fetch output object schema (offline, no login needed)."
    )
    schema_p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON Schema (draft 2020-12) instead of a plain annotated listing.",
    )

    catalog_p = subparsers.add_parser(
        "catalog",
        help=(
            "Describe this CLI to a caller: every command, its flags, the exit codes, "
            "the output contract, and known limitations (offline, no login needed)."
        ),
    )
    catalog_p.add_argument(
        "--json",
        action="store_true",
        help="Emit the catalog as JSON for programmatic use instead of a text listing.",
    )

    fetch_p = subparsers.add_parser("fetch", help="Fetch posts from a profile timeline.")
    fetch_p.add_argument("identifier", help="Profile URL, vanity name, or numeric id.")
    _add_profile_args(fetch_p)
    _add_output_args(fetch_p)
    _add_active_args(fetch_p)
    fetch_p.add_argument(
        "--since",
        type=_parse_iso_date,
        default=None,
        help=(
            "Keep posts on/after this date YYYY-MM-DD. Precise in active mode "
            "(server-side filter); best-effort within --max-scrolls when passive (see exit 7)."
        ),
    )
    fetch_p.add_argument(
        "--until",
        type=_parse_iso_date,
        default=None,
        help="Keep posts on/before this date YYYY-MM-DD.",
    )
    fetch_p.add_argument(
        "--mode",
        choices=["auto", "active", "passive"],
        default="auto",
        help=(
            "Transport: 'active' reads the GraphQL API over HTTP (fast, precise dates), "
            "'passive' scrolls a browser, 'auto' tries active and falls back (default: auto)."
        ),
    )
    fetch_p.add_argument(
        "--scroll-pause",
        type=_parse_scroll_pause,
        default=DEFAULT_SCROLL_PAUSE,
        help=(
            "Passive mode only. MIN,MAX seconds between scrolls; MIN is clamped to "
            ">= 0.5s and cannot be bypassed (default: 2.0,4.0)."
        ),
    )
    fetch_p.add_argument(
        "--max-scrolls",
        type=int,
        default=DEFAULT_MAX_SCROLLS,
        help=(
            "Passive mode only. Scroll-iteration ceiling; if the budget runs out before "
            "--limit/--since is met, the run stops with them unmet (default: 40)."
        ),
    )

    feed_p = subparsers.add_parser("feed", help="Fetch posts from your home news feed.")
    _add_profile_args(feed_p)
    _add_output_args(feed_p)
    _add_active_args(feed_p)

    comments_p = subparsers.add_parser("comments", help="Fetch comments on a post.")
    comments_p.add_argument("url", help="Post permalink URL.")
    _add_profile_args(comments_p)
    _add_output_args(comments_p)
    _add_active_args(comments_p)
    comments_p.add_argument(
        "--sort",
        choices=sorted(COMMENT_SORT_TOKENS),
        default="top",
        help="Comment ordering (default: top).",
    )
    comments_p.add_argument(
        "--replies",
        action="store_true",
        help=(
            "Also fetch replies (depth >= 1). Costs one extra request per commented "
            "comment — replies are never returned inline."
        ),
    )

    post_p = subparsers.add_parser("post", help="Fetch a single post by permalink URL.")
    post_p.add_argument("url", help="Post permalink URL.")
    _add_profile_args(post_p)
    _add_output_args(post_p)
    _add_active_args(post_p)

    search_p = subparsers.add_parser("search", help="Search Facebook.")
    search_p.add_argument("query", help="Search text.")
    _add_profile_args(search_p)
    _add_output_args(search_p)
    _add_active_args(search_p)
    search_p.add_argument(
        "--type",
        dest="search_type",
        choices=sorted(SEARCH_EXPERIENCE_TYPES),
        default="top",
        help=(
            "Which vertical to search (default: top). 'top'/'posts' return Posts; "
            "'people'/'pages'/'groups' return Entity records."
        ),
    )

    group_p = subparsers.add_parser("group", help="Fetch posts from a group's feed.")
    group_p.add_argument("identifier", help="Group URL, vanity slug, or numeric id.")
    _add_profile_args(group_p)
    _add_output_args(group_p)
    _add_active_args(group_p)

    return parser


def _cmd_login(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)

    if args.from_chrome:
        try:
            imported = tokens.from_chrome(args.chrome_profile)
            tokens.save_cached(args.profile, imported)
        except Exception as exc:
            print(redact.redact_raw_text(f"chrome import failed: {exc}"), file=sys.stderr)
            return 2
        print(
            f"Imported a Facebook session from Chrome profile {args.chrome_profile!r} "
            f"(user {imported.user_id}). Active-mode commands will use it.\n"
            "NOTE: this is your real Chrome account — see DISCLAIMER.md on ban risk.",
            file=sys.stderr,
        )
        return 0

    try:
        logged_in = session.run_login(profile_dir, timeout_seconds=args.timeout_seconds)
    except Exception as exc:
        print(redact.redact_raw_text(f"login failed: {exc}"), file=sys.stderr)
        return 1
    if logged_in:
        print(f"Logged in. Profile saved at {profile_dir}", file=sys.stderr)
        return 0
    print(
        "Could not verify login (still see a login wall). Try again: scrape-fb login",
        file=sys.stderr,
    )
    return 2


_STATUS_EXIT_CODES = {
    Status.LOGGED_IN: exits.OK,
    Status.EXPIRED: exits.LOGIN_REQUIRED,
    Status.CHECKPOINT: exits.CHECKPOINT,
}


def _cmd_status(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    try:
        status = session.run_status(profile_dir)
    except Exception as exc:
        print(redact.redact_raw_text(f"status check failed: {exc}"), file=sys.stderr)
        return 1
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


def _cmd_schema(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                {
                    "Post": json_schema(),
                    "Comment": comment_json_schema(),
                    "Entity": entity_json_schema(),
                },
                indent=2,
            )
        )
        return 0
    print("Post — one element of the fetch/feed/post output (fetch, feed, search, group, post):\n")
    for field in schema_fields():
        note = "" if field["always_present"] else " (only present with --raw)"
        print(f"  {field['name']} : {field['type']}{note}")
        print(f"      {field['description']}")
    print("\nComment — one element of the comments output:\n")
    for field in comment_schema_fields():
        print(f"  {field['name']} : {field['type']}")
        print(f"      {field['description']}")
    print("\nEntity — a non-post search hit (search --type people|pages|groups, or top):\n")
    for field in entity_schema_fields():
        print(f"  {field['name']} : {field['type']}")
        print(f"      {field['description']}")
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    # Built from the same parser the CLI actually runs on, so the catalog cannot
    # describe a command that doesn't exist or miss one that does.
    data = catalog.build_catalog(build_parser())
    print(json.dumps(data, indent=2) if args.json else catalog.render_text(data))
    return exits.OK


def _redact_raw_recursive(post: Post) -> None:
    """Scrub ``post.raw`` AND every nested ``shared_post.raw`` down the chain.

    ``Post.to_dict()`` serializes ``shared_post`` recursively, so a shared/
    quoted post's own raw node reaches the output file just as directly as
    the top-level post's — redacting only the top-level one leaves it
    completely unscrubbed.
    """
    node: Post | None = post
    while node is not None:
        if node.raw is not None:
            node.raw = redact.redact(node.raw)
        node = node.shared_post


def _default_output_path(identifier: str, fmt: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "Z"
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


def _run_retrieval(args: argparse.Namespace, call) -> tuple[retrieve.RetrieveResult | None, int]:
    """Run a retrieval and map every failure mode onto the documented exit code."""
    try:
        return call(), 0
    except (LoginRequiredError, SessionExpiredError) as exc:
        print(f"{exc} Run: scrape-fb login --profile {args.profile}", file=sys.stderr)
        return None, exits.LOGIN_REQUIRED
    except ChallengeError as exc:
        print(str(exc), file=sys.stderr)
        return None, exits.CHECKPOINT
    except ProfileUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return None, exits.TARGET_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001 - last-resort CLI boundary
        if args.verbose:
            print(redact.redact_raw_text(f"unexpected error: {exc}"), file=sys.stderr)
        else:
            print(
                f"unexpected error: {type(exc).__name__} (rerun with -v for details)",
                file=sys.stderr,
            )
        return None, exits.ERROR


def _write_dicts(rows: list[dict], path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        if fmt == "ndjson":
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False))
                fh.write("\n")
        else:
            json.dump(rows, fh, ensure_ascii=False, indent=2)


def _cmd_comments(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    result, code = _run_retrieval(
        args,
        lambda: retrieve.fetch_comments(
            args.url,
            profile_dir=profile_dir,
            profile_name=args.profile,
            headless=not args.headed,
            limit=args.limit,
            sort=args.sort,
            replies=args.replies,
            request_interval=args.request_interval,
            max_pages=args.max_pages,
        ),
    )
    if result is None:
        return code
    if not result.comments:
        print("0 comments retrieved (the post may have none).", file=sys.stderr)
        return exits.NO_RESULTS

    output_path = (
        Path(args.output) if args.output else _default_output_path("comments", args.format)
    )
    _write_dicts([c.to_dict() for c in result.comments], output_path, args.format)
    replies = sum(1 for c in result.comments if c.depth > 0)
    print(
        f"{len(result.comments)} comments ({replies} replies), stop reason: "
        f"{result.stop_reason}. Saved to {output_path}",
        file=sys.stderr,
    )
    return 0


def _cmd_post(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    result, code = _run_retrieval(
        args,
        lambda: retrieve.fetch_post(
            args.url,
            profile_dir=profile_dir,
            profile_name=args.profile,
            headless=not args.headed,
            request_interval=args.request_interval,
            raw=args.raw,
        ),
    )
    if result is None:
        return code

    if args.raw and not args.no_redact:
        _redact_raw_recursive(result)
    output_path = Path(args.output) if args.output else _default_output_path("post", args.format)
    _write_dicts([result.to_dict()], output_path, args.format)
    print(
        f"1 post by {result.author_name or 'unknown'}. Saved to {output_path}",
        file=sys.stderr,
    )
    return 0


def _cmd_group(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    result, code = _run_retrieval(
        args,
        lambda: retrieve.fetch_group(
            args.identifier,
            profile_dir=profile_dir,
            profile_name=args.profile,
            headless=not args.headed,
            limit=args.limit,
            request_interval=args.request_interval,
            max_pages=args.max_pages,
            raw=args.raw,
        ),
    )
    if result is None:
        return code
    return _emit_posts(result, args, identifier=f"group-{args.identifier}", since=None)


def _cmd_search(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    result, code = _run_retrieval(
        args,
        lambda: retrieve.search(
            args.query,
            profile_dir=profile_dir,
            profile_name=args.profile,
            search_type=args.search_type,
            headless=not args.headed,
            limit=args.limit,
            request_interval=args.request_interval,
            max_pages=args.max_pages,
            raw=args.raw,
        ),
    )
    if result is None:
        return code

    if args.raw and not args.no_redact:
        for post in result.posts:
            _redact_raw_recursive(post)

    rows = [p.to_dict() for p in result.posts] + [e.to_dict() for e in result.entities]
    if not rows:
        print("0 results retrieved.", file=sys.stderr)
        return exits.NO_RESULTS

    output_path = (
        Path(args.output)
        if args.output
        else _default_output_path(f"search-{args.query}", args.format)
    )
    _write_dicts(rows, output_path, args.format)
    print(
        f"{len(result.posts)} posts, {len(result.entities)} entities, stop reason: "
        f"{result.stop_reason}. Saved to {output_path}",
        file=sys.stderr,
    )
    return 0


def _cmd_feed(args: argparse.Namespace) -> int:
    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    result, code = _run_retrieval(
        args,
        lambda: retrieve.fetch_feed(
            profile_dir=profile_dir,
            profile_name=args.profile,
            headless=not args.headed,
            limit=args.limit,
            request_interval=args.request_interval,
            max_pages=args.max_pages,
            raw=args.raw,
        ),
    )
    if result is None:
        return code
    return _emit_posts(result, args, identifier="feed", since=None)


def _cmd_fetch(args: argparse.Namespace) -> int:
    try:
        normalized_url = profiles.normalize_target_identifier(args.identifier)
    except InvalidIdentifierError as exc:
        print(f"invalid identifier: {exc}", file=sys.stderr)
        return 1

    profile_dir = profiles.resolve_profile_dir(args.profile, args.profile_dir)
    result, code = _run_retrieval(
        args,
        lambda: retrieve.fetch_profile(
            normalized_url,
            profile_dir=profile_dir,
            profile_name=args.profile,
            mode=args.mode,
            headless=not args.headed,
            limit=args.limit,
            since=args.since,
            until=args.until,
            scroll_pause=args.scroll_pause,
            request_interval=args.request_interval,
            max_scrolls=args.max_scrolls,
            max_pages=args.max_pages,
            raw=args.raw,
        ),
    )
    if result is None:
        return code
    return _emit_posts(result, args, identifier=args.identifier, since=args.since)


def _emit_posts(
    result: retrieve.RetrieveResult, args: argparse.Namespace, *, identifier: str, since
) -> int:
    if not result.posts:
        print(
            f"0 posts retrieved (stop reason: {result.stop_reason})."
            + (
                " An unexpected error interrupted scrolling before any post was captured "
                "(rerun with -v for details)."
                if result.stop_reason == scroll.STOP_UNKNOWN_ERROR
                else " If this profile is known-good, this may indicate a Facebook "
                "response-shape change — see "
                "https://github.com/tjdwls101010/Scraper-for-Facebook/issues"
            ),
            file=sys.stderr,
        )
        return exits.NO_RESULTS

    if args.raw:
        if args.no_redact:
            print(
                "WARNING: --no-redact leaves --raw output unscrubbed. The saved file "
                "will contain unredacted third-party data. See DISCLAIMER.md.",
                file=sys.stderr,
            )
        else:
            for post in result.posts:
                _redact_raw_recursive(post)

    output_path = (
        Path(args.output) if args.output else _default_output_path(identifier, args.format)
    )
    _write_output(result.posts, output_path, args.format)

    # Per the exit-code contract: hitting `--limit` is a full success in its
    # own right (limit/since compose, first trigger wins) even if `since`
    # was never independently confirmed crossed — exit 7 is reserved for
    # "we genuinely don't know whether we reached `since`" (stopped on
    # budget/stall), not for "we stopped early because we got enough posts".
    since_inconclusive = result.stop_reason in (
        scroll.STOP_MAX_SCROLLS,
        scroll.STOP_FEED_STALLED,
        retrieve.STOP_MAX_PAGES,
    )
    exit_code = exits.SINCE_UNCONFIRMED if (since is not None and since_inconclusive) else exits.OK
    oldest = result.oldest_seen.date().isoformat() if result.oldest_seen else "unknown"
    newest = result.newest_seen.date().isoformat() if result.newest_seen else "unknown"
    reached_note = " (requested --since NOT confirmed reached)" if exit_code == 7 else ""
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
    "schema": _cmd_schema,
    "catalog": _cmd_catalog,
    "fetch": _cmd_fetch,
    "feed": _cmd_feed,
    "comments": _cmd_comments,
    "post": _cmd_post,
    "search": _cmd_search,
    "group": _cmd_group,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
