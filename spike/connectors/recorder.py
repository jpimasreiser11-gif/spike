"""Browser recorder for Spike View (A16): while it records, every call the Playwright connector really ran (navigate,
click, type, select, press a key, fill a form) is kept as a step of a script that can be replayed later.

It only watches: the connector hands each finished call to `observe`, and nothing is sent to the browser from here.
A step's target is what Playwright reported it ran ("### Ran Playwright code" in the result: `getByRole('button',
{ name: 'Send' })`), because that is as robust as the View tooling gives: the snapshot references the model uses
(`e12`) are only valid for one snapshot. When the result says nothing usable the step is kept with an empty target
and cannot be replayed; the app says so.

What is never kept:
- what was typed into a field that is, or is named like, a password, a PIN, a security code or a token: the step is
  marked `secret` and the replay asks for the text. Spike cannot see a field's `type="password"` through the browser
  tools, so this goes by the field's name and selector (see `looks_secret`): a secret in a field with an ordinary name
  is kept, and the app lets the user mark any step as secret afterwards;
- keys pressed one character at a time (a password typed key by key); only named keys such as Enter and Tab are kept;
- the user name and password of an address (`https://user:pw@host/`);
- anything from calls that failed, from other connectors, or from tools that read or run code in the page.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from spike.connectors import browser
from spike.connectors.scripts import (
    MAX_STEPS,
    MAX_TEXT,
    NAMED_KEYS,
    ScriptError,
    ScriptStore,
    clean_step,
    describe,
    web_host,
)

# tools that change the page but that a script has no step for: counted, so the app can say what was left out
IGNORED = {"browser_hover", "browser_drag", "browser_drop", "browser_evaluate", "browser_run_code_unsafe",
           "browser_file_upload", "browser_handle_dialog", "browser_tabs", "browser_navigate_back"}
LOCATOR_ACTIONS = {"fill", "click", "dblclick", "selectOption", "check", "uncheck", "hover", "setChecked", "press", "type"}
CODE_BLOCK = re.compile(r"### Ran Playwright code\s*```js\n(.*?)```", re.S)
PAGE_URL = re.compile(r"^- Page URL: (\S+)", re.M)
SNAPSHOT_REF = re.compile(r"(?:[a-z]\d+)?[a-z]?\d+|ref=\w+|aria-ref=\w+", re.I)
SECRET_WORDS = re.compile(
    r"\b(pass(word|wd|code|phrase)?|contrasena|clave|pin|cvv|cvc|secret\w*|token|otp|2fa|security code|verification code|"
    r"codigo de (seguridad|verificacion)|one[- ]time|api[- ]?key|tarjeta|card number|credit card|iban)\b|type\s*=\s*[\"']?password",
    re.I)


class RecorderError(Exception):
    """The recorder cannot do that now; the message is safe to show."""


def plain(text: str) -> str:
    """Lowercase, without accents: `Contraseña` -> `contrasena`."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def looks_secret(*texts: str) -> bool:
    """True when a field's name, description or selector says it holds a password, PIN, code or token (a guess: the
    browser tools do not tell Spike the field's type)."""
    return any(SECRET_WORDS.search(plain(t)) for t in texts if t)


# ------------------------------------------------------------------ reading the code Playwright reports it ran
class NotSupported(Exception):
    pass


class Regex:
    """A regular expression in generated code (`name: /Send/i`): not a text, so it cannot be a target."""


def js_string(src: str, i: int) -> tuple[str, int]:
    quote, j, chars = src[i], i + 1, []
    while j < len(src):
        ch = src[j]
        if ch == "\\" and j + 1 < len(src):
            nxt = src[j + 1]
            chars.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            j += 2
        elif ch == quote:
            return "".join(chars), j + 1
        else:
            chars.append(ch)
            j += 1
    raise NotSupported


def js_value(src: str, i: int) -> tuple[Any, int]:
    """One value of generated code: a string, number, boolean, object of such values, or a regular expression."""
    while i < len(src) and src[i].isspace():
        i += 1
    if i >= len(src):
        raise NotSupported
    ch = src[i]
    if ch in "'\"`":
        return js_string(src, i)
    if ch == "/":
        j = i + 1
        while j < len(src) and src[j] != "/":
            j += 2 if src[j] == "\\" else 1
        j += 1
        while j < len(src) and src[j].isalpha():
            j += 1
        return Regex(), j
    if ch == "{":
        out: dict[str, Any] = {}
        i += 1
        while True:
            while i < len(src) and src[i].isspace():
                i += 1
            if i >= len(src):
                raise NotSupported
            if src[i] == "}":
                return out, i + 1
            if src[i] in "'\"":
                key, i = js_string(src, i)
            else:
                m = re.compile(r"[A-Za-z_$][\w$]*").match(src, i)
                if not m:
                    raise NotSupported
                key, i = m.group(), m.end()
            while i < len(src) and src[i].isspace():
                i += 1
            if src[i:i + 1] != ":":
                raise NotSupported
            out[key], i = js_value(src, i + 1)
            while i < len(src) and src[i].isspace():
                i += 1
            if src[i:i + 1] == ",":
                i += 1
    m = re.compile(r"-?\d+|true|false").match(src, i)
    if not m:
        raise NotSupported
    word = m.group()
    return (word == "true" if word in ("true", "false") else int(word)), m.end()


def js_args(src: str) -> list[Any]:
    out: list[Any] = []
    i = 0
    while True:
        while i < len(src) and src[i].isspace():
            i += 1
        if i >= len(src):
            return out
        value, i = js_value(src, i)
        out.append(value)
        while i < len(src) and src[i].isspace():
            i += 1
        if src[i:i + 1] == ",":
            i += 1


def chain(line: str) -> list[tuple[str, str | None]]:
    """`page.a(x).b.c(y)` as [("a", "x"), ("b", None), ("c", "y")]: the members after `page`, with their arguments."""
    members: list[tuple[str, str | None]] = []
    i = 0
    while i < len(line):
        if line[i] != ".":
            raise NotSupported
        m = re.compile(r"[A-Za-z_$][\w$]*").match(line, i + 1)
        if not m:
            raise NotSupported
        i, name = m.end(), m.group()
        if line[i:i + 1] != "(":
            members.append((name, None))
            continue
        depth, j, quote = 0, i, ""
        while j < len(line):
            ch = line[j]
            if quote:
                if ch == "\\":
                    j += 1
                elif ch == quote:
                    quote = ""
            elif ch in "'\"`":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth:
            raise NotSupported
        members.append((name, line[i + 1:j]))
        i = j + 1
    return members


def target_of(first: tuple[str, str | None], rest: list[tuple[str, str | None]]) -> dict[str, Any]:
    """The target of a locator call and the `.first()` / `.last()` / `.nth(n)` that follow it."""
    name, raw = first
    args = js_args(raw or "")
    opts = args[1] if len(args) > 1 else {}
    if not isinstance(opts, dict) or (args and isinstance(args[0], (dict, Regex))):
        raise NotSupported
    target: dict[str, Any]
    if name == "getByRole" and len(args) in (1, 2) and isinstance(args[0], str) and set(opts) <= {"name", "exact"}:
        if not isinstance(opts.get("name", ""), str):
            raise NotSupported
        target = {"by": "role", "role": args[0], "name": opts.get("name", ""), "exact": opts.get("exact") is True}
    elif name in ("getByLabel", "getByText", "getByPlaceholder", "getByTitle", "getByAltText") and args \
            and isinstance(args[0], str) and set(opts) <= {"exact"}:
        by = {"getByLabel": "label", "getByText": "text", "getByPlaceholder": "placeholder", "getByTitle": "title",
              "getByAltText": "alt"}[name]
        target = {"by": by, "value": args[0], "exact": opts.get("exact") is True}
    elif name == "getByTestId" and len(args) == 1 and isinstance(args[0], str):
        target = {"by": "testid", "value": args[0], "exact": True}
    elif name == "locator" and len(args) == 1 and isinstance(args[0], str) and not args[0].startswith("aria-ref="):
        target = {"by": "css", "selector": args[0]}
    else:
        raise NotSupported
    if len(rest) > 1:
        raise NotSupported
    for step, inner in rest:
        if step == "first" and inner == "":
            target["nth"] = 0
        elif step == "last" and inner == "":
            target["nth"] = -1
        elif step == "nth" and inner is not None and re.fullmatch(r"\s*\d{1,3}\s*", inner):
            target["nth"] = int(inner)
        else:
            raise NotSupported
    return target


def code_targets(text: str) -> list[dict[str, Any]]:
    """One target per line of the "Ran Playwright code" of a result that acts on an element, in order: a robust
    target, or {"by": "none"} when the line is too complex to be one (chained, filtered, by snapshot reference)."""
    block = CODE_BLOCK.search(text or "")
    if not block:
        return []
    out = []
    for raw in block.group(1).splitlines():
        line = raw.strip().removeprefix("await ").rstrip(";").strip()
        if not line.startswith("page."):
            continue
        try:
            members = chain(line[4:])
        except NotSupported:
            continue
        if len(members) < 2 or members[-1][0] not in LOCATOR_ACTIONS or members[-1][1] is None \
                or any(m[1] is None for m in members[:-1]) or members[0][0] in ("keyboard", "mouse"):
            continue
        try:
            out.append(target_of(members[0], members[1:-1]))
        except NotSupported:
            out.append({"by": "none"})
    return out


# ------------------------------------------------------------------ the recorder
def clean_url(url: str) -> str | None:
    """A web address without the user name and password it may carry; None for anything that is not http(s)."""
    url = url.strip()
    if web_host(url) is None:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.username or parts.password:
        host = parts.hostname or ""
        netloc = f"[{host}]" if ":" in host else host
        netloc += f":{parts.port}" if parts.port else ""
        url = urlunsplit(parts._replace(netloc=netloc))
    return url[:2000]


def page_url(text: str) -> str | None:
    found = PAGE_URL.search(text or "")
    return found.group(1) if found else None


def without_fragment(url: str) -> str:
    return url.split("#", 1)[0]


class Recorder:
    def __init__(self, store: ScriptStore, connector: str = browser.CONNECTOR):
        self.store, self.connector = store, connector
        self.active = False
        self.name = ""
        self.steps: list[dict[str, Any]] = []
        self.ignored: Counter[str] = Counter()
        self.truncated = False
        self.url: str | None = None  # the page the browser is on, as far as the results have said

    # ------------------------------------------------------------------ control
    def start(self, name: str = "") -> dict[str, Any]:
        if self.active:
            raise RecorderError("a recording is already running")
        self.active, self.name = True, name.strip()[:120]
        self.steps, self.ignored, self.truncated, self.url = [], Counter(), False, None
        return self.status()

    def cancel(self) -> None:
        self.active, self.steps, self.url = False, [], None

    def stop(self) -> dict[str, Any]:
        """End the recording and keep the script (nothing is saved when nothing was recorded)."""
        if not self.active:
            raise RecorderError("nothing is being recorded")
        name = self.name or f"Script {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        script = {"name": name, "steps": list(self.steps)}
        try:
            sid = self.store.save(script) if self.steps else None
        except (OSError, ScriptError) as exc:
            raise RecorderError(f"the script could not be saved: {exc.__class__.__name__}") from exc
        out = {"id": sid, "name": name, "steps": len(self.steps), "truncated": self.truncated,
               "ignored": dict(self.ignored), "script": script}
        self.cancel()
        return out

    def status(self) -> dict[str, Any]:
        return {"recording": self.active, "name": self.name if self.active else "",
                "steps": [{"n": i, **describe(s)} for i, s in enumerate(self.steps)],
                "ignored": dict(self.ignored), "truncated": self.truncated}

    # ------------------------------------------------------------------ what the connector tells us
    def observe(self, connector: str, remote: str, args: dict[str, Any], text: str, is_error: bool) -> None:
        if not self.active or connector != self.connector or is_error:
            return
        before = self.url
        after = page_url(text)
        if after:
            self.url = after
        if remote == "browser_navigate":
            self.navigate(args)
        elif remote == "browser_click":
            self.click(args, text, before, after)
        elif remote == "browser_type":
            self.typing(args, text)
        elif remote == "browser_select_option":
            self.select(args, text)
        elif remote == "browser_press_key":
            self.press(args)
        elif remote == "browser_fill_form":
            self.fill_form(args, text)
        elif remote in IGNORED:
            self.ignored[remote] += 1

    def add(self, step: dict[str, Any]) -> None:
        if len(self.steps) >= MAX_STEPS:
            self.truncated = True
            return
        try:
            self.steps.append(clean_step(step, len(self.steps)))
        except ScriptError:  # e.g. a name too long to be a selector: left out, and counted
            self.ignored["step"] += 1

    @staticmethod
    def given(args: dict[str, Any]) -> str:
        return str(args.get("target") or args.get("ref") or "")

    def target(self, given: str, found: dict[str, Any] | None) -> dict[str, Any]:
        """What Playwright reported; else the selector the model wrote, unless it is a snapshot reference."""
        if found is not None:
            return found
        if given and not SNAPSHOT_REF.fullmatch(given.strip()) and not browser.REF.fullmatch(given.strip()):
            return {"by": "css", "selector": given[:500]}
        return {"by": "none"}

    def submits(self, remote: str, args: dict[str, Any], target: dict[str, Any]) -> bool:
        """Whether this call may send a form: the guard's own rules on what the model asked, and on the name of what
        was clicked (the model's description may say nothing)."""
        if browser.review(remote, args, {}) is not None:
            return True
        name = target.get("name") if target.get("by") == "role" else target.get("value", "")
        return remote == "browser_click" and bool(name) and \
            browser.review(remote, {"element": name, "target": ""}, {}) is not None

    def navigate(self, args: dict[str, Any]) -> None:
        url = clean_url(str(args.get("url") or ""))
        if url:
            self.add({"action": "navigate", "url": url})
            self.url = url

    def click(self, args: dict[str, Any], text: str, before: str | None, after: str | None) -> None:
        found = code_targets(text)
        target = self.target(self.given(args), found[0] if found else None)
        step: dict[str, Any] = {"action": "click", "target": target}
        element = str(args.get("element") or "")[:200]
        if element:
            step["element"] = element
        if args.get("doubleClick"):
            step["double"] = True
        moved = bool(before and after and without_fragment(before) != without_fragment(after))
        is_button = target.get("by") == "role" and target.get("role") == "button"
        if self.submits("browser_click", args, target) or (moved and is_button):  # a button that leaves the page
            step["submits"] = True
        self.add(step)

    def typing(self, args: dict[str, Any], text: str) -> None:
        found = code_targets(text)
        given = self.given(args)
        target = self.target(given, found[0] if found else None)
        element = str(args.get("element") or "")[:200]
        self.add(self.type_step(args, target, element, str(args.get("text") or ""), given, bool(args.get("submit"))))

    def type_step(self, args: dict[str, Any], target: dict[str, Any], element: str, value: str, given: str,
                  submit: bool) -> dict[str, Any]:
        step: dict[str, Any] = {"action": "type", "target": target}
        if element:
            step["element"] = element
        name = target.get("name") or target.get("value") or target.get("selector") or ""
        if looks_secret(element, name, given, target.get("selector", "")):
            step["secret"] = True
        else:
            step["text"] = value[:MAX_TEXT]
        if submit:
            step["submit"] = True
        if self.submits("browser_type", {**args, "text": value, "submit": submit}, target):
            step["submits"] = True
        return step

    def select(self, args: dict[str, Any], text: str) -> None:
        found = code_targets(text)
        target = self.target(self.given(args), found[0] if found else None)
        values = [str(v)[:500] for v in (args.get("values") or []) if isinstance(v, (str, int))][:20]
        if not values:
            return
        step: dict[str, Any] = {"action": "select", "target": target, "values": values}
        if args.get("element"):
            step["element"] = str(args["element"])[:200]
        self.add(step)

    def press(self, args: dict[str, Any]) -> None:
        key = str(args.get("key") or "")
        if key not in NAMED_KEYS:  # a typed character (maybe of a password) or a shortcut: not kept
            self.ignored["browser_press_key"] += 1
            return
        step: dict[str, Any] = {"action": "press", "key": key}
        if self.submits("browser_press_key", args, {}):
            step["submits"] = True
        self.add(step)

    def fill_form(self, args: dict[str, Any], text: str) -> None:
        fields = [f for f in (args.get("fields") or []) if isinstance(f, dict)]
        found = code_targets(text)
        if len(found) != len(fields):
            found = [{"by": "none"}] * len(fields)
        for field, target in zip(fields, found, strict=True):
            kind, name, value = str(field.get("type") or ""), str(field.get("name") or "")[:200], field.get("value")
            given = self.given(field)
            target = self.target(given, target if target.get("by") != "none" else None)
            if kind == "textbox":
                self.add(self.type_step({}, target, name, str(value if value is not None else ""), given, False))
            elif kind == "combobox" and isinstance(value, str) and value:
                self.add({"action": "select", "target": target, "values": [value[:500]],
                          **({"element": name} if name else {})})
            else:
                self.ignored["browser_fill_form"] += 1
