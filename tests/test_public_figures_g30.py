"""G30 — Public figures match measured records.

Reads:
- `training/runs/medicine/sweep/final/summary.json`
- `training/runs/medicine/sweep/final/adapter.json`
- `spike/specialists/acceptance/medicine.json`
- `evals/results/bench-x86-16gb-20261018/bench-cpu-ngl0.json`
- `evals/results/bench-x86-16gb-20261018/README.md`

And verifies that every figure cited in `README.md`, `CHANGELOG.md`,
`packaging/RELEASE-NOTES.md`, `docs/SPECIALISTS.md`, and `docs/STATUS.md`
matches the underlying records.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MEDICINE_SUMMARY = REPO_ROOT / "training" / "runs" / "medicine" / "sweep" / "final" / "summary.json"
MEDICINE_ADAPTER = REPO_ROOT / "training" / "runs" / "medicine" / "sweep" / "final" / "adapter.json"
MEDICINE_RECEIPT = REPO_ROOT / "spike" / "specialists" / "acceptance" / "medicine.json"
BENCH_16GB_JSON = REPO_ROOT / "evals" / "results" / "bench-x86-16gb-20261018" / "bench-cpu-ngl0.json"
BENCH_16GB_README = REPO_ROOT / "evals" / "results" / "bench-x86-16gb-20261018" / "README.md"

README_MD = REPO_ROOT / "README.md"
CHANGELOG_MD = REPO_ROOT / "CHANGELOG.md"
RELEASE_NOTES_MD = REPO_ROOT / "packaging" / "RELEASE-NOTES.md"
SPECIALISTS_MD = REPO_ROOT / "docs" / "SPECIALISTS.md"
STATUS_MD = REPO_ROOT / "docs" / "STATUS.md"


def _fmt_comma(n: int) -> str:
    return f"{n:,}"


def test_medicine_records_and_public_citations_match() -> None:
    summary = json.loads(MEDICINE_SUMMARY.read_text(encoding="utf-8"))
    adapter = json.loads(MEDICINE_ADAPTER.read_text(encoding="utf-8"))
    receipt = json.loads(MEDICINE_RECEIPT.read_text(encoding="utf-8"))

    variant = receipt["evaluated_as"]
    assert variant == adapter["evaluated_as"] == "spike-medicine-it13270-s0.5"
    assert receipt["accepted"] is True
    assert adapter["verdict"] == "accepted"
    assert receipt["file"] == adapter["file"] == "spike-medicine-it13270-s0.5.gguf"
    assert receipt["bytes"] == adapter["bytes"] == 42_485_024
    assert receipt["sha256"] == adapter["sha256"]
    sha = receipt["sha256"]
    assert len(sha) == 64

    med_suite = summary["suites"]["medicine"]
    gen_suite = summary["suites"]["general"]
    med_vs = med_suite["vs_base"][variant]
    gen_vs = gen_suite["vs_base"][variant]

    n_questions = med_vs["paired_n"]
    med_delta = med_vs["delta_points"]
    gen_delta = gen_vs["delta_points"]

    assert n_questions == 2318
    assert med_delta == 35.07
    assert gen_delta == -0.62
    assert summary["acceptance"][variant]["accepted"] is True
    assert receipt["reasons"] == summary["acceptance"][variant]["reasons"]

    # Sub-task counts must sum to pooled medicine count (1000 + 500 + 818 = 2318)
    tasks = summary["tasks"]
    assert (
        tasks["medmcqa-val"]["vs_base"][variant]["paired_n"]
        + tasks["pubmedqa-labeled"]["vs_base"][variant]["paired_n"]
        + tasks["mmlu-pro-health"]["vs_base"][variant]["paired_n"]
        == n_questions
    )

    n_comma = _fmt_comma(n_questions)  # "2,318"
    pos_delta = f"+{med_delta:.2f}"  # "+35.07"
    neg_delta_minus = f"−{abs(gen_delta):.2f}"  # "−0.62"

    # 1. CHANGELOG.md cites +35.07, −0.62, and 2,318 questions
    changelog = CHANGELOG_MD.read_text(encoding="utf-8")
    assert pos_delta in changelog
    assert neg_delta_minus in changelog or f"{gen_delta:.2f}" in changelog
    assert n_comma in changelog

    # 2. docs/SPECIALISTS.md cites +35.07, −0.62, and 2026-11-05 acceptance date
    specialists = SPECIALISTS_MD.read_text(encoding="utf-8")
    assert pos_delta in specialists
    assert neg_delta_minus in specialists or f"{gen_delta:.2f}" in specialists
    assert receipt["date"] in specialists

    # 3. packaging/RELEASE-NOTES.md cites Medicine passing its gate on 2026-11-05
    release_notes = RELEASE_NOTES_MD.read_text(encoding="utf-8")
    assert "Medicine passed" in release_notes
    assert receipt["date"] in release_notes

    # 4. docs/STATUS.md cites 2,318 questions, +35.07, −0.62, 42,485,024 bytes, and the adapter SHA-256
    status = STATUS_MD.read_text(encoding="utf-8")
    assert f"| medicine (pooled) | {n_comma} |" in status
    assert pos_delta in status
    assert neg_delta_minus in status
    assert _fmt_comma(receipt["bytes"]) in status
    assert sha in status

    # 5. README.md must not claim "Today none has a trained adapter that passed its acceptance test"
    # and must match the accepted Medicine record (+35.07, −0.62, 2,318 questions)
    readme = README_MD.read_text(encoding="utf-8")
    assert "Today none has a trained adapter that passed its acceptance test" not in readme
    assert pos_delta in readme
    assert neg_delta_minus in readme or f"{gen_delta:.2f}" in readme
    assert n_comma in readme


def test_16gb_benchmark_records_and_public_citations_match() -> None:
    bench = json.loads(BENCH_16GB_JSON.read_text(encoding="utf-8"))
    bench_readme = BENCH_16GB_README.read_text(encoding="utf-8")
    readme = README_MD.read_text(encoding="utf-8")
    changelog = CHANGELOG_MD.read_text(encoding="utf-8")
    status = STATUS_MD.read_text(encoding="utf-8")

    assert bench["hardware"]["physical_cores"] == 4
    assert round(bench["hardware"]["total_ram_gb"]) == 16
    assert bench["llama_cpp_build"] == "b11709-62318cd57"

    by_tokens = {r["prompt_tokens"]: r for r in bench["results"]}
    r1k = by_tokens[1024]
    r8k = by_tokens[8192]
    r32k = by_tokens[32768]

    # Derived rounded figures from bench-cpu-ngl0.json
    ttft_1k_s = f"{round(r1k['ttft_s']['median'])} s"  # "52 s"
    ttft_8k_s = f"{round(r8k['ttft_s']['median'])} s"  # "773 s"
    ttft_8k_min = f"{round(r8k['ttft_s']['median'] / 60)} min"  # "13 min"
    ttft_32k_s = f"{_fmt_comma(round(r32k['ttft_s']['median']))} s"  # "5,566 s"

    prompt_1k = f"{r1k['prompt_tok_s']['median']:.1f}"  # "19.6"
    prompt_8k = f"{r8k['prompt_tok_s']['median']:.1f}"  # "10.6"
    prompt_32k = f"{r32k['prompt_tok_s']['median']:.1f}"  # "5.9"

    gen_1k = f"{r1k['gen_tok_s']['median']:.1f}"  # "6.2"
    gen_8k = f"{r8k['gen_tok_s']['median']:.1f}"  # "5.1"
    gen_32k = f"{r32k['gen_tok_s']['median']:.1f}"  # "2.1"

    rss_1k_mib = f"{_fmt_comma(round(r1k['peak_rss_mb']))} MiB"  # "6,274 MiB"
    rss_8k_mib = f"{_fmt_comma(round(r8k['peak_rss_mb']))} MiB"  # "6,276 MiB"
    rss_32k_mib = f"{_fmt_comma(round(r32k['peak_rss_mb']))} MiB"  # "6,295 MiB"

    anon_1k_mib = f"{_fmt_comma(round(r1k['peak_rss_anon_mb']))} MiB"  # "3,654 MiB"
    anon_8k_mib = f"{_fmt_comma(round(r8k['peak_rss_anon_mb']))} MiB"  # "3,656 MiB"
    anon_32k_mib = f"{_fmt_comma(round(r32k['peak_rss_anon_mb']))} MiB"  # "3,675 MiB"

    anon_gib = f"{r1k['peak_rss_anon_mb'] / 1024:.1f} GiB"  # "3.6 GiB"
    rss_gib = f"{r1k['peak_rss_mb'] / 1024:.1f} GiB"  # "6.1 GiB"

    # Check bench README.md and docs/STATUS.md tables match JSON
    for doc in (bench_readme, status):
        assert ttft_1k_s in doc and prompt_1k in doc and gen_1k in doc
        assert rss_1k_mib in doc and anon_1k_mib in doc
        assert ttft_8k_s in doc and prompt_8k in doc and gen_8k in doc
        assert rss_8k_mib in doc and anon_8k_mib in doc
        assert ttft_32k_s in doc and prompt_32k in doc and gen_32k in doc
        assert rss_32k_mib in doc and anon_32k_mib in doc

    # Check README.md cites 52 s, 13 min, 6.2 tok/s, 5.1 tok/s, 3.6 GiB anonymous, 6.1 GiB RSS
    assert ttft_1k_s in readme
    assert ttft_8k_min in readme
    assert f"{gen_1k} tok/s" in readme
    assert f"{gen_8k} tok/s" in readme
    assert f"{gen_8k}–{gen_1k} tok/s" in readme
    assert f"{anon_gib} anonymous" in readme
    assert f"{rss_gib} RSS" in readme

    # Check CHANGELOG.md cites 6.2 tok/s at 1K, 5.1 at 8K, and 3.6 GiB
    assert f"{gen_1k} tok/s at 1K" in changelog
    assert f"{gen_8k} at 8K" in changelog
    assert anon_gib in changelog
