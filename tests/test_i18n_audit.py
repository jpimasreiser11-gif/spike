"""Complete i18n audit for web/src/i18n.ts and frontend .tsx components (G17)."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_SRC = ROOT / "web" / "src"

ALLOWED_TECHNICAL_LITERALS = {
    "SPIKE",
    "SPIKE Dev",
    "SPIKE Motion ·",
    "Forge",
    "⌘ / Ctrl K",
    ": JSON",
    "SQL",
    "Python",
    "· Godot",
    "whisper.cpp:",
    "· Piper:",
    "· ffmpeg:",
    "· ffprobe:",
    "SHA-256",
    "stdio",
    "Streamable HTTP",
    "ID",
    "· KV",
    ", KV",
    ", ctx",
    "· ctx",
    "GB RAM ·",
    "· Metal",
    "RSS",
    "MB ·",
    "KB",
    "KB ·",
    "GiB",
    "fps ·",
    "boe.es",
    "npx",
    "https://…/mcp",
    "staging.example.test",
    "BTC/USDT, ETH/USDT",
    "http://localhost:5173/",
    "index.html",
    "~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf",
    '{"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}',
}


def _extract_placeholders(text: str) -> list[str]:
    braces = re.findall(r"\{\{?[a-zA-Z0-9_]+\}?\}", text)
    single = re.findall(r"\{[a-zA-Z0-9_]+\}", text)
    interp = re.findall(r"\$\{[^}]+\}", text)
    return sorted(set(braces + single + interp))


def _strip_comments(code: str) -> str:
    out: list[str] = []
    i = 0
    n = len(code)
    in_str: str | None = None
    escaped = False
    while i < n:
        ch = code[i]
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_str:
                in_str = None
            i += 1
        elif ch in ('"', "'", "`"):
            in_str = ch
            out.append(ch)
            i += 1
        elif code[i : i + 2] == "//":
            while i < n and code[i] != "\n":
                i += 1
        elif code[i : i + 2] == "/*":
            i += 2
            while i < n and code[i : i + 2] != "*/":
                i += 1
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _find_matching_brace(text: str, open_pos: int) -> int:
    depth = 0
    in_str: str | None = None
    escaped = False
    for i in range(open_pos, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'", "`"):
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError(f"Unmatched brace at {open_pos}")


def _parse_ts_dict(body: str, prefix: str = "") -> dict[str, str]:
    """Flatten nested TS object literal string entries into dotted key -> string value."""
    out: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        m_key = re.match(r'(?:"([^"]+)"|\'([^\']+)\'|([a-zA-Z0-9_]+))\s*:\s*', body[i:])
        if not m_key:
            i += 1
            continue
        key = m_key.group(1) or m_key.group(2) or m_key.group(3)
        full_key = f"{prefix}.{key}" if prefix else key
        i += m_key.end()
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if body[i] == "{":
            end = _find_matching_brace(body, i)
            sub = _parse_ts_dict(body[i + 1 : end], full_key)
            out[full_key] = "__OBJECT__"
            out.update(sub)
            i = end + 1
            m_as = re.match(r"\s*as\s+[^,\n}]+", body[i:])
            if m_as:
                i += m_as.end()
        elif body[i] in ('"', "'", "`"):
            quote = body[i]
            j = i + 1
            escaped = False
            chars: list[str] = []
            while j < n:
                ch = body[j]
                if escaped:
                    chars.append(ch)
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    break
                else:
                    chars.append(ch)
                j += 1
            out[full_key] = "".join(chars)
            i = j + 1
        elif body[i] == "[":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if body[j] == "[":
                    depth += 1
                elif body[j] == "]":
                    depth -= 1
                j += 1
            out[full_key] = body[i:j]
            i = j
        else:
            while i < n and body[i] not in ",\n":
                i += 1
    return out


def _extract_locale_blocks(i18n_code: str) -> dict[str, dict[str, str]]:
    clean = _strip_comments(i18n_code)
    m_dicts = re.search(r"export\s+const\s+dicts\s*=\s*\{([^}]+)\}", clean)
    assert m_dicts, "dicts export not found in web/src/i18n.ts"
    locales = [tok.strip() for tok in m_dicts.group(1).split(",") if tok.strip()]
    result: dict[str, dict[str, str]] = {}
    for loc in locales:
        m_loc = re.search(rf"const\s+{re.escape(loc)}(?:\s*:\s*Dict)?\s*=\s*\{{", clean)
        assert m_loc, f"locale {loc} definition not found in web/src/i18n.ts"
        open_brace = m_loc.end() - 1
        close_brace = _find_matching_brace(clean, open_brace)
        result[loc] = _parse_ts_dict(clean[open_brace + 1 : close_brace])
    return result


def test_i18n_locale_keys_and_placeholders_match() -> None:
    code = (WEB_SRC / "i18n.ts").read_text(encoding="utf-8")
    locales = _extract_locale_blocks(code)
    assert "es" in locales and "en" in locales
    base_name = "es"
    base = locales[base_name]
    issues: list[str] = []

    for other_name, other in locales.items():
        if other_name == base_name:
            continue
        for k in sorted(set(base) | set(other)):
            if k not in other:
                issues.append(f"i18n.{k}: missing in {other_name}")
            elif k not in base:
                issues.append(f"i18n.{k}: missing in {base_name}")
            else:
                va, vb = base[k], other[k]
                if not va.strip() or not vb.strip():
                    issues.append(f"i18n.{k}: empty string")
                pa, pb = _extract_placeholders(va), _extract_placeholders(vb)
                if pa != pb:
                    issues.append(f"i18n.{k}: placeholder mismatch ({base_name}={pa}, {other_name}={pb})")

    # Also verify inline `lang === "es" ? { ... } : { ... }` dictionaries in .tsx components
    for path in sorted(WEB_SRC.rglob("*.tsx")):
        if ".test." in path.name:
            continue
        rel = path.relative_to(WEB_SRC).as_posix()
        clean = _strip_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r'lang\s*===\s*"es"\s*\?\s*\{', clean):
            es_open = m.end() - 1
            es_close = _find_matching_brace(clean, es_open)
            rest = clean[es_close + 1 :]
            m_colon = re.match(r"\s*:\s*\{", rest)
            if not m_colon:
                continue
            en_open = es_close + 1 + m_colon.end() - 1
            en_close = _find_matching_brace(clean, en_open)
            es_map = _parse_ts_dict(clean[es_open + 1 : es_close])
            en_map = _parse_ts_dict(clean[en_open + 1 : en_close])
            for k in sorted(set(es_map) | set(en_map)):
                if k not in en_map:
                    issues.append(f"{rel}:{k}: missing in en")
                elif k not in es_map:
                    issues.append(f"{rel}:{k}: missing in es")
                else:
                    pa, pb = _extract_placeholders(es_map[k]), _extract_placeholders(en_map[k])
                    if pa != pb:
                        issues.append(f"{rel}:{k}: placeholder mismatch (es={pa}, en={pb})")

    assert issues == []


def test_tsx_components_have_no_untranslated_ui_literals() -> None:
    attr_re = re.compile(r'\b(aria-label|title|placeholder|alt)\s*=\s*"([^"]*)"')
    ternary_re = re.compile(r'\{[^{}\n]*\?\s*"([^"\n]*)"\s*:\s*"([^"\n]*)"[^{}\n]*\}')
    issues: list[str] = []

    for path in sorted(WEB_SRC.rglob("*.tsx")):
        if ".test." in path.name:
            continue
        rel = path.relative_to(WEB_SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in attr_re.finditer(line):
                attr, val = m.group(1), m.group(2).strip()
                if "${" in val:
                    continue
                if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", val) and val not in ALLOWED_TECHNICAL_LITERALS:
                    issues.append(f"{rel}:{lineno} [attr:{attr}] -> {val!r}")
            if "lang ===" not in line and "className=" not in line:
                for m in ternary_re.finditer(line):
                    if "screenshot:" in m.group(0):
                        continue
                    for branch in (m.group(1).strip(), m.group(2).strip()):
                        if (
                            re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", branch)
                            and branch not in ALLOWED_TECHNICAL_LITERALS
                            and not re.fullmatch(r"[a-z0-9_/-]+", branch)
                        ):
                            issues.append(f"{rel}:{lineno} [ternary] -> {branch!r}")

    assert issues == []
