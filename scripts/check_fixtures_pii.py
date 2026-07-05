#!/usr/bin/env python3
"""Fail if committed fixtures look like they contain real captured data.

Fixtures under tests/fixtures/ must be hand-authored, PII-free synthetic
skeletons (see plan §13) — never a mutated real capture. This is a coarse,
allowlist-based gate, not a guarantee: every fixture diff still needs human
review before merge.

SCOPE, STATED PLAINLY: this only pattern-matches structural artifacts (CDN
hosts, token-shaped keys, emails, phone numbers, high-entropy strings). It
has NO detector for free-text PII — a real person's actual name or sensitive
message content, with no token/email/phone/CDN-host/high-entropy-string
anywhere in the line, passes this gate silently. Human review is the actual
control for that category, not this script.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

REAL_CDN_HOSTS = re.compile(
    r"\b(scontent[.\-][a-z0-9.\-]*fbcdn\.net|fbcdn\.net|fbstatic-a\.akamaihd\.net)\b"
)
TOKEN_SHAPED_KEYS = re.compile(r'"(fb_dtsg|lsd|jazoest|datr|sb|c_user|xs)"\s*:')
EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Requires explicit separators between groups, so a bare long digit run (a
# perfectly normal synthetic Facebook numeric id, e.g. "100000000000001")
# doesn't false-positive as a phone number.
PHONE = re.compile(r"\+?\d{1,3}[\s.\-]\d{2,4}[\s.\-]\d{3,4}[\s.\-]?\d{0,4}\b")
# Long runs of base64/hex-ish characters, the shape of a real signed token.
HIGH_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/_=\-]{40,}")


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def scan_file(path: Path) -> list[str]:
    problems = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if REAL_CDN_HOSTS.search(line):
            problems.append(f"{path}:{lineno}: real fbcdn/scontent CDN host found")
        if TOKEN_SHAPED_KEYS.search(line):
            problems.append(f"{path}:{lineno}: token-shaped cookie/auth field found")
        if EMAIL.search(line):
            problems.append(f"{path}:{lineno}: email-shaped string found")
        if PHONE.search(line):
            problems.append(f"{path}:{lineno}: phone-shaped string found")
        for match in HIGH_ENTROPY_TOKEN.finditer(line):
            token = match.group(0)
            if shannon_entropy(token) >= 4.0:
                problems.append(
                    f"{path}:{lineno}: high-entropy token-shaped string found ({token[:12]}...)"
                )
    return problems


def main() -> int:
    if not FIXTURES_DIR.exists():
        return 0
    all_problems: list[str] = []
    for path in sorted(FIXTURES_DIR.glob("*.ndjson")):
        all_problems.extend(scan_file(path))
    if all_problems:
        print("Fixture PII/secret scan FAILED:", file=sys.stderr)
        for problem in all_problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nFixtures must be hand-authored synthetic skeletons, never a mutated "
            "real capture. If this is a false positive on deliberately fake data, "
            "adjust the fixture to use an obviously-fake placeholder instead of "
            "something real-shaped.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Fixture PII/secret scan OK ({len(list(FIXTURES_DIR.glob('*.ndjson')))} file(s) checked) "
        "— structural checks only; still needs human review for real names/free-text PII."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
