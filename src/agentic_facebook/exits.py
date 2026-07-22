"""The CLI's exit-code contract, in one place.

These were previously bare integer literals scattered across ``cli.py``'s
command handlers, which made them impossible to enumerate without reading every
handler — so anything that wanted to *describe* the contract (documentation, the
``catalog`` command, a skill) had to re-type it and then silently drift from it.

Callers script against these numbers, so a value here is a public API: change
what a code means and you break someone's shell script, not just a docstring.
"""

from __future__ import annotations

OK = 0
ERROR = 1
LOGIN_REQUIRED = 2
CHECKPOINT = 3
NO_RESULTS = 4
TARGET_UNAVAILABLE = 5
SINCE_UNCONFIRMED = 7

#: The single source for what each code means. ``catalog`` renders this; the
#: README's exit-code table and the skill both defer to it rather than restating.
DESCRIPTIONS: dict[int, str] = {
    OK: "Success — limit met, requested date window fully reached, or feed genuinely exhausted.",
    ERROR: "Unexpected error. Re-run with -v for the (redaction-scrubbed) detail.",
    LOGIN_REQUIRED: (
        "Login required or session expired. Run: agentic-facebook login "
        "(opens a real browser; needs a human)."
    ),
    CHECKPOINT: (
        "Account checkpoint — Meta flagged the session. Do NOT retry: hammering a "
        "checkpointed account turns a temporary block into a permanent one."
    ),
    NO_RESULTS: (
        "Zero results. Ambiguous by nature: either genuinely nothing there, or parser "
        "drift / doc_id rotation. Probe with a known-good command (e.g. `feed --limit 3`) "
        "to tell them apart."
    ),
    TARGET_UNAVAILABLE: (
        "Target unavailable (memorialized, blocked, restricted, or nonexistent). "
        "A definite answer, not a transient failure — do not retry with variations."
    ),
    SINCE_UNCONFIRMED: (
        "Partial: --since was requested but not confirmed reached within the run's "
        "budget. The posts returned are real but may not be all of them in that range."
    ),
}
