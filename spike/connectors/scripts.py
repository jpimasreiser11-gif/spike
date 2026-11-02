"""Recorded Spike View scripts (A16): the file format, what a step may be, the selector a step is replayed with, and the
folder where the scripts are kept.

A script is a local JSON file written in UTF-8, for example:

    {"format": "spike-view-script", "version": 1, "name": "Order", "created": "2026-11-02T10:00:00+00:00", "steps": [
      {"action": "navigate", "url": "https://shop.example/order"},
      {"action": "type", "target": {"by": "role", "role": "textbox", "name": "Name", "exact": false},
       "element": "Name textbox", "text": "Ana"},
      {"action": "type", "target": {"by": "role", "role": "textbox", "name": "Password", "exact": false},
       "element": "Password textbox", "secret": true},
      {"action": "click", "target": {"by": "role", "role": "button", "name": "Send order", "exact": false},
       "element": "Send order button", "submits": true}]}

Steps are only navigate, click, type, select and press; there is no step that runs code, uploads a file or reads the
page, so a script from anywhere can do no more than a person could by hand. A `secret` type step has no text: the
replay asks for it. A step with `submits` is one the recorder saw submit (or that may): the replay asks before it.
Targets are what Playwright itself reported for the element (by role and name, label, text and so on), never a
snapshot reference, which is only valid for one snapshot."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spike.connectors import browser

FORMAT = "spike-view-script"
VERSION = 1
MAX_STEPS = 500
MAX_TEXT = 10_000
ACTIONS = ("navigate", "click", "type", "select", "press")
BYS = ("role", "label", "text", "placeholder", "title", "alt", "testid", "css", "none")
NAMED_KEYS = ("Enter", "Tab", "Escape", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
              "Home", "End", "PageUp", "PageDown")  # a key that is not a character: typed characters are never kept
ROLE = re.compile(r"[a-z][a-z-]{0,30}")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
MAX_LISTED = 200


class ScriptError(ValueError):
    """A script that is not valid, or not there. `code` is `not_found` or `invalid`."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-") or "guion"


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def selector_of(target: dict[str, Any]) -> str | None:
    """The `target` string the browser tools take for this element (Playwright's selector syntax), or None when the
    target could not be recorded as one robust selector."""
    by = target.get("by")
    flag = "s" if target.get("exact") else "i"
    if by == "role":
        name = target.get("name") or ""
        out = f"internal:role={target['role']}" + (f"[name={quote(name)}{flag}]" if name else "")
    elif by == "label":
        out = f"internal:label={quote(target['value'])}{flag}"
    elif by == "text":
        out = f"internal:text={quote(target['value'])}{flag}"
    elif by in ("placeholder", "title", "alt"):
        out = f"internal:attr=[{by}={quote(target['value'])}{flag}]"
    elif by == "testid":
        out = f"internal:testid=[data-testid={quote(target['value'])}s]"
    elif by == "css":
        out = target["selector"]
    else:
        return None
    if target.get("nth") is not None:
        out += f" >> nth={target['nth']}"
    return out


def target_name(step: dict[str, Any]) -> str:
    """A short name for what a step acts on, to show to the user."""
    target = step.get("target") or {}
    by = target.get("by")
    if by == "role":
        return target.get("name") or target.get("role") or ""
    if by == "css":
        return target.get("selector", "")
    if by in ("label", "text", "placeholder", "title", "alt", "testid"):
        return target.get("value", "")
    return step.get("element", "")


def describe(step: dict[str, Any]) -> dict[str, Any]:
    """What the app may show about a step: never the text of a secret step (it has none)."""
    out: dict[str, Any] = {"action": step["action"], "name": target_name(step)[:120]}
    if step["action"] == "navigate":
        out["url"] = step["url"]
    elif step["action"] == "press":
        out["key"] = step["key"]
    elif step["action"] == "type":
        if step.get("secret"):
            out["secret"] = True
        else:
            out["text"] = step.get("text", "")[:200]
    elif step["action"] == "select":
        out["values"] = step["values"]
    if step.get("submits") or step.get("submit"):
        out["submits"] = True
    return out


def string(value: Any, what: str, limit: int, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty) or len(value) > limit:
        raise ScriptError(f"{what} must be text of up to {limit} characters")
    return value


def clean_target(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("by") not in BYS:
        raise ScriptError("a step needs a target made by Spike (role, label, text, placeholder, title, alt, testid or css)")
    by = raw["by"]
    out: dict[str, Any] = {"by": by}
    if by == "role":
        role = raw.get("role")
        if not isinstance(role, str) or not ROLE.fullmatch(role):
            raise ScriptError("the role of a target is a word such as button or textbox")
        out |= {"role": role, "name": string(raw.get("name", ""), "the name of a target", 500, empty=True),
                "exact": bool(raw.get("exact"))}
    elif by in ("label", "text", "placeholder", "title", "alt", "testid"):
        out |= {"value": string(raw.get("value"), "the value of a target", 500), "exact": bool(raw.get("exact"))}
    elif by == "css":
        out["selector"] = string(raw.get("selector"), "the selector of a target", 500)
    nth = raw.get("nth")
    if nth is not None and by != "none":
        if isinstance(nth, bool) or not isinstance(nth, int) or not -1 <= nth <= 999:
            raise ScriptError("nth must be a whole number from -1 to 999")
        out["nth"] = nth
    return out


def clean_step(raw: Any, number: int) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("action") not in ACTIONS:
        raise ScriptError(f"step {number + 1}: the action must be one of {', '.join(ACTIONS)}")
    action = raw["action"]
    out: dict[str, Any] = {"action": action}
    try:
        if action == "navigate":
            url = string(raw.get("url"), "the address", 2000)
            if web_host(url) is None:
                raise ScriptError("only web pages (http or https) can be opened")
            out["url"] = url
        elif action == "press":
            if raw.get("key") not in NAMED_KEYS:
                raise ScriptError(f"a key must be one of {', '.join(NAMED_KEYS)}: typed characters are not kept")
            out["key"] = raw["key"]
        else:
            out["target"] = clean_target(raw.get("target"))
            if raw.get("element") is not None:
                out["element"] = string(raw["element"], "the description", 200, empty=True)
            if action == "click" and raw.get("double"):
                out["double"] = True
            if action == "type":
                if raw.get("secret"):
                    if "text" in raw:
                        raise ScriptError("a secret step keeps no text")
                    out["secret"] = True
                else:
                    out["text"] = string(raw.get("text", ""), "the text", MAX_TEXT, empty=True)
                if raw.get("submit"):
                    out["submit"] = True
            if action == "select":
                values = raw.get("values")
                if not isinstance(values, list) or not 1 <= len(values) <= 20:
                    raise ScriptError("values must be a list of 1 to 20 options")
                out["values"] = [string(v, "an option", 500, empty=True) for v in values]
        if raw.get("submits"):
            out["submits"] = True
    except ScriptError as exc:
        raise ScriptError(f"step {number + 1}: {exc}") from exc
    return out


def web_host(url: str) -> str | None:
    """The host of a web address, or None when it is not an http(s) page."""
    host = browser.host_of(url)
    return host if host and url.strip().lower().startswith(("http://", "https://")) else None


def validate(raw: Any) -> dict[str, Any]:
    """The script cleaned to what Spike keeps, or ScriptError. Unknown fields are dropped."""
    if not isinstance(raw, dict):
        raise ScriptError("a script is a JSON object")
    if raw.get("format", FORMAT) != FORMAT or raw.get("version", VERSION) != VERSION:
        raise ScriptError(f"this is not a version {VERSION} Spike View script")
    name = raw.get("name", "")
    if not isinstance(name, str) or len(name.strip()) > 120:
        raise ScriptError("the name is text of up to 120 characters")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ScriptError(f"a script has 1 to {MAX_STEPS} steps")
    created = raw.get("created")
    return {"format": FORMAT, "version": VERSION, "name": name.strip() or "Script",
            "created": created[:40] if isinstance(created, str) else datetime.now(UTC).isoformat(timespec="seconds"),
            "steps": [clean_step(s, i) for i, s in enumerate(steps)]}


class ScriptStore:
    """The scripts of one folder, one `<id>.json` file each. An id is lowercase letters, digits and hyphens, so no id
    can name a file outside the folder."""

    def __init__(self, folder: Path):
        self.folder = folder

    def path(self, sid: str) -> Path:
        if not isinstance(sid, str) or not ID.fullmatch(sid):
            raise ScriptError("there is no such script", "not_found")
        return self.folder / f"{sid}.json"

    def read(self, sid: str) -> dict[str, Any]:
        path = self.path(sid)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ScriptError("there is no such script", "not_found") from exc
        except (OSError, ValueError) as exc:
            raise ScriptError(f"the file cannot be read: {exc.__class__.__name__}") from exc
        return validate(raw)

    get = read

    def list(self) -> list[dict[str, Any]]:
        if not self.folder.is_dir():
            return []
        out = []
        for path in sorted(self.folder.glob("*.json"), key=lambda p: p.stem)[:MAX_LISTED]:
            if not ID.fullmatch(path.stem):
                continue
            try:
                script = self.read(path.stem)
                out.append({"id": path.stem, "name": script["name"], "created": script["created"],
                            "steps": len(script["steps"])})
            except ScriptError as exc:
                out.append({"id": path.stem, "error": str(exc)[:200]})
        return out

    def write(self, sid: str, script: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.path(sid)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def save(self, script: dict[str, Any]) -> str:
        """Keep a new script under an id made from its name; returns the id."""
        clean = validate(script)
        base = slug(str(script.get("name") or ""))
        sid, n = base, 1
        while self.path(sid).exists():
            n += 1
            sid = f"{base}-{n}"
        self.write(sid, clean)
        return sid

    def delete(self, sid: str) -> bool:
        try:
            path = self.path(sid)
            path.unlink()
        except (ScriptError, FileNotFoundError):
            return False
        return True

    def make_secret(self, sid: str, index: int) -> dict[str, Any]:
        """Turn a typing step into one that asks for its text when replayed, and drop the text from the file."""
        script = self.read(sid)
        steps = script["steps"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(steps) \
                or steps[index]["action"] != "type":
            raise ScriptError("that step does not type text")
        steps[index].pop("text", None)
        steps[index]["secret"] = True
        self.write(sid, script)
        return script
