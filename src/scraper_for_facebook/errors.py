"""Typed errors so library callers can branch on failure mode instead of parsing messages."""

from __future__ import annotations


class ScraperForFacebookError(Exception):
    """Base class for every error this package raises."""


class LoginRequiredError(ScraperForFacebookError):
    """No persisted, logged-in session exists for this profile.

    Fix: ``scrape-fb login --profile <name>``.
    """


class SessionExpiredError(ScraperForFacebookError):
    """A persisted session exists but Facebook is showing a login wall.

    Distinct from :class:`LoginRequiredError` (never logged in) — this means the
    session was valid once and has since expired. Fix: log in again.
    """


class ActiveTransportError(ScraperForFacebookError):
    """An active (HTTP GraphQL) request failed in a way the passive fallback may survive.

    Deliberately NOT an auth error: a rotated ``doc_id``, a transport hiccup, or
    a non-200 all land here, and the caller's correct response is to retry the
    same target through the browser transport (recon §6) rather than to give up
    or to tell the user to log in again.
    """


class ChallengeError(ScraperForFacebookError):
    """Meta has flagged the account with a security checkpoint mid-session.

    Never retried automatically — hammering a checkpointed account raises ban risk.
    """


class ProfileUnavailableError(ScraperForFacebookError):
    """The target profile is memorialized, blocked, restricted, or does not exist.

    Distinct from a zero-post parser-drift result: this is a confirmed, expected
    "nothing to fetch here" rather than a possible extraction failure.
    """


class SessionClosedError(ScraperForFacebookError):
    """An ``iter_profile()`` generator was advanced after its owning ``with`` block exited.

    The generator drives the browser session; it can only make progress while the
    session is open. Consume it inside the ``with FacebookScraper(...) as fb:`` block.
    """


class InvalidIdentifierError(ScraperForFacebookError, ValueError):
    """The target profile identifier/URL failed validation (see ``profiles.py``)."""
