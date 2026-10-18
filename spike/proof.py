"""Proof package: one chat exported with everything needed to check what happened in it.

The zip holds the transcript, every recorded step (route, plan, tool calls and results, questions, memory used,
files withheld from providers), the model calls of the chat from the call log (tokens, cost, status), the files
tools changed with their SHA-256 before and after, the providers and settings involved (without keys or headers),
the machine and SPIKE version, and a SHA256SUMS of every file in it. It shows the record is complete and unaltered
since export; it is not signed, so it does not prove who exported it.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import sys
import time
import zipfile
from typing import Any

from spike import __version__
from spike.runtime.hardware import detect

PROVIDER_FIELDS = ("id", "kind", "name", "base_url", "model", "paid", "allow_paid", "local", "share_files", "limits")
SETTING_FIELDS = ("custom_instructions", "specialist_instructions", "tool_policies", "tools_enabled", "use_planner",
                  "parallel", "reasoning", "temperature", "max_tokens", "skill_mode", "memory", "local_runtime")
README = """SPIKE proof package
===================

chat.md           the chat, readable: each answer with its specialists, tools, files, questions and costs
chat.json         every message with everything SPIKE recorded for it (meta.events is the run step by step)
calls.json        the model calls made for this chat (provider, model, tokens, cost, status); no message text
file-changes.json files that tools changed: path, SHA-256 before and after, whether the step was undone
manifest.json     SPIKE version, machine, providers (no keys, no headers) and settings in use at export
SHA256SUMS        a checksum of every other file

Check it:   sha256sum -c SHA256SUMS
The package shows the record is complete and has not been changed since export. It is not signed: it does not
prove who made it. File contents are not included, only their checksums; compare them with your copies.
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(ts: float | None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else ""


def _short(value: Any, limit: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f" […] ({len(text)} characters)"


def transcript(conv: dict[str, Any], messages: list[dict[str, Any]], calls: list[dict[str, Any]],
               changes: list[dict[str, Any]]) -> str:
    lines = [f"# {conv['title']}", "", f"Chat `{conv['id']}` · started {_iso(conv['created'])} · "
             f"exported {_iso(time.time())} · SPIKE {__version__}", ""]
    by_call = {c["call_id"]: c for c in changes}
    for m in messages:
        meta = m["meta"]
        if m["role"] == "user":
            lines += [f"## You · {_iso(m['created'])}", "", m["content"], ""]
            continue
        route = meta.get("route") or {}
        names = ", ".join(f"{s.get('name')} ({s.get('provider')} · {s.get('model') or '?'}"
                          f"{' · adapter ' + s['adapter'] if s.get('adapter') else ''})"
                          for s in route.get("specialists") or [])
        lines += [f"## SPIKE · {_iso(m['created'])}", ""]
        if names:
            lines.append(f"- Specialists: {names}; routed by {route.get('method', '?')}")
        if meta.get("memory"):
            lines.append(f"- Memory used: {meta['memory'].get('rules', 0)} rules, "
                         f"{len(meta['memory'].get('notes') or [])} notes")
        for provider, n in (meta.get("privacy") or {}).items():
            lines.append(f"- File passages withheld from {provider}: {n}")
        for ev in meta.get("tools") or []:
            if ev.get("type") == "tool_call":
                lines.append(f"- Tool `{ev['name']}` {_short(ev.get('arguments'), 300)}")
            elif ev.get("type") == "tool_result":
                change = by_call.get(ev["id"])
                files = "; ".join(f"{f['path']} {f.get('before') or 'new'} → {f.get('after') or 'deleted'}"
                                  for f in (change or {}).get("files", []))
                lines.append(f"  - {'ok' if ev.get('ok') else 'failed'}: {_short(ev.get('content'), 300)}"
                             + (f" · files: {files}" if files else "") + (" · undone" if ev.get("undone") else ""))
        for q in meta.get("questions") or []:
            lines.append(f"- Asked you: {q['question']} → {q.get('answer') or 'no answer'}")
        if meta.get("elapsed_s") is not None:
            lines.append(f"- Took {meta['elapsed_s']} s")
        if meta.get("error"):
            lines.append(f"- Error: {meta['error']}")
        lines += ["", m["content"] or "_(no text)_", ""]
    if calls:
        total_in, total_out = sum(c["tokens_in"] for c in calls), sum(c["tokens_out"] for c in calls)
        cost = sum(c["cost"] or 0 for c in calls)
        lines += ["## Model calls", "", f"{len(calls)} calls · {total_in:,} tokens in · {total_out:,} out"
                  + (f" · cost {cost:.4f} at the prices you entered" if any(c["cost"] for c in calls) else ""), "",
                  "| Time (UTC) | Provider | Model | Status | In | Out | Estimated |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {_iso(c['ts'])} | {c['provider']} | {c['model']} | {c['status']} | {c['tokens_in']} | "
                  f"{c['tokens_out']} | {'yes' if c['estimated'] else 'no'} |" for c in calls]
    return "\n".join(lines) + "\n"


def build_proof(conv: dict[str, Any], messages: list[dict[str, Any]], calls: list[dict[str, Any]],
                checkpoints: list[dict[str, Any]], providers: list[dict[str, Any]], settings: dict[str, Any],
                temporary: bool = False) -> bytes:
    changes = [{"call_id": cp["call_id"], "tool": cp["tool"], "at": _iso(cp["created"]),
                "undone": _iso(cp["undone"]) if cp["undone"] else None,
                "files": [{"path": f["path"], "existed": f["existed"], "before": f.get("before"),
                           "after": f.get("after"), **({"too_big": True} if f.get("too_big") else {})}
                          for f in cp["files"]]} for cp in checkpoints]
    used = {s.get("provider_id") for m in messages
            for s in ((m["meta"].get("route") or {}).get("specialists") or [])} | {c["provider_id"] for c in calls}
    hw = detect().to_dict()
    manifest = {
        "format": "spike-proof", "version": 1, "exported_utc": _iso(time.time()), "spike": __version__,
        "chat": {k: conv.get(k) for k in ("id", "title", "mode", "provider_id", "project_id")} |
                {"created_utc": _iso(conv["created"]), "temporary": temporary, "messages": len(messages)},
        "machine": {"platform": platform.platform(), "python": sys.version.split()[0], **hw},
        "providers": [{k: p.get(k) for k in PROVIDER_FIELDS if k in p} for p in providers if p["id"] in used],
        "settings": {k: settings.get(k) for k in SETTING_FIELDS if k in settings},
    }
    files = {
        "README.txt": README,
        "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False),
        "chat.json": json.dumps({"conversation": conv, "messages": messages}, indent=2, ensure_ascii=False),
        "calls.json": json.dumps(calls, indent=2, ensure_ascii=False),
        "file-changes.json": json.dumps(changes, indent=2, ensure_ascii=False),
        "chat.md": transcript(conv, messages, calls, changes),
    }
    blobs = {name: text.encode("utf-8") for name, text in files.items()}
    sums = "".join(f"{_sha(data)}  {name}\n" for name, data in blobs.items())
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in [*blobs.items(), ("SHA256SUMS", sums.encode())]:
            zf.writestr(name, data)
    return out.getvalue()
