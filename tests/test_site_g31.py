"""G31 — the static landing page in `site/` (not published).

The page is rendered by `scripts/build_site.py` from `site-src/` templates; every figure comes from
`site/figures.json`, which the script reads out of the evaluation and benchmark records. These tests read the files
only: no network, no browser.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SCRIPT = ROOT / "scripts" / "build_site.py"
PAGES = {"en": SITE / "index.html", "es": SITE / "es" / "index.html"}
REPO_URL = "https://github.com/jpimasreiser11-gif/spike"
ALLOWED_EXTERNAL = (REPO_URL, "https://huggingface.co/")
PALETTE = {"ink": "#052E1E", "green": "#88D445", "shadow": "#5FBB47", "mint": "#E3FADA", "cream": "#FDFDFA"}
SECTIONS = ["what", "today", "figures", "install", "licenses", "not-claimed"]


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.text: dict[str, list[str]] = {}  # data-fig key -> text of each occurrence
        self._fig: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        self.tags.append((tag, a))
        if tag == "title":
            self._in_title = True
        if "data-fig" in a:
            self._fig.append(a["data-fig"])
            self.text.setdefault(a["data-fig"], []).append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "span" and self._fig:
            self._fig.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._fig:
            self.text[self._fig[-1]][-1] += data

    def find(self, name: str) -> list[dict[str, str]]:
        return [a for t, a in self.tags if t == name]


def parse(lang: str) -> Page:
    p = Page()
    p.feed(PAGES[lang].read_text(encoding="utf-8"))
    return p


def luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_generator_check_passes_and_detects_drift(tmp_path: Path) -> None:
    ok = subprocess.run([sys.executable, str(SCRIPT), "--check"], cwd=ROOT, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    out = tmp_path / "site"
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--check"], cwd=ROOT).returncode == 1
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(out)], cwd=ROOT).returncode == 0
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--check"], cwd=ROOT).returncode == 0
    lf = lambda p: p.read_bytes().replace(b"\r\n", b"\n")  # noqa: E731 (a Windows checkout has CRLF)
    assert lf(out / "figures.json") == lf(SITE / "figures.json")
    assert lf(out / "es" / "index.html") == lf(PAGES["es"])
    fig = out / "figures.json"
    fig.write_text(fig.read_text(encoding="utf-8").replace("+35.07", "+99.99"), encoding="utf-8")
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--check"], cwd=ROOT).returncode == 1


def test_figures_equal_the_records() -> None:
    figs = {k: v["value"] for k, v in json.loads((SITE / "figures.json").read_text(encoding="utf-8"))["figures"].items()}
    summary = json.loads((ROOT / "training/runs/medicine/sweep/final/summary.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT / "spike/specialists/acceptance/medicine.json").read_text(encoding="utf-8"))
    v = receipt["evaluated_as"]
    assert receipt["accepted"] is True
    assert figs["med_delta"] == f"+{summary['suites']['medicine']['vs_base'][v]['delta_points']:.2f}" == "+35.07"
    assert figs["gen_delta"] == "−0.62"
    assert figs["med_n"] == f"{summary['suites']['medicine']['vs_base'][v]['paired_n']:,}" == "2,318"
    assert figs["gen_n"] == "800"
    assert figs["med_bytes"] == f"{receipt['bytes']:,}"
    assert figs["med_date"] == receipt["date"]
    assert figs["med_sha256"] == receipt["sha256"]
    assert figs["accepted_count"] == "1" and figs["specialists_count"] == "13" and figs["others_count"] == "12"
    base = summary["suites"]["medicine"]["accuracy"]["base"]["accuracy"]
    tuned = summary["suites"]["medicine"]["accuracy"][v]["accuracy"]
    assert figs["med_base_acc"] == f"{base * 100:.1f} %" and figs["med_acc"] == f"{tuned * 100:.1f} %"
    bench = json.loads((ROOT / "evals/results/bench-x86-16gb-20261018/bench-cpu-ngl0.json").read_text(encoding="utf-8"))
    for r, tag in zip(bench["results"], ("1k", "8k", "32k"), strict=True):
        assert r["prompt_tokens"] == {"1k": 1024, "8k": 8192, "32k": 32768}[tag]
        assert figs[f"x86_{tag}_gen"] == f"{r['gen_tok_s']['median']:.1f}"
        assert figs[f"x86_{tag}_prompt"] == f"{r['prompt_tok_s']['median']:.1f}"
        assert figs[f"x86_{tag}_anon"] == f"{r['peak_rss_anon_mb'] / 1024:.1f}"
        assert figs[f"x86_{tag}_rss"] == f"{r['peak_rss_mb'] / 1024:.1f}"
    assert (figs["x86_1k_gen"], figs["x86_8k_gen"], figs["x86_32k_gen"]) == ("6.2", "5.1", "2.1")
    assert (figs["x86_1k_ttft"], figs["x86_8k_ttft"], figs["x86_32k_ttft"]) == ("52 s", "13 min", "~1.5 h")
    mac = json.loads((ROOT / "evals/results/bench-mac-20261017/bench-metal-ngl99.json").read_text(encoding="utf-8"))
    assert figs["mac_1k_gen"] == f"{mac['results'][0]['gen_tok_s']['median']:.0f}" == "82"
    assert figs["x86_cores"] == str(bench["hardware"]["physical_cores"]) == "4"
    assert figs["x86_ram"] == f"{bench['hardware']['total_ram_gb']}" == "15.7"


def test_figures_on_both_pages_equal_figures_json() -> None:
    data = json.loads((SITE / "figures.json").read_text(encoding="utf-8"))["figures"]
    for lang in PAGES:
        page = parse(lang)
        assert page.text, lang
        for key, texts in page.text.items():
            assert key in data, f"{lang}: {key} is not in figures.json"
            for text in texts:
                assert text == data[key]["value"], f"{lang}: {key} {text!r} != {data[key]['value']!r}"
            assert (ROOT / data[key]["source"]).exists(), data[key]["source"]
    for key in ("med_delta", "gen_delta", "med_n", "x86_1k_gen", "x86_8k_gen", "x86_32k_gen", "x86_1k_ttft", "mac_1k_gen"):
        assert key in parse("en").text and key in parse("es").text


def test_no_numbers_typed_by_hand_next_to_unit() -> None:
    """Prose may not carry a measured number: every tok/s, GiB or pts figure sits in a data-fig span."""
    for lang, path in PAGES.items():
        html = re.sub(r"<span data-fig=.*?</span>", "", path.read_text(encoding="utf-8"), flags=re.S)
        html = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", html, flags=re.S)
        assert not re.search(r"\d[\d.,]*\s*(tok/s|GiB|pts|puntos|points)\b", html), lang


def test_both_languages_have_the_same_sections() -> None:
    en, es = parse("en"), parse("es")
    for page in (en, es):
        ids = [a["id"] for t, a in page.tags if t == "section" and "id" in a]
        assert ids == SECTIONS
        assert len(page.find("h1")) == 1
    assert [a["id"] for t, a in en.tags if t == "section"] == [a["id"] for t, a in es.tags if t == "section"]
    assert len([1 for t, _ in en.tags if t == "h2"]) == len([1 for t, _ in es.tags if t == "h2"]) == len(SECTIONS)
    assert sorted(en.text) == sorted(es.text)
    assert len(en.find("img")) == len(es.find("img"))
    assert len(en.find("a")) == len(es.find("a"))
    assert en.find("html")[0]["lang"] == "en" and es.find("html")[0]["lang"] == "es"
    assert en.title != es.title
    langs = {a["hreflang"]: a["href"] for a in en.find("link") if a.get("rel") == "alternate"}
    assert langs == {"en": "index.html", "es": "es/index.html"}
    langs = {a["hreflang"]: a["href"] for a in es.find("link") if a.get("rel") == "alternate"}
    assert langs == {"en": "../index.html", "es": "index.html"}


def test_install_commands_are_the_readme_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    figs = json.loads((SITE / "figures.json").read_text(encoding="utf-8"))["figures"]
    install = figs["cmd_install"]["value"]
    run = figs["cmd_run"]["value"]
    assert install == '(cd web && npm ci && npm run build) && pipx install ".[docs,finance,data,motion]"'
    assert run == "spike serve --open"
    assert re.search(rf"^{re.escape(install)}\s", readme, re.M) and re.search(rf"^{re.escape(run)}\s", readme, re.M)
    assert figs["cmd_pull"]["value"] == "spike models pull qwen3.5-4b" and figs["cmd_pull"]["value"] in readme


def _refs(path: Path) -> list[str]:
    page = Page()
    page.feed(path.read_text(encoding="utf-8"))
    refs = []
    for _tag, a in page.tags:
        for attr in ("href", "src", "srcset", "poster", "action", "data"):
            if attr in a:
                refs += [x.strip().split()[0] for x in a[attr].split(",") if x.strip()]
    return refs


def test_links_and_assets_exist_and_no_third_party_hosts() -> None:
    for lang, path in PAGES.items():
        html = path.read_text(encoding="utf-8")
        ids = {a["id"] for _, a in parse(lang).tags if "id" in a}
        for ref in _refs(path):
            url = urlsplit(ref)
            if url.scheme in ("http", "https"):
                assert ref.startswith(ALLOWED_EXTERNAL), f"{lang}: external URL {ref}"
                if ref.startswith(REPO_URL + "/blob/main/"):
                    rel = unquote(url.path.removeprefix("/jpimasreiser11-gif/spike/blob/main/"))
                    assert (ROOT / rel).exists(), f"{lang}: {rel} is not in the repository"
                continue
            assert not url.scheme and not ref.startswith("//"), f"{lang}: {ref}"
            if not url.path:
                assert url.fragment in ids, f"{lang}: #{url.fragment}"
                continue
            target = (path.parent / unquote(url.path)).resolve()
            assert target.exists() and SITE in target.parents, f"{lang}: missing {ref}"
            if url.fragment and target.suffix == ".html":
                assert f'id="{url.fragment}"' in target.read_text(encoding="utf-8"), f"{lang}: {ref}"
        assert "<script" not in html.lower() and "<iframe" not in html.lower() and "<form" not in html.lower()
        assert not re.search(r"https?://(?!(?:github\.com/jpimasreiser11-gif/spike|huggingface\.co)\b)", html), lang
        assert not re.search(r"gtag|googletagmanager|plausible|matomo|document\.cookie", html, re.I)
    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    assert "@import" not in css and not re.search(r"https?:", css)
    for u in re.findall(r"url\(\s*['\"]?([^)'\"]+)", css):
        assert (SITE / "assets" / u).resolve().exists(), u
    for lang in PAGES:
        for a in parse(lang).find("link"):
            if a.get("rel") in ("stylesheet", "preload", "icon", "apple-touch-icon"):
                assert not a["href"].startswith(("http", "//")), a


def test_assets_are_the_repo_brand_and_font_files() -> None:
    pairs = {
        "assets/spike-mark-512.png": "brand/logo/spike-mark-512.png",
        "assets/spike-wordmark.png": "brand/logo/spike-wordmark.png",
        "assets/spike-wordmark-white.png": "brand/logo/spike-wordmark-white.png",
        "assets/favicon-32.png": "brand/web/favicon-32.png",
        "assets/apple-touch-icon.png": "brand/web/apple-touch-icon.png",
        "assets/fonts/inter-latin-400-normal.woff2": "marketing/video/public/inter-latin-400-normal.woff2",
        "assets/fonts/inter-latin-700-normal.woff2": "marketing/video/public/inter-latin-700-normal.woff2",
        "assets/fonts/Inter-LICENSE.txt": "marketing/video/public/Inter-LICENSE.txt",
    }
    for dst, src in pairs.items():
        assert (SITE / dst).read_bytes() == (ROOT / src).read_bytes(), dst
    assert "SIL OPEN FONT LICENSE" in (SITE / "assets/fonts/Inter-LICENSE.txt").read_text(encoding="utf-8")
    fonts = list((SITE / "assets" / "fonts").glob("*"))
    assert {p.suffix for p in fonts} <= {".woff2", ".txt"}


def test_accessibility_structure() -> None:
    for lang in PAGES:
        p = parse(lang)
        names = [t for t, _ in p.tags]
        assert names.count("main") == 1 and names.count("header") >= 1 and names.count("footer") == 1
        assert names.count("nav") >= 1 and all(a.get("aria-label") for t, a in p.tags if t == "nav")
        vp = [a for a in p.find("meta") if a.get("name") == "viewport"]
        assert vp and "width=device-width" in vp[0]["content"] and "user-scalable=no" not in vp[0]["content"]
        assert any(a.get("name") == "description" and a.get("content") for a in p.find("meta"))
        assert p.title.strip()
        for img in p.find("img"):
            assert "alt" in img and img.get("width") and img.get("height"), img
        assert any(a.get("alt") for a in p.find("img"))
        skip = [a for a in p.find("a") if a.get("class") == "skip"]
        assert skip and skip[0]["href"] == "#content" and any(a.get("id") == "content" for _, a in p.tags)
        levels = [int(t[1]) for t in names if re.fullmatch(r"h[1-6]", t)]
        assert levels[0] == 1 and all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))
        for t, a in p.tags:
            if t == "section":
                assert a.get("aria-labelledby") and any(x.get("id") == a["aria-labelledby"] for _, x in p.tags)
        for tag, a in p.tags:
            if tag == "a":
                assert a.get("href")
        assert all(a.get("scope") for t, a in p.tags if t == "th")
        assert [t for t, _ in p.tags].count("caption") >= 2


def test_palette_and_contrast() -> None:
    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert root
    vars_ = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", root.group(1)))
    for name, hexv in PALETTE.items():
        assert vars_[name].upper() == hexv.upper()
    assert {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", css)} <= {h.upper() for h in PALETTE.values()}
    assert not re.findall(r"#[0-9A-Fa-f]{3}\b", css)
    # Text and background pairs the stylesheet uses (body text needs 4.5, large text and UI borders 3).
    text_pairs = [("ink", "cream"), ("ink", "mint"), ("ink", "green"), ("cream", "ink"), ("mint", "ink"), ("ink", "shadow")]
    for fg, bg in text_pairs:
        assert contrast(PALETTE[fg], PALETTE[bg]) >= 4.5, (fg, bg, contrast(PALETTE[fg], PALETTE[bg]))
    # The two greens are never used as text colour on cream or mint (they would fail 4.5).
    assert contrast(PALETTE["green"], PALETTE["cream"]) < 3 and contrast(PALETTE["shadow"], PALETTE["cream"]) < 4.5
    for m in re.finditer(r"(?<![-\w])color:\s*var\(--(\w+)\)", css):
        assert m.group(1) in ("ink", "cream", "mint"), m.group(0)
    assert re.search(r":focus-visible", css) and re.search(r"prefers-reduced-motion", css)


def test_responsive_css_has_no_fixed_wide_boxes() -> None:
    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    assert "overflow-x: auto" in css and "overflow-wrap" in css and "max-width: 100%" in css
    assert not re.search(r"(?<!max-)(?<!min-)width:\s*\d{3,}px", css)
    assert "@font-face" in css and "font-display: swap" in css
    for lang in PAGES:
        assert parse(lang).find("table"), lang


def test_not_claimed_section_is_honest() -> None:
    for lang, words in (("en", ("Finance", "not measured", "not published")), ("es", ("Finanzas", "no medido", "no publicado"))):
        html = PAGES[lang].read_text(encoding="utf-8")
        section = re.search(r'<section id="not-claimed".*?</section>', html, re.S)
        assert section
        for w in words:
            assert w in section.group(0), (lang, w)


def test_check_accepts_windows_line_endings(tmp_path: Path) -> None:
    """A Windows checkout (core.autocrlf) has CRLF in the generated text files; that is not drift."""
    out = tmp_path / "site"
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(out)], cwd=ROOT).returncode == 0
    for page in [*out.rglob("*.html"), *out.rglob("*.json")]:
        page.write_bytes(page.read_bytes().replace(b"\n", b"\r\n"))
    assert subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--check"], cwd=ROOT).returncode == 0
