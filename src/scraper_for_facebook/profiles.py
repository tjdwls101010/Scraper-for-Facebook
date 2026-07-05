"""Login-profile storage and target-identifier validation.

Two distinct things live here because both are about "which profile":

- ``resolve_profile_dir``/``ensure_profile_dir``: where a *login* profile (a
  persisted, logged-in browser session) is stored on disk.
- ``normalize_target_identifier``: validating and normalizing the *target*
  Facebook profile a caller wants to scrape, before it ever reaches the browser.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import platformdirs

from .config import APP_NAME, ENV_PROFILE_DIR
from .errors import InvalidIdentifierError

# --- Login profile storage --------------------------------------------------

#: The profile directory is a live, 2FA-satisfied session (cookies + local
#: storage) — anyone who can read it has authenticated account access with no
#: password. 0700 so only the owning user can read it (see DISCLAIMER.md §6).
_PROFILE_DIR_MODE = 0o700


def resolve_profile_dir(name: str, profile_dir_override: str | os.PathLike | None = None) -> Path:
    """Return the storage path for the named login profile (does not create it)."""
    if profile_dir_override is not None:
        root = Path(profile_dir_override).expanduser()
    else:
        env_override = os.environ.get(ENV_PROFILE_DIR)
        root = (
            Path(env_override).expanduser()
            if env_override
            else Path(platformdirs.user_data_dir(APP_NAME)) / "profiles"
        )
    return root / name


def ensure_profile_dir(path: Path) -> Path:
    """Create the profile directory (and parents) with 0700 permissions, idempotently."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, _PROFILE_DIR_MODE)
    return path


def list_profiles(profile_dir_override: str | os.PathLike | None = None) -> list[str]:
    """List the names of login profiles that already exist under the storage root."""
    if profile_dir_override is not None:
        root = Path(profile_dir_override).expanduser()
    else:
        env_override = os.environ.get(ENV_PROFILE_DIR)
        root = (
            Path(env_override).expanduser()
            if env_override
            else Path(platformdirs.user_data_dir(APP_NAME)) / "profiles"
        )
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


# --- Target identifier validation --------------------------------------------

_ALLOWED_HOSTS = frozenset({"facebook.com", "www.facebook.com", "m.facebook.com"})
_VANITY_RE = re.compile(r"^[A-Za-z0-9.]+$")
_NUMERIC_ID_RE = re.compile(r"^\d+$")
_PROFILE_PHP_ID_RE = re.compile(r"(?:^|&)id=(\d+)(?:&|$)")


def normalize_target_identifier(raw: str) -> str:
    """Validate and normalize a target profile identifier into a canonical URL.

    Accepts a bare vanity name (``[A-Za-z0-9.]+``), a bare numeric id, a
    ``profile.php?id=<digits>`` path, or a full URL on an allowed Facebook host.
    Anything else is rejected outright rather than best-effort-expanded — an
    unvalidated string reaching the authenticated browser is a navigation
    primitive an attacker-controlled input could otherwise steer (plan §10, §22).
    """
    raw = raw.strip()
    if not raw:
        raise InvalidIdentifierError("identifier is empty")

    if raw.startswith("http://") or raw.startswith("https://"):
        return _normalize_url(raw)

    if _NUMERIC_ID_RE.match(raw):
        return f"https://www.facebook.com/profile.php?id={raw}"

    if _VANITY_RE.match(raw):
        return f"https://www.facebook.com/{quote(raw)}"

    raise InvalidIdentifierError(
        f"invalid identifier {raw!r}: expected a vanity name, a numeric id, "
        "profile.php?id=<digits>, or a full facebook.com/www.facebook.com/"
        "m.facebook.com URL"
    )


def _normalize_url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme != "https":
        raise InvalidIdentifierError(f"unsupported scheme {parts.scheme!r}: only https is accepted")

    host = parts.netloc.split("@")[-1].split(":")[0].lower()
    if host not in _ALLOWED_HOSTS:
        raise InvalidIdentifierError(
            f"unsupported host {host!r}: must be one of {sorted(_ALLOWED_HOSTS)}"
        )

    path = parts.path.strip("/")
    if not path:
        raise InvalidIdentifierError("URL has no profile path")

    first_segment = path.split("/")[0]
    if first_segment == "profile.php":
        match = _PROFILE_PHP_ID_RE.search(parts.query)
        if not match:
            raise InvalidIdentifierError("profile.php URL is missing a numeric id= query parameter")
        return f"https://www.facebook.com/profile.php?id={match.group(1)}"

    if not _VANITY_RE.match(first_segment):
        raise InvalidIdentifierError(f"invalid vanity path segment {first_segment!r}")

    return f"https://www.facebook.com/{quote(first_segment)}"
