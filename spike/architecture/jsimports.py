"""The modules a JavaScript or TypeScript file imports, found by a small tokenizer (not a parser).

The tokenizer skips comments, string and template contents and regular-expression literals, so an `import` written in
a comment or a string is not one; it then recognises `import x from "m"` in all its forms (default, named, namespace,
side-effect, multi-line), `import type`, `export * from`, `export {..} from`, `import("m")` with a string literal,
`require("m")` and TypeScript's `import x = require("m")`. Each result is (specifier, kind): `static`, `type`
(`import type`, erased at run time) or `lazy` (a dynamic `import()`).

Limits: a `/` after `)` or `}` is read as division; a stray apostrophe in JSX text swallows the rest of its line;
`require` inside a function counts as static; nothing is evaluated, so computed specifiers (`require(name)`) are
not followed. A tokenizer is not a JavaScript parser, and this is documented rather than hidden."""

from __future__ import annotations

REGEX_AFTER = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else",
               "yield", "await"}  # a `/` after one of these starts a regular expression
LOOKAHEAD = 400  # tokens searched for the `from "module"` of one import statement
Token = tuple[str, str]


def scan_string(src: str, i: int) -> tuple[int, str]:
    """(index after the string, its text) for the string starting at src[i]; an unterminated one ends at the line."""
    quote, j, n, chars = src[i], i + 1, len(src), []
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
        elif ch == quote:
            return j + 1, "".join(chars)
        elif ch == "\n":
            return j, ""
        else:
            chars.append(ch)
            j += 1
    return n, ""


def skip_braces(src: str, j: int) -> int:
    """Index after the `}` that closes a `${` whose contents start at j (strings and templates inside are skipped)."""
    depth, n = 1, len(src)
    while j < n and depth:
        ch = src[j]
        if ch in "'\"":
            j = scan_string(src, j)[0]
            continue
        if ch == "`":
            j = skip_template(src, j)
            continue
        depth += (ch == "{") - (ch == "}")
        j += 1
    return j


def skip_template(src: str, i: int) -> int:
    j, n = i + 1, len(src)
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
        elif ch == "`":
            return j + 1
        elif ch == "$" and src[j + 1:j + 2] == "{":
            j = skip_braces(src, j + 2)
        else:
            j += 1
    return n


def scan_regex(src: str, i: int) -> int:
    """Index after the regular expression literal at src[i], or 0 when it is not one (a division)."""
    j, n, in_class = i + 1, len(src), False
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "\n":
            return 0
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            return j
        j += 1
    return 0


def regex_allowed(out: list[Token]) -> bool:
    if not out:
        return True
    kind, value = out[-1]
    if kind in ("str", "num", "tpl", "regex"):
        return False
    return value in REGEX_AFTER if kind == "id" else value not in ")]}"


def tokens(src: str) -> list[Token]:
    out: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif c == "/" and src[i + 1:i + 2] == "/":
            i = src.find("\n", i)
            i = n if i < 0 else i
        elif c == "/" and src[i + 1:i + 2] == "*":
            i = src.find("*/", i + 2)
            i = n if i < 0 else i + 2
        elif c == "/" and regex_allowed(out) and (end := scan_regex(src, i)):
            out.append(("regex", ""))
            i = end
        elif c in "'\"":
            i, value = scan_string(src, i)
            out.append(("str", value))
        elif c == "`":
            i = skip_template(src, i)
            out.append(("tpl", ""))
        elif c.isalpha() or c in "_$" or ord(c) > 127:
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_$" or ord(src[j]) > 127):
                j += 1
            out.append(("id", src[i:j]))
            i = j
        elif c.isdigit():
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            out.append(("num", src[i:j]))
            i = j
        else:
            out.append(("p", c))
            i += 1
    return out


def find_from(toks: list[Token], start: int) -> str | None:
    """The module of the `from "m"` that ends the statement whose tokens begin at `start`."""
    depth = 0
    for k in range(start, min(len(toks), start + LOOKAHEAD)):
        kind, value = toks[k]
        if kind == "p" and value in "{[(":
            depth += 1
        elif kind == "p" and value in "}])":
            depth -= 1
        elif depth == 0 and kind == "p" and value == ";":
            return None
        elif depth == 0 and kind == "id" and value in ("import", "export"):
            return None  # the next statement: this one had no `from`
        elif depth == 0 and (kind, value) == ("id", "from") and k + 1 < len(toks) and toks[k + 1][0] == "str":
            return toks[k + 1][1]
    return None


def after_braces(toks: list[Token], start: int) -> int:
    """Index after the `}` matching the `{` at toks[start]."""
    depth = 0
    for k in range(start, len(toks)):
        if toks[k] == ("p", "{"):
            depth += 1
        elif toks[k] == ("p", "}"):
            depth -= 1
            if depth == 0:
                return k + 1
    return len(toks)


def js_imports(source: str) -> list[tuple[str, str]]:
    """(specifier, kind) of every import in the source, in order, without repeats."""
    if "import" not in source and "require" not in source and "export" not in source:
        return []
    toks = tokens(source)
    found: list[tuple[str, str]] = []
    for i, (kind, value) in enumerate(toks):
        if kind != "id" or (i and toks[i - 1] == ("p", ".")):
            continue
        ahead = toks[i + 1] if i + 1 < len(toks) else ("", "")
        ahead2 = toks[i + 2] if i + 2 < len(toks) else ("", "")
        spec: str | None = None
        how = "static"
        if value == "import":
            if ahead == ("p", "("):
                if ahead2[0] == "str" and i + 3 < len(toks) and toks[i + 3] in (("p", ")"), ("p", ",")):
                    spec, how = ahead2[1], "lazy"
            elif ahead[0] == "str":
                spec = ahead[1]
            elif ahead == ("id", "type") and ahead2 not in (("id", "from"), ("p", ",")):
                spec, how = find_from(toks, i + 2), "type"
            elif ahead != ("p", "."):
                spec = find_from(toks, i + 1)
        elif value == "export":
            if ahead == ("p", "*"):
                spec = find_from(toks, i + 2)
            elif ahead == ("p", "{"):
                k = after_braces(toks, i + 1)
                spec = toks[k + 1][1] if toks[k:k + 1] == [("id", "from")] and k + 1 < len(toks) \
                    and toks[k + 1][0] == "str" else None
            elif ahead == ("id", "type") and ahead2 in (("p", "{"), ("p", "*")):
                spec, how = find_from(toks, i + 2), "type"
        elif value == "require" and ahead == ("p", "(") and ahead2[0] == "str" and toks[i + 3:i + 4] == [("p", ")")]:
            spec = ahead2[1]
        if spec and (spec, how) not in found:
            found.append((spec, how))
    return found
