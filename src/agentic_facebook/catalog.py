"""``agentic-facebook catalog`` — the CLI describing itself, so nothing has to re-type it.

The problem this solves: anything that wants to *explain* this tool (the README,
a `.claude` skill, an agent's prompt) previously had to transcribe the command
list, the flags, their choices, and the exit codes. A transcription drifts the
moment a flag is added, and a stale description is worse than none — a model
trusts it over its own reading of `--help`.

So the catalog is **derived, never authored**: the command and option tables are
introspected from the live ``argparse`` parser, the object schemas come from the
same ``to_dict()``-anchored functions ``schema`` uses, and the exit codes come
from ``exits.DESCRIPTIONS``. Adding a command or a flag updates this output with
no edit here, and ``tests/test_catalog.py`` fails if that ever stops being true.

What is genuinely authored here is the short list below of behaviors that no
amount of introspection can reach — the output contract and the known
limitations. They live in code, next to the thing they describe, so there is
still exactly one copy.
"""

from __future__ import annotations

import argparse
from typing import Any

from . import exits
from .comments import schema_fields as comment_schema_fields
from .model import schema_fields as post_schema_fields
from .search import schema_fields as entity_schema_fields

#: Facts about how every retrieval command behaves that argparse cannot express.
#: The first entry is the single most common mistake made against this CLI.
OUTPUT_CONTRACT = [
    "Results are written to a JSON FILE. Only a one-line summary goes to stderr, "
    "and nothing useful goes to stdout — run the command, then read the file.",
    "Pass --output PATH to choose that file. Without it, results land under the "
    "platform data directory with a timestamped name (never the current directory, "
    "because captured posts contain third-party personal data).",
    "--format json emits one array; --format ndjson emits one object per line.",
    "fetch/feed/post/search/group emit Post objects; comments emits Comment objects; "
    "search --type people|pages|groups emits Entity objects instead of Posts.",
]

#: Known limitations that look like bugs. Authored (they are not derivable), but
#: authored HERE so the skill and the README can point at them instead of copying.
LIMITATIONS = [
    "Active mode replays Facebook query ids (doc_id) that rotate when Facebook ships "
    "a client build. `fetch` falls back to the browser automatically; feed/comments/"
    "post/search/group are active-only and simply fail until the package is updated.",
    "Passive mode cannot see a profile's newest post — the first timeline batch is "
    "server-rendered into the HTML, never fetched as a GraphQL request. Active mode can.",
    "post/comments require a real post permalink. Reel URLs are unsupported (a reel "
    "page embeds no story id).",
    "comments --replies fetches depth-1 replies only; a comment's reply_count includes "
    "deeper nested replies that are not returned.",
    "--limit on comments counts top-level comments only, so one heavily-replied comment "
    "cannot consume the whole budget.",
    "Requests are rate-floored in code and cannot be bypassed: >= 1.0s between active "
    "requests, >= 0.5s between scrolls.",
]


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _describe_option(action: argparse.Action) -> dict[str, Any] | None:
    """One flag, as the catalog reports it. ``None`` for things not worth listing."""
    if isinstance(action, argparse._HelpAction | argparse._VersionAction):
        return None
    entry: dict[str, Any] = {
        "flags": list(action.option_strings) or [action.dest],
        "help": (action.help or "").replace("%(default)s", str(action.default)),
        "required": bool(action.required),
    }
    if action.choices:
        entry["choices"] = sorted(str(choice) for choice in action.choices)
    if action.default is not None and not isinstance(action, argparse._StoreTrueAction):
        entry["default"] = action.default
    if not action.option_strings:
        entry["positional"] = True
    return entry


def build_catalog(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """The whole self-description, derived from ``parser`` plus the schema functions."""
    from . import __version__

    subparsers = _subparser_action(parser)
    commands: dict[str, Any] = {}
    if subparsers is not None:
        # choices maps name -> subparser; _choices_actions carries the help strings.
        help_by_name = {choice.dest: (choice.help or "") for choice in subparsers._choices_actions}
        for name, subparser in subparsers.choices.items():
            options = [_describe_option(a) for a in subparser._actions]
            commands[name] = {
                "summary": help_by_name.get(name, ""),
                "options": [option for option in options if option is not None],
            }

    return {
        "tool": parser.prog,
        "version": __version__,
        "commands": commands,
        "exit_codes": {str(code): text for code, text in sorted(exits.DESCRIPTIONS.items())},
        "output_contract": OUTPUT_CONTRACT,
        "limitations": LIMITATIONS,
        "object_types": {
            "Post": post_schema_fields(),
            "Comment": comment_schema_fields(),
            "Entity": entity_schema_fields(),
        },
    }


def _format_option(option: dict[str, Any]) -> str:
    flags = ", ".join(option["flags"])
    if option.get("choices"):
        flags += " {" + "|".join(option["choices"]) + "}"
    return f"    {flags}\n        {option['help']}"


def render_text(catalog: dict[str, Any]) -> str:
    """The human/agent-readable rendering. Same content, no JSON parsing needed."""
    lines = [f"{catalog['tool']} {catalog['version']} — command catalog", ""]

    lines.append("OUTPUT CONTRACT (read this first)")
    for item in catalog["output_contract"]:
        lines.append(f"  - {item}")
    lines.append("")

    lines.append("COMMANDS")
    for name, command in catalog["commands"].items():
        lines.append(f"  {name} — {command['summary']}")
        for option in command["options"]:
            lines.append(_format_option(option))
        lines.append("")

    lines.append("EXIT CODES")
    for code, text in catalog["exit_codes"].items():
        lines.append(f"  {code}: {text}")
    lines.append("")

    lines.append("OBJECT TYPES (full field descriptions: agentic-facebook schema)")
    for type_name, fields in catalog["object_types"].items():
        names = ", ".join(field["name"] for field in fields)
        lines.append(f"  {type_name}: {names}")
    lines.append("")

    lines.append("KNOWN LIMITATIONS")
    for item in catalog["limitations"]:
        lines.append(f"  - {item}")
    return "\n".join(lines)
