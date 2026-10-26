"""The actions a computer-use model can ask for, checked and described for the approval card, and which of them always
ask. Names are the computer-use tool's own (`left_click`, `type`, `key`, ...). Anything the driver cannot do safely
(zoom, holding a key, pressing the mouse button without releasing it) is refused with a clear message instead of
guessed. The approval itself is in `session.py`; this module only says what an action is and how sensitive it is."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PASSIVE = frozenset({"screenshot", "cursor_position", "wait"})  # they change nothing: no approval card
CLICKS = {"left_click": ("left", 1), "right_click": ("right", 1), "middle_click": ("middle", 1),
          "double_click": ("left", 2), "triple_click": ("left", 3)}
KNOWN = PASSIVE | set(CLICKS) | {"mouse_move", "left_click_drag", "scroll", "type", "key"}
NOT_OFFERED = frozenset({"zoom", "hold_key", "left_mouse_down", "left_mouse_up"})  # the toolset members SPIKE turns off
MAX_WAIT_S = 30.0
MAX_SCROLL = 30
MAX_REPEAT = 100
MAX_TEXT = 4000
DIRECTIONS = ("up", "down", "left", "right")
Point = tuple[int, int]


class ActionError(ValueError):
    """The model asked for something malformed or not offered. The message goes back to the model as the result."""


@dataclass(frozen=True)
class Action:
    name: str
    coordinate: Point | None = None  # in the screenshot the model saw
    start: Point | None = None  # where a drag begins
    text: str | None = None  # typed text, a key or combination, or held modifier keys
    direction: str = ""
    amount: int = 0
    duration: float = 0.0
    repeat: int = 1

    @property
    def passive(self) -> bool:
        return self.name in PASSIVE


def _point(value: Any, what: str) -> Point:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)):
        raise ActionError(f"{what} must be [x, y]")
    x, y = round(value[0]), round(value[1])
    if x < 0 or y < 0:
        raise ActionError(f"{what} is outside the screen")
    return x, y


def parse_action(name: str, args: Mapping[str, Any]) -> Action:
    """The call `name` with its input as an Action, or ActionError."""
    if name in NOT_OFFERED:
        raise ActionError(f"'{name}' is not available on this computer: use the other actions")
    if name not in KNOWN:
        raise ActionError(f"unknown action '{name}'")
    args = args if isinstance(args, Mapping) else {}
    text = args.get("text")
    if text is not None and not isinstance(text, str):
        raise ActionError("'text' must be a string")
    if text is not None and len(text) > MAX_TEXT:
        raise ActionError(f"'text' is longer than {MAX_TEXT} characters: type it in parts")
    coordinate = _point(args["coordinate"], "'coordinate'") if args.get("coordinate") is not None else None
    if name in ("mouse_move", "left_click_drag") and coordinate is None:
        raise ActionError("'coordinate' is required")
    start = None
    if name == "left_click_drag":
        if args.get("start_coordinate") is None:
            raise ActionError("'start_coordinate' is required")
        start = _point(args["start_coordinate"], "'start_coordinate'")
    if name in ("type", "key") and not text:
        raise ActionError("'text' is required")
    direction, amount = "", 0
    if name == "scroll":
        direction = str(args.get("scroll_direction") or "")
        if direction not in DIRECTIONS:
            raise ActionError("'scroll_direction' must be up, down, left or right")
        raw = args.get("scroll_amount", 3)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise ActionError("'scroll_amount' must be a number")
        amount = min(max(round(raw), 1), MAX_SCROLL)
    duration = 0.0
    if name == "wait":
        raw = args.get("duration", 1)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
            raise ActionError("'duration' must be a number of seconds")
        duration = min(float(raw), MAX_WAIT_S)
    repeat = 1
    if name == "key" and args.get("repeat") is not None:
        raw = args["repeat"]
        if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= MAX_REPEAT:
            raise ActionError(f"'repeat' must be a whole number from 1 to {MAX_REPEAT}")
        repeat = raw
    return Action(name, coordinate, start, text, direction, amount, duration, repeat)


# --------------------------------------------------------------------------- what the card shows
def summary(a: Action, masked: bool = False) -> str:
    """One English line for the record (the app writes its own in the user's language from `describe`)."""
    at = f" at ({a.coordinate[0]}, {a.coordinate[1]})" if a.coordinate else " at the mouse position"
    if a.name in CLICKS:
        return f"{a.name.removesuffix('_click').replace('_', ' ')} click{at}"
    if a.name == "mouse_move":
        return f"move the mouse to ({a.coordinate[0]}, {a.coordinate[1]})" if a.coordinate else "move the mouse"
    if a.name == "left_click_drag" and a.start and a.coordinate:
        return f"drag from ({a.start[0]}, {a.start[1]}) to ({a.coordinate[0]}, {a.coordinate[1]})"
    if a.name == "scroll":
        return f"scroll {a.direction} {a.amount}" + (f" at ({a.coordinate[0]}, {a.coordinate[1]})" if a.coordinate else "")
    if a.name == "type":
        shown = f"{len(a.text or '')} characters, hidden" if masked else f"“{shown_text(a.text or '')}”"
        return f"type {shown}"
    if a.name == "key":
        return f"press {a.text}" + (f" x{a.repeat}" if a.repeat > 1 else "")
    if a.name == "wait":
        return f"wait {a.duration:g} s"
    return a.name.replace("_", " ")


def shown_text(text: str, limit: int = 200) -> str:
    text = text.replace("\n", "⏎").replace("\t", "⇥")
    return text if len(text) <= limit else text[:limit] + "…"


def describe(a: Action, masked: bool = False) -> dict[str, Any]:
    """The structured action for the card and the record. A masked text (a password) is never included."""
    out: dict[str, Any] = {"name": a.name}
    if a.coordinate:
        out["x"], out["y"] = a.coordinate
    if a.start:
        out["from_x"], out["from_y"] = a.start
    if a.name == "type":
        out["chars"] = len(a.text or "")
        if not masked:
            out["text"] = shown_text(a.text or "")
    elif a.text:
        out["key" if a.name == "key" else "modifiers"] = a.text
    if a.direction:
        out["direction"], out["amount"] = a.direction, a.amount
    if a.repeat > 1:
        out["repeat"] = a.repeat
    if a.name == "wait":
        out["seconds"] = a.duration
    return out


REGION_W, REGION_H = 360, 220


def region_for(a: Action, width: int, height: int) -> dict[str, Any] | None:
    """The part of the screenshot (`width` x `height`) the card shows: a box around the point(s) the action touches,
    with the points inside it, or None for an action that does not point anywhere."""
    points = [p for p in (a.start, a.coordinate) if p]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    w, h = min(max(REGION_W, max(xs) - min(xs) + 120), width), min(max(REGION_H, max(ys) - min(ys) + 120), height)
    x = min(max((min(xs) + max(xs)) // 2 - w // 2, 0), width - w)
    y = min(max((min(ys) + max(ys)) // 2 - h // 2, 0), height - h)
    return {"x": x, "y": y, "w": w, "h": h, "image_w": width, "image_h": height,
            "points": [{"x": px, "y": py} for px, py in points]}


# --------------------------------------------------------------------------- which actions always ask
@dataclass(frozen=True)
class Sensitive:
    """An action that always asks, never inside an "approve the next N" batch. `kind`: purchase | send | delete |
    password | submit | close | labelled (the model said so without saying why). `reason` is English."""

    kind: str
    reason: str


LABEL = re.compile(r"\[\s*(?:SENSITIVE|SENSIBLE)\s*(?::\s*([A-Za-z _-]{0,40}))?\]", re.I)
WORDS = {
    "purchase": r"buy|purchase|pay|payment|checkout|check\s*out|place\s+(?:the\s+)?order|order\s+now|subscribe|donate|"
                r"book(?:ing)?|comprar?|compra|pagar|pago|pedido|suscrib\w*|donar|reservar",
    "send": r"send|submit|post|publish|share|e-?mail|transfer|upload|reply|enviar?|envía|mandar|publicar|compartir|"
            r"transferir|subir|responder",
    "delete": r"delete|remove|erase|wipe|format|uninstall|empty\s+(?:the\s+)?trash|discard|borrar|eliminar|quitar|"
              r"vaciar|desinstalar|formatear",
}
PASSWORD_WORDS = re.compile(
    r"\b(pass(?:word|code|phrase)s?|contrase[ñn]as?|clave|pin|cvv|cvc|security\s+code|c[oó]digo\s+de\s+seguridad|"
    r"credit\s+card|card\s+number|tarjeta|2fa|otp|verification\s+code|c[oó]digo\s+de\s+verificaci[oó]n|secret)\b", re.I)
KIND_WORDS = {kind: re.compile(rf"\b(?:{words})\b", re.I) for kind, words in WORDS.items()}
KINDS = ("purchase", "send", "delete", "password")


def key_sensitivity(a: Action) -> Sensitive | None:
    from spike.desktop.driver import DriverError, parse_key

    try:
        mods, key = parse_key(a.text or "")
    except DriverError:
        return None
    if key == "Return":
        return Sensitive("submit", "presses Enter, which may send a form or confirm a dialog")
    if key == "Delete" or (key == "BackSpace" and "super" in mods):
        return Sensitive("delete", "presses a delete key, which may delete files or text")
    if (key == "F4" and "alt" in mods) or (key == "q" and set(mods) & {"ctrl", "super"}):
        return Sensitive("close", "closes the program, which may lose unsaved work")
    return None


def classify(a: Action, commentary: str, secure_field: bool | None = None) -> Sensitive | None:
    """Why `a` must always ask, or None. `commentary` is the model's own words in the same reply (it is asked to tag
    purchases, sends and deletions with [SENSITIVE: kind]; SPIKE also reads the words themselves, in English and
    Spanish). `secure_field`: what the driver says about the focused field, when it can tell."""
    if a.passive:
        return None
    if a.name == "type" and secure_field:
        return Sensitive("password", "types into a password field")
    if label := LABEL.search(commentary):
        kind = (label.group(1) or "").strip().lower()
        return Sensitive(kind if kind in KINDS else "labelled",
                         f"the model marked this action as sensitive{f' ({kind})' if kind else ''}")
    if a.name == "type" and PASSWORD_WORDS.search(commentary):
        return Sensitive("password", "the model is typing something that looks like a password or a payment code")
    if a.name == "key" and (found := key_sensitivity(a)):
        return found
    if a.name == "type" and re.search(r"[\r\n]", a.text or ""):
        return Sensitive("submit", "types a line break, which may send a form")
    for kind, pattern in KIND_WORDS.items():
        if pattern.search(commentary):
            return Sensitive(kind, f"the model's own words mention a {kind}")
    return None
