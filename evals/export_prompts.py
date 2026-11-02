"""Export a licensed suite's seeded prompts for the existing pairwise evaluator, without starting a model.

    python evals/export_prompts.py --suite writing-select --out evals/results/writing-select.jsonl

Use writing for final acceptance, writing-select for selection, and the same seed as decontamination/evaluation.
No gold title is sent to the judge: this exports id/prompt only. Unverified sources fail before loading rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml
from run_eval import ROOT, load_items


def export_suite(suite: str, out: Path, seed: int = 0) -> int:
    registry = yaml.safe_load((ROOT / 'training/datasets.yaml').read_text(encoding='utf-8'))['sources']
    suites = yaml.safe_load((ROOT / 'evals/suites.yaml').read_text(encoding='utf-8'))['suites']
    if suite not in suites:
        raise ValueError(f"unknown suite '{suite}'")
    rows = [item for task in suites[suite]['tasks'] for item in load_items(task, registry, seed, None)]
    if len({item.id for item in rows}) != len(rows):
        raise ValueError('duplicate prompt ids in suite')
    # Refuse an existing file; acceptance prompts must not silently replace a selection export or its evidence.
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as stream:
        for item in rows:
            stream.write(json.dumps({'id': item.id, 'prompt': item.prompt, 'suite': suite, 'seed': seed},
                                    ensure_ascii=False) + '\n')
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--suite', required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    try:
        n = export_suite(args.suite, args.out, args.seed)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(f'{n} prompts exported to {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
