"""Write docs/guide/{en,es}/cli.md from the `spike` parser itself, so the reference cannot drift from the code (G38).

The tables are built from the parser's actions, not from argparse's help text, so they read the same on every Python.

    python scripts/cli_reference.py          # rewrite both pages
    python scripts/cli_reference.py --check  # exit 1 if a page is stale (CI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spike.cli import build_parser  # noqa: E402

PAGES = {"en": ROOT / "docs" / "guide" / "en" / "cli.md", "es": ROOT / "docs" / "guide" / "es" / "cli.md"}

INTRO = {
    "en": """# Command line

Language: [Español](../es/cli.md) | **English** · [Guide Index](README.md)

Every `spike` command and option, generated from the parser by `python scripts/cli_reference.py` (CI fails when this
page is stale). Run `spike <command> --help` for the same text in the terminal.

## Examples

```bash
spike doctor                                  # hardware, llama-server and how much memory each local model needs
spike models pull qwen3.5-4b                  # download the base model, checked against the Hub's SHA-256
spike serve --open                            # start the app on http://127.0.0.1:8740 and open the browser
spike chat "What does an ACE inhibitor do?" --mode medicine
spike tune --quick                            # find the fastest threads and KV cache on this machine
spike skills validate                         # offline checks of the bundled skills
```
""",
    "es": """# Línea de comandos

Idioma: **Español** | [English](../en/cli.md) · [Índice de la guía](README.md)

Todas las órdenes y opciones de `spike`, generadas a partir del propio analizador con
`python scripts/cli_reference.py` (la CI falla si esta página queda desfasada). Los textos de ayuda están en inglés,
igual que en `spike <orden> --help`; las órdenes `skills` y `connectors` los dan en los dos idiomas.

## Ejemplos

```bash
spike doctor                                  # hardware, llama-server y memoria que necesita cada modelo local
spike models pull qwen3.5-4b                  # descarga el modelo base, comprobado con el SHA-256 del Hub
spike serve --open                            # arranca la app en http://127.0.0.1:8740 y abre el navegador
spike chat "¿Qué hace un IECA?" --mode medicine
spike tune --quick                            # busca los hilos y la caché KV más rápidos en este equipo
spike skills validate                         # comprobaciones sin red de las skills incluidas
```
""",
}

HEAD = {"en": ("Option", "Default", "What it does"), "es": ("Opción", "Por defecto", "Qué hace")}


def commands(parser: argparse.ArgumentParser, path: list[str]):
    """(path, help, parser) for every leaf command, depth first, in the parser's own order."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help for choice in action._choices_actions}
            for name, sub in action.choices.items():
                subs = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
                if subs:
                    yield from commands(sub, path + [name])
                else:
                    yield path + [name], helps.get(name) or "", sub


def cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def option_rows(parser: argparse.ArgumentParser) -> list[str]:
    rows = []
    for a in parser._actions:
        if isinstance(a, argparse._HelpAction):
            continue
        name = ", ".join(f"`{o}`" for o in a.option_strings) or f"`{a.dest}`"
        if a.choices:
            name += " (" + ", ".join(f"`{c}`" for c in a.choices) + ")"
        default = "" if a.default in (None, False, [], argparse.SUPPRESS) or a.required else f"`{a.default}`"
        if a.required and a.option_strings:
            default = "required"
        rows.append(f"| {name} | {default} | {cell(a.help or '')} |")
    return rows


def render(lang: str) -> str:
    out = [INTRO[lang]]
    for path, help_text, parser in commands(build_parser(), ["spike"]):
        out.append(f"## `{' '.join(path)}`\n")
        if help_text:
            out.append(cell(help_text) + "\n")
        rows = option_rows(parser)
        if rows:
            out.append("| " + " | ".join(HEAD[lang]) + " |\n|---|---|---|\n" + "\n".join(rows) + "\n")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if a page is stale")
    args = parser.parse_args()
    stale = []
    for lang, page in PAGES.items():
        text = render(lang)
        if args.check:
            if not page.exists() or page.read_text(encoding="utf-8") != text:
                stale.append(str(page.relative_to(ROOT)))
        else:
            page.write_text(text, encoding="utf-8")
    if stale:
        print("CLI reference is stale / Referencia de la CLI desactualizada: python scripts/cli_reference.py",
              *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
