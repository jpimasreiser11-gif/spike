"""G38: every `spike` command and option explains itself, and the generated CLI reference is current."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from spike.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def walk(parser: argparse.ArgumentParser, path: list[str]):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help for choice in action._choices_actions}
            for name, sub in action.choices.items():
                yield "command", path + [name], helps.get(name)
                yield from walk(sub, path + [name])
        elif not isinstance(action, argparse._HelpAction):
            yield "option", path + [action.option_strings[0] if action.option_strings else action.dest], action.help


def test_every_command_and_option_has_help():
    missing = [" ".join(path) for kind, path, text in walk(build_parser(), ["spike"]) if not (text or "").strip()]
    assert missing == []


def test_the_walk_sees_every_top_level_command():
    names = {path[1] for kind, path, _ in walk(build_parser(), ["spike"]) if kind == "command" and len(path) == 2}
    assert {"serve", "doctor", "models", "chat", "bench", "tune", "evolve", "skills", "connectors", "forge",
            "adapters"} <= names


def test_the_cli_reference_pages_are_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "cli_reference.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_both_pages_cover_every_leaf_command():
    sys.path.insert(0, str(ROOT / "scripts"))
    import cli_reference

    leaves = [" ".join(path) for path, _, _ in cli_reference.commands(build_parser(), ["spike"])]
    for page in cli_reference.PAGES.values():
        text = page.read_text(encoding="utf-8")
        assert [leaf for leaf in leaves if f"## `{leaf}`" not in text] == []
