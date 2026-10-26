"""Built-in tools. Each one is real, bounded and permission-gated according to its risk."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import datetime as dt
import functools
import html
import ipaddress
import math
import operator
import os
import re
import socket
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from spike.tools.base import Review, Tool, ToolRegistry, ToolResult
from spike.tools.documents import document_tools
from spike.tools.sandbox import Sandbox, SandboxRefused, default_sandbox, with_note

# --------------------------------------------------------------------------- calculator
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {name: getattr(math, name) for name in (
    "sqrt", "log", "log10", "log2", "exp", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh",
    "tanh", "floor", "ceil", "factorial", "comb", "perm", "gcd", "degrees", "radians", "fabs", "hypot")}
_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max, "sum": lambda *a: sum(a)})
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(expr: str) -> float | int:
    tree = ast.parse(expr.replace("^", "**"), mode="eval")

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10_000:
                raise ValueError("exponent too large")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"unsupported expression element: {ast.dump(node)[:60]}")

    return ev(tree)


class Calculator(Tool):
    name = "calculator"
    description = "Evaluate an arithmetic expression exactly (supports + - * / // % ** and math functions like sqrt, log, exp, sin)."
    parameters = {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}
    risk = "safe"
    default_policy = "allow"

    async def run(self, args: dict[str, Any]) -> ToolResult:
        expr = str(args.get("expression", ""))
        try:
            value = safe_eval(expr)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        return ToolResult(ok=True, content=f"{expr} = {value!r}", data={"value": value})


class AskUser(Tool):
    """Human handoff: the run pauses on a question card in the app and goes on with the user's answer. The agent loop
    handles it (it needs the user, not code); `run` is only reached outside the app's loop."""

    name = "ask_user"
    description = ("Ask the user a question and wait for the answer, when you cannot continue well without "
                   "information or a decision only they have (a missing detail, a choice between options). Do not "
                   "use it for what you can find out or safely assume.")
    parameters = {"type": "object", "properties": {
        "question": {"type": "string", "description": "one clear question"},
        "options": {"type": "array", "items": {"type": "string"},
                    "description": "optional short answers to pick from (2 to 4)"},
    }, "required": ["question"]}

    async def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=False, content=NO_ONE_TO_ASK)


NO_ONE_TO_ASK = ("error: nobody can answer questions here; continue with your best assumption and say what you "
                 "assumed")


class CurrentTime(Tool):
    name = "current_time"
    description = "Return the current date and time, optionally for an IANA timezone such as 'Europe/Madrid'."
    parameters = {"type": "object", "properties": {"timezone": {"type": "string"}}}

    async def run(self, args: dict[str, Any]) -> ToolResult:
        tz_name = args.get("timezone")
        if tz_name:
            try:
                from zoneinfo import ZoneInfo

                now = dt.datetime.now(ZoneInfo(str(tz_name)))
            except Exception:
                return ToolResult(ok=False, content=f"error: unknown timezone '{tz_name}'")
        else:
            now = dt.datetime.now().astimezone()
        return ToolResult(ok=True, content=now.isoformat(timespec="seconds"))


# --------------------------------------------------------------------------- workspace files
class Workspace:
    """All file tools are confined to one root directory chosen by the user."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError(f"path '{relative}' is outside the workspace")
        return candidate


class ReadFile(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file from the workspace. Large files are truncated."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer"}},
                  "required": ["path"]}
    risk = "read"
    default_policy = "allow"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            path = self.workspace.resolve(str(args["path"]))
            limit = min(int(args.get("max_chars", 20_000)), 200_000)
            text = path.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, FileNotFoundError, IsADirectoryError, KeyError, ValueError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        suffix = f"\n[truncated {len(text) - limit} chars]" if len(text) > limit else ""
        return ToolResult(ok=True, content=text[:limit] + suffix, private=[text[:limit]])


class ListDir(Tool):
    name = "list_dir"
    description = "List files and folders in a workspace directory."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
    risk = "read"
    default_policy = "allow"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            path = self.workspace.resolve(str(args.get("path", ".")))
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:500]
        except (PermissionError, FileNotFoundError, NotADirectoryError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        lines = [f"{'dir ' if p.is_dir() else 'file'} {p.relative_to(self.workspace.root)}" for p in entries]
        return ToolResult(ok=True, content="\n".join(lines) or "(empty)")


class WriteFile(Tool):
    name = "write_file"
    description = "Create or overwrite a UTF-8 text file in the workspace."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                  "required": ["path", "content"]}
    risk = "write"
    default_policy = "ask"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def targets(self, args: dict[str, Any]) -> list[Path]:
        try:
            return [self.workspace.resolve(str(args["path"]))]
        except (PermissionError, KeyError):
            return []

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            path = self.workspace.resolve(str(args["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            content = str(args.get("content", ""))
            path.write_text(content, encoding="utf-8")
        except (PermissionError, KeyError, IsADirectoryError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        rel = path.relative_to(self.workspace.root).as_posix()
        return ToolResult(ok=True, content=f"wrote {len(content)} chars to {rel}", data={"file": rel})


# --------------------------------------------------------------------------- python
class PythonRunner(Tool):
    name = "python"
    description = ("Run a short Python 3 script in a separate subprocess with a temporary working directory (20 s CPU limit, "
                   "512 MB memory on Linux) and return stdout/stderr. Where the computer has a sandbox (bubblewrap on "
                   "Linux, sandbox-exec on macOS) the script has no network and writes only in that directory; the last "
                   "line of the result says whether it was isolated. Use print() to show results.")
    parameters = {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}
    risk = "execute"
    default_policy = "ask"

    def __init__(self, timeout_s: float = 30.0, memory_mb: int = 512, sandbox: Sandbox | None = None,
                 readable: Sequence[Path] = ()):
        self.timeout_s = timeout_s
        self.memory_mb = memory_mb
        self.sandbox = sandbox or default_sandbox()
        self.readable = list(readable)  # folders the script may read (not write) when isolated: the workspace

    def _limits(self, new_session: bool = True) -> None:  # runs in the child before exec (POSIX only)
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        mem = self.memory_mb * 1024 * 1024
        with contextlib.suppress(ValueError, OSError):  # macOS does not enforce RLIMIT_AS
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        if new_session:  # bubblewrap starts its own session, and a session leader cannot start another
            os.setsid()

    def prepare(self, folder: Path, args: dict[str, Any]) -> None:
        """Put what the script needs in its temporary folder (data_python copies the user's files here)."""

    def review(self, args: dict[str, Any]) -> Review | None:
        return self.sandbox.review()  # `required` and no sandbox: refused before anyone is asked

    def isolation(self, args: dict[str, Any]) -> dict[str, Any] | None:
        return self.sandbox.isolation().to_dict()

    async def run(self, args: dict[str, Any]) -> ToolResult:
        code = str(args.get("code", ""))
        with tempfile.TemporaryDirectory(prefix="spike-py-") as tmp:
            self.prepare(Path(tmp), args)
            script = Path(tmp) / "main.py"
            script.write_text(code, encoding="utf-8")
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "HOME": tmp}
            try:
                with self.sandbox.wrapped([sys.executable, "-I", str(script)], cwd=tmp, writable=[tmp],
                                          readable=self.readable) as box:
                    proc = await asyncio.create_subprocess_exec(
                        *box.argv, cwd=tmp, env={**env, **box.env},
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        preexec_fn=functools.partial(self._limits, box.new_session) if os.name == "posix" else None,
                    )
                    try:
                        out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                        return ToolResult(ok=False, content=with_note(f"error: timed out after {self.timeout_s:.0f}s",
                                                                      box.isolation),
                                          data={"isolation": box.isolation.to_dict()})
            except SandboxRefused as exc:
                return ToolResult(ok=False, content=f"error: {exc}", data={"isolation": exc.isolation.to_dict()})
        text = out.decode("utf-8", "replace")[-20_000:]
        errors = err.decode("utf-8", "replace")[-8_000:]
        content = text + (f"\n[stderr]\n{errors}" if errors else "")
        return ToolResult(ok=proc.returncode == 0, content=with_note(content.strip() or "(no output)", box.isolation),
                          data={"returncode": proc.returncode, "isolation": box.isolation.to_dict()})


# --------------------------------------------------------------------------- web fetch
def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class WebFetch(Tool):
    name = "web_fetch"
    description = "Fetch a public http(s) URL and return its readable text (HTML is converted to text)."
    parameters = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
    risk = "network"
    default_policy = "ask"
    max_bytes = 2_000_000

    def __init__(self, client: httpx.AsyncClient | None = None, allow_private: bool = False):
        self.client = client
        self.allow_private = allow_private

    async def run(self, args: dict[str, Any]) -> ToolResult:
        url = str(args.get("url", ""))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ToolResult(ok=False, content="error: only absolute http(s) URLs are allowed")
        if not self.allow_private and not await asyncio.to_thread(_is_public_host, parsed.hostname):
            return ToolResult(ok=False, content="error: private, local or unresolvable addresses are blocked")
        client = self.client or httpx.AsyncClient(timeout=20.0, follow_redirects=False)
        try:
            async with client.stream("GET", url, headers={"User-Agent": "SPIKE/0.1 (+https://github.com/)"}) as resp:
                if resp.is_redirect:
                    return ToolResult(ok=False, content=f"redirect to {resp.headers.get('location')} (call again with that URL)")
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > self.max_bytes:
                        break
                ctype = resp.headers.get("content-type", "")
                status = resp.status_code
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, content=f"error: {exc.__class__.__name__}: {exc}")
        finally:
            if self.client is None:
                await client.aclose()
        text = body.decode("utf-8", "replace")
        if "html" in ctype:
            text = html_to_text(text)
        return ToolResult(ok=200 <= status < 300, content=f"[HTTP {status}] {url}\n\n{text[:30_000]}")


def default_registry(workspace_root: Path, sandbox: Sandbox | None = None) -> ToolRegistry:
    ws = Workspace(workspace_root)
    return ToolRegistry([
        Calculator(), CurrentTime(), AskUser(), ReadFile(ws), ListDir(ws), WriteFile(ws),
        PythonRunner(sandbox=sandbox, readable=[ws.root]), WebFetch(), *document_tools(ws),
    ])
