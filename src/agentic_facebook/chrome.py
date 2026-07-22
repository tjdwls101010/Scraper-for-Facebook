"""Opt-in: reuse the Facebook session in your everyday Chrome (plan §3a, option a).

**This is literal cookie extraction**, which is exactly what the default path
avoids — hence opt-in, never automatic. It reads Chrome's encryption key from
the macOS Keychain (which may prompt once) and decrypts the cookie values out
of Chrome's own database.

Why decryption is unavoidable: simply copying a logged-in Chrome profile and
opening it with Playwright **fails**. Playwright launches Chrome with
``--use-mock-keychain``, so Chrome cannot reach the real "Chrome Safe Storage"
Keychain entry, every cookie fails to decrypt, and the copy opens logged out
(recon §5.4).

Importing an everyday browser usually means importing your *main* account —
against this project's throwaway-account guidance. Prefer ``agentic-facebook login``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .errors import AgenticFacebookError

#: Constants of Chrome's macOS cookie encryption (stable for many years).
_SALT = b"saltysalt"
_ITERATIONS = 1003
_KEY_LENGTH = 16
_IV = b" " * 16


class ChromeImportError(AgenticFacebookError):
    """Chrome's cookies could not be read or decrypted."""


def _chrome_user_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"


def list_profiles_with_facebook_session() -> list[str]:
    """Chrome profile names that hold a ``facebook.com`` ``c_user`` cookie.

    Reads cookie *names and domains only* — never a value — so identifying the
    right profile costs no decryption and triggers no Keychain prompt.
    """
    found: list[str] = []
    root = _chrome_user_data_dir()
    if not root.exists():
        return found
    for cookie_db in sorted(root.glob("*/Cookies")):
        try:
            with _temp_copy(cookie_db) as path:
                connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    row = connection.execute(
                        "SELECT 1 FROM cookies WHERE host_key LIKE '%facebook.com' "
                        "AND name = 'c_user' LIMIT 1"
                    ).fetchone()
                finally:
                    connection.close()
            if row:
                found.append(cookie_db.parent.name)
        except (OSError, sqlite3.Error):
            continue
    return found


class _temp_copy:
    """Chrome holds a lock on the live DB; work on a copy."""

    def __init__(self, source: Path) -> None:
        self._source = source
        self._dir: str | None = None

    def __enter__(self) -> Path:
        self._dir = tempfile.mkdtemp(prefix="sfb-chrome-")
        target = Path(self._dir) / "Cookies"
        shutil.copy2(self._source, target)
        os.chmod(target, 0o600)
        return target

    def __exit__(self, *exc) -> None:
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)


def _safe_storage_password() -> str:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ChromeImportError(
            "could not read the 'Chrome Safe Storage' key from the Keychain "
            "(it may need to be allowed once, interactively)"
        ) from exc
    return result.stdout.strip()


def _derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password.encode(), _SALT, _ITERATIONS, _KEY_LENGTH)


def _decrypt(value: bytes, key: bytes) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:  # pragma: no cover - depends on an optional extra
        raise ChromeImportError(
            "--from-chrome needs the optional 'chrome' extra: "
            "pip install 'agentic-facebook[chrome]'"
        ) from exc

    if not value.startswith(b"v10"):
        # An unencrypted value (rare, older Chrome) is already plaintext.
        return value.decode("utf-8", errors="replace")

    decryptor = Cipher(algorithms.AES(key), modes.CBC(_IV)).decryptor()
    plaintext = decryptor.update(value[3:]) + decryptor.finalize()
    if plaintext:
        padding = plaintext[-1]
        if 1 <= padding <= 16:
            plaintext = plaintext[:-padding]
    # Chrome >= 130 prefixes the plaintext with a 32-byte SHA256 of the domain.
    # Detected structurally (non-UTF8 leading bytes) rather than by version
    # sniffing, so both layouts work without knowing which Chrome wrote it.
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        return plaintext[32:].decode("utf-8", errors="replace")


def load_facebook_cookies(profile: str = "Default") -> dict[str, str]:
    """Decrypted ``facebook.com`` cookies from a local Chrome profile.

    Raises :class:`ChromeImportError` if the profile, the Keychain key, or the
    session itself is missing — never returns a half-usable cookie jar.
    """
    cookie_db = _chrome_user_data_dir() / profile / "Cookies"
    if not cookie_db.exists():
        available = ", ".join(list_profiles_with_facebook_session()) or "none found"
        raise ChromeImportError(
            f"no Chrome cookie database for profile {profile!r} "
            f"(profiles with a Facebook session: {available})"
        )

    key = _derive_key(_safe_storage_password())
    cookies: dict[str, str] = {}
    with _temp_copy(cookie_db) as path:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT name, value, encrypted_value FROM cookies "
                "WHERE host_key LIKE '%facebook.com'"
            ).fetchall()
        finally:
            connection.close()

    for name, value, encrypted in rows:
        if value:
            cookies[name] = value
        elif encrypted:
            decrypted = _decrypt(encrypted, key)
            if decrypted:
                cookies[name] = decrypted

    if "c_user" not in cookies or "xs" not in cookies:
        raise ChromeImportError(
            f"Chrome profile {profile!r} has no logged-in Facebook session "
            "(no c_user/xs cookie after decryption)"
        )
    return cookies
