"""Build the static landing page in `site/` (G31). Not published: nothing here deploys anything.

Every figure on the page is read from the evaluation and benchmark records and written to `site/figures.json`
with the record it came from; the templates in `site-src/` only name figures as `{{key}}`, so no measured number is
typed by hand. Brand and font files are copied unchanged from `brand/` and `marketing/video/public/`.

    python scripts/build_site.py           # write site/
    python scripts/build_site.py --check   # exit 1 when site/ differs from what the records produce
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

MEDICINE_SUMMARY = "training/runs/medicine/sweep/final/summary.json"
MEDICINE_RECEIPT = "spike/specialists/acceptance/medicine.json"
BENCH_X86 = "evals/results/bench-x86-16gb-20261018/bench-cpu-ngl0.json"
BENCH_MAC = "evals/results/bench-mac-20261017/bench-metal-ngl99.json"
CATALOG = "spike/specialists/catalog.yaml"
README = "README.md"
CONTEXTS = {"1k": 1024, "8k": 8192, "32k": 32768}

# published path (under the output folder) -> source file in the repository
COPIES = {
    "assets/spike-mark-512.png": "brand/logo/spike-mark-512.png",
    "assets/spike-wordmark.png": "brand/logo/spike-wordmark.png",
    "assets/spike-wordmark-white.png": "brand/logo/spike-wordmark-white.png",
    "assets/favicon-32.png": "brand/web/favicon-32.png",
    "assets/apple-touch-icon.png": "brand/web/apple-touch-icon.png",
    "assets/fonts/inter-latin-400-normal.woff2": "marketing/video/public/inter-latin-400-normal.woff2",
    "assets/fonts/inter-latin-700-normal.woff2": "marketing/video/public/inter-latin-700-normal.woff2",
    "assets/fonts/Inter-LICENSE.txt": "marketing/video/public/Inter-LICENSE.txt",
}
PAGES = {"index.html": "site-src/index.en.html", "es/index.html": "site-src/index.es.html"}
HAND_WRITTEN = ("assets/site.css",)  # lives in the output folder, is not generated; only copied by --out


def _load(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def human_time(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f} s"
    if seconds < 120:
        return f"{round(seconds)} s"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    return f"~{seconds / 3600:.1f} h"


def figures(root: Path = ROOT) -> dict[str, dict[str, str]]:
    """Return {key: {"value": text shown on the page, "source": record path}} read from the records."""
    out: dict[str, dict[str, str]] = {}

    def put(key: str, value: str, source: str) -> None:
        out[key] = {"value": value, "source": source}

    summary, receipt = _load(root, MEDICINE_SUMMARY), _load(root, MEDICINE_RECEIPT)
    variant = receipt["evaluated_as"]
    if not receipt["accepted"] or not summary["acceptance"][variant]["accepted"]:
        raise SystemExit("the medicine record is not an accepted verdict; the page text would be wrong")
    med, gen = summary["suites"]["medicine"], summary["suites"]["general"]
    put("med_n", f"{med['vs_base'][variant]['paired_n']:,}", MEDICINE_SUMMARY)
    put("med_delta", f"+{med['vs_base'][variant]['delta_points']:.2f}", MEDICINE_SUMMARY)
    put("med_base_acc", f"{med['accuracy']['base']['accuracy'] * 100:.1f} %", MEDICINE_SUMMARY)
    put("med_acc", f"{med['accuracy'][variant]['accuracy'] * 100:.1f} %", MEDICINE_SUMMARY)
    put("gen_n", f"{gen['vs_base'][variant]['paired_n']:,}", MEDICINE_SUMMARY)
    put("gen_delta", f"−{abs(gen['vs_base'][variant]['delta_points']):.2f}", MEDICINE_SUMMARY)
    reasons = " ".join(receipt["reasons"])
    put("med_need", re.search(r"need ≥ ([\d.]+)", reasons).group(1), MEDICINE_RECEIPT)
    put("gen_limit", re.search(r"max drop ([\d.]+)", reasons).group(1), MEDICINE_RECEIPT)
    put("med_date", receipt["date"], MEDICINE_RECEIPT)
    put("med_bytes", f"{receipt['bytes']:,}", MEDICINE_RECEIPT)
    put("med_sha256", receipt["sha256"], MEDICINE_RECEIPT)

    catalog = yaml.safe_load((root / CATALOG).read_text(encoding="utf-8"))["specialists"]
    accepted = [p.stem for p in sorted((root / "spike/specialists/acceptance").glob("*.json"))
                if json.loads(p.read_text(encoding="utf-8")).get("accepted") is True]
    put("specialists_count", str(len(catalog)), CATALOG)
    put("accepted_count", str(len(accepted)), "spike/specialists/acceptance")
    put("others_count", str(len(catalog) - len(accepted)), CATALOG)

    x86, mac = _load(root, BENCH_X86), _load(root, BENCH_MAC)
    put("x86_cores", str(x86["hardware"]["physical_cores"]), BENCH_X86)
    put("x86_ram", str(x86["hardware"]["total_ram_gb"]), BENCH_X86)
    put("x86_build", x86["llama_cpp_build"], BENCH_X86)
    put("mac_chip", mac["hardware"]["cpu_model"], BENCH_MAC)
    put("mac_ram", f"{mac['hardware']['total_ram_gb']:.0f}", BENCH_MAC)
    for name, bench, path in (("x86", x86, BENCH_X86), ("mac", mac, BENCH_MAC)):
        by_ctx = {r["prompt_tokens"]: r for r in bench["results"]}
        for tag, tokens in CONTEXTS.items():
            r = by_ctx[tokens]
            fmt = "{:.1f}" if name == "x86" else "{:.0f}"
            put(f"{name}_{tag}_ttft", human_time(r["ttft_s"]["median"]), path)
            put(f"{name}_{tag}_gen", fmt.format(r["gen_tok_s"]["median"]), path)
            put(f"{name}_{tag}_rss", f"{r['peak_rss_mb'] / 1024:.1f}", path)
            if name == "x86":
                put(f"{name}_{tag}_prompt", f"{r['prompt_tok_s']['median']:.1f}", path)
                put(f"{name}_{tag}_anon", f"{r['peak_rss_anon_mb'] / 1024:.1f}", path)

    readme = (root / README).read_text(encoding="utf-8")
    for key, start in (("cmd_install", "(cd web && npm ci"), ("cmd_pull", "spike models pull"),
                       ("cmd_run", "spike serve")):
        line = next(x for x in readme.splitlines() if x.startswith(start))
        put(key, re.sub(r"\s{2,}#.*$", "", line).rstrip(), README)
    return out


def render_page(template: str, figs: dict[str, dict[str, str]]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in figs:
            raise SystemExit(f"template names an unknown figure: {key}")
        return f'<span data-fig="{key}">{html.escape(figs[key]["value"], quote=False)}</span>'

    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def render(root: Path = ROOT) -> dict[str, bytes]:
    figs = figures(root)
    files = {"figures.json": (json.dumps({"generated_by": "scripts/build_site.py", "figures": figs}, indent=2,
                                         sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")}
    for dst, src in PAGES.items():
        files[dst] = render_page((root / src).read_text(encoding="utf-8"), figs).encode("utf-8")
    for dst, src in COPIES.items():
        files[dst] = (root / src).read_bytes()
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    files = render()
    if args.out.resolve() != (ROOT / "site").resolve():
        for rel in HAND_WRITTEN:  # the stylesheet is not generated; a custom --out gets a copy so pages render there
            files[rel] = (ROOT / "site" / rel).read_bytes()
    stale = [rel for rel, data in files.items()
             if not (args.out / rel).exists() or (args.out / rel).read_bytes() != data]
    if args.check:
        if stale:
            print("Site is stale / Sitio desactualizado: python scripts/build_site.py")
            for rel in stale:
                print("  ", rel)
            return 1
        return 0
    for rel, data in files.items():
        target = args.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
