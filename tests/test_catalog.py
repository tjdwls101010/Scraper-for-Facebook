"""The catalog must stay DERIVED, not transcribed.

These tests are the whole reason the catalog is trustworthy. A hand-maintained
description of a CLI drifts the moment someone adds a flag, and a stale
description is worse than none — a reader (or a model) trusts it over their own
reading of `--help`. So the tests below fail if the catalog ever stops being a
faithful projection of the real parser.
"""

from __future__ import annotations

import json

from scraper_for_facebook import catalog, exits
from scraper_for_facebook.cli import _HANDLERS, build_parser


def _catalog() -> dict:
    return catalog.build_catalog(build_parser())


def _subcommand_names() -> set[str]:
    import argparse

    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("parser has no subcommands")


def test_every_subcommand_appears_in_the_catalog():
    """The anti-drift check: add a command, and it shows up here with no edit."""
    assert set(_catalog()["commands"]) == _subcommand_names()


def test_every_subcommand_has_a_handler():
    """Catches the other half of the same drift — a command that parses but can't run."""
    assert _subcommand_names() == set(_HANDLERS)


def test_catalog_reports_real_flags_with_their_choices():
    commands = _catalog()["commands"]

    search_type = next(o for o in commands["search"]["options"] if "--type" in o["flags"])
    assert search_type["choices"] == ["groups", "pages", "people", "posts", "top"]

    comment_sort = next(o for o in commands["comments"]["options"] if "--sort" in o["flags"])
    assert comment_sort["choices"] == ["recent", "top"]


def test_catalog_carries_every_flag_the_parser_defines():
    """Spot-check one command exhaustively rather than trusting the shape alone."""
    import argparse

    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            fetch_parser = action.choices["fetch"]
            break

    expected = {
        flag
        for a in fetch_parser._actions
        if not isinstance(a, argparse._HelpAction)
        for flag in (a.option_strings or [a.dest])
    }
    reported = {flag for o in _catalog()["commands"]["fetch"]["options"] for flag in o["flags"]}
    assert reported == expected


def test_help_text_is_carried_through_not_summarized():
    """The catalog's value is the real help string, not a paraphrase of it."""
    options = _catalog()["commands"]["comments"]["options"]
    replies = next(o for o in options if "--replies" in o["flags"])
    assert "depth" in replies["help"]


def test_exit_codes_come_from_the_single_source():
    reported = _catalog()["exit_codes"]
    assert reported == {str(code): text for code, text in sorted(exits.DESCRIPTIONS.items())}
    # The two codes whose meaning is easy to misread as a plain failure.
    assert "Ambiguous" in reported[str(exits.NO_RESULTS)]
    assert "not confirmed reached" in reported[str(exits.SINCE_UNCONFIRMED)]


def test_object_types_match_the_schema_command():
    """One source of truth for fields: the same to_dict()-anchored functions."""
    from scraper_for_facebook.comments import schema_fields as comment_fields
    from scraper_for_facebook.model import schema_fields as post_fields
    from scraper_for_facebook.search import schema_fields as entity_fields

    types = _catalog()["object_types"]
    assert types["Post"] == post_fields()
    assert types["Comment"] == comment_fields()
    assert types["Entity"] == entity_fields()


def test_output_contract_leads_with_the_file_not_stdout_trap():
    """The single most common mistake against this CLI; it must not get buried."""
    first = _catalog()["output_contract"][0]
    assert "FILE" in first and "stdout" in first


def test_catalog_is_json_serializable():
    """It is meant to be consumed programmatically — argparse defaults can be exotic."""
    assert json.loads(json.dumps(_catalog()))["tool"] == "scrape-fb"


def test_render_text_lists_every_command():
    text = catalog.render_text(_catalog())
    for name in _subcommand_names():
        assert f"  {name} — " in text
