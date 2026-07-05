#!/usr/bin/env python3
"""Fail if the pushed release tag doesn't match pyproject.toml's version.

version = "0.1.0" in pyproject.toml is a plain static string, not derived
from the git tag — tagging v0.2.0 without also bumping it would otherwise
either fail confusingly at the PyPI upload step (re-uploading an existing
version) or, worse, publish a wheel whose version doesn't match its release
tag. Fail loudly here instead, before any build/upload work happens.

Usage: check_tag_version.py <tag-name, e.g. "v0.1.0">
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_tag_version.py <tag-name>", file=sys.stderr)
        return 1
    tag_name = sys.argv[1]
    tag_version = tag_name.removeprefix("v")

    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        pkg_version = tomllib.load(f)["project"]["version"]

    if tag_version != pkg_version:
        print(
            f"::error::tag {tag_name!r} does not match pyproject.toml version {pkg_version!r}",
            file=sys.stderr,
        )
        return 1
    print(f"OK: tag {tag_name!r} matches pyproject.toml version {pkg_version!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
