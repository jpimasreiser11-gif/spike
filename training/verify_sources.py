"""Evidence for reviewing `license_status: unverified` sources of training/datasets.yaml (needs the network).

For each source it records what a reviewer needs to mark it verified, and nothing is changed in the registry:
the license the Hub metadata declares and whether the license gate accepts it for the source's role, whether the
dataset is gated, the Hub commit read, the dataset card (README) text, every row of the split streamed and counted
(after the registry `filter:`), how many rows the source's formatter turns into a chat, and two formatted
examples. A failure is recorded per source and the others still run. The verdict stays with the reviewer: the
card text, upstream rights and how the data was produced are read by a person, not inferred.

    python training/verify_sources.py --out sources-report.json            # every unverified source
    python training/verify_sources.py --names gsm8k-train mbpp-test --out r.json
    python training/verify_sources.py --probe allenai/scitail --out r.json   # candidates not in the registry yet
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT))

from spike_train import licenses  # noqa: E402
from spike_train.data import FORMATTERS  # noqa: E402
from spike_train.sources import filtered, hub_load_kwargs  # noqa: E402

CARD_CHARS = 12000
EXAMPLE_CHARS = 1500


def hub_metadata(repo: str) -> dict:
    """The Hub's own record of a dataset (network): license, gating, commit, card text."""
    import httpx

    data = httpx.get(f"https://huggingface.co/api/datasets/{repo}", timeout=60).raise_for_status().json()
    sha = data.get("sha")
    card = httpx.get(f"https://huggingface.co/datasets/{repo}/raw/{sha or 'main'}/README.md", timeout=60,
                     follow_redirects=True)
    lic = (data.get("cardData") or {}).get("license")  # read as licenses.hub_license does: metadata, then the tag
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    if not lic:
        lic = next((t.split(":", 1)[1] for t in data.get("tags", []) if t.startswith("license:")), None)
    return {"license_hub": licenses.normalize(lic) or None, "gated": data.get("gated", False), "sha": sha,
            "last_modified": data.get("lastModified"), "card": card.text[:CARD_CHARS] if card.status_code == 200 else None}


def stream_rows(src: dict) -> Iterable[dict]:
    """Every row of the source's split, streamed (network), with the registry filter applied as prepare.py does."""
    from datasets import load_dataset

    return filtered(src, load_dataset(src["hub"], src.get("config"), split=src.get("split", "train"), streaming=True,
                                     **hub_load_kwargs(src)))


def _clip(chat: dict) -> dict:
    return {"messages": [{**m, "content": str(m.get("content", ""))[:EXAMPLE_CHARS]} for m in chat.get("messages", [])]}


def verify(name: str, src: dict, metadata: Callable[[str], dict] | None = None,
           rows: Callable[[dict], Iterable[dict]] | None = None) -> dict:
    """The evidence for one registry source; `error` holds the first failure, and what was read before it stays."""
    metadata, rows = metadata or hub_metadata, rows or stream_rows
    out: dict = {"name": name, "hub": src.get("hub"), "config": src.get("config"), "split": src.get("split", "train"),
                 "role": src.get("role"), "format": src.get("format"), "license_registry": src.get("license")}
    if "hub" not in src:
        return {**out, "error": "not a Hub source: its pinned files and LICENSE are reviewed from datasets.yaml"}
    try:
        out.update(metadata(src["hub"]))
        ok, reason = licenses.check(out["license_hub"], src.get("role", "train"))
        out["license_gate"] = {"ok": ok, "reason": reason,
                               "matches_registry": out["license_hub"] == licenses.normalize(src.get("license"))}
        fmt = FORMATTERS.get(src.get("format", ""))
        if fmt is None:
            raise ValueError(f"no formatter '{src.get('format')}' in spike_train.data.FORMATTERS")
        total = formatted = 0
        examples: list[dict] = []
        columns: set[str] = set()
        for row in rows(src):
            total += 1
            columns |= set(row)
            chat = fmt(row, "")
            if chat is not None:
                formatted += 1
                if len(examples) < 2:
                    examples.append(_clip(chat))
        out.update({"rows": total, "rows_formatted": formatted, "columns": sorted(columns), "examples": examples})
    except Exception as exc:  # recorded for the reviewer; the next source still runs
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--names", nargs="*", help="registry names (default: every license_status: unverified source)")
    ap.add_argument("--registry", default=str(ROOT / "training" / "datasets.yaml"))
    ap.add_argument("--probe", nargs="*", default=[], help="Hub datasets not in the registry: metadata and card only")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.probe:
        report = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "probes": []}
        for repo in args.probe:
            try:
                report["probes"].append({"hub": repo, **hub_metadata(repo)})
            except Exception as exc:  # recorded; the next candidate still runs
                report["probes"].append({"hub": repo, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{repo}: hub_license={report['probes'][-1].get('license_hub')} error={report['probes'][-1].get('error')}")
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 0
    registry = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))["sources"]
    names = args.names or [n for n, s in registry.items() if s.get("license_status") == "unverified"]
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise SystemExit(f"not in the registry: {', '.join(unknown)}")
    report = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": []}
    for name in names:
        started = time.monotonic()
        entry = verify(name, registry[name])
        entry["seconds"] = round(time.monotonic() - started, 1)
        report["sources"].append(entry)
        print(f"{name}: rows={entry.get('rows')} formatted={entry.get('rows_formatted')} "
              f"hub_license={entry.get('license_hub')} error={entry.get('error')}", flush=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 1 if any("error" in s for s in report["sources"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
