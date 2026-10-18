"""Run the real SPIKE app with a scripted test provider (for UI end-to-end tests only).

The scripted provider streams canned answers with small delays so the UI can be exercised without a model.
It is never registered in the product; it lives under tests/.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402

from spike.connectors.manager import Connection, McpTool  # noqa: E402
from spike.connectors.mcp import APP_MIME, CallResult  # noqa: E402
from spike.core.types import Capabilities, StreamEvent, ToolCall  # noqa: E402
from spike.providers.base import Provider  # noqa: E402
from spike.server.app import create_app  # noqa: E402
from spike.server.state import AppState  # noqa: E402

# An artifact that probes its sandbox: it reports whether it could read storage, reach the parent page or call
# SPIKE's API. The browser test expects all three blocked.
PROBE_PAGE = """<!doctype html><html><head><title>Prueba de aislamiento</title></head><body>
<h1>Hola desde un artefacto</h1><p id="out">...</p>
<script>
const r = [];
try { localStorage.getItem("spike-theme"); r.push("storage:open"); } catch (e) { r.push("storage:blocked"); }
try { r.push(parent.document.title !== undefined ? "parent:open" : "parent:blocked"); } catch (e) { r.push("parent:blocked"); }
fetch("/api/conversations").then(() => r.push("api:open"), () => r.push("api:blocked"))
  .finally(() => { document.getElementById("out").textContent = r.join(" "); });
</script></body></html>"""


BLUEPRINT = {"goal": "Informe del IVA de 120 €", "requirements": ["IVA del 21 %"], "criteria": [
    "El informe da el total con IVA"], "steps": [
    {"id": "t1", "specialist": "finance", "role": "research", "instruction": "Calcula el IVA de una base de 120 €",
     "depends_on": [], "deliverables": []},
    {"id": "t2", "specialist": "writing", "role": "execute", "instruction": "Escribe informe.md con el total con IVA",
     "depends_on": ["t1"], "deliverables": ["informe.md"]}]}
SENT_BACK: set[str] = set()  # Forge tasks whose first check already sent work back


def checker_answer(request) -> str:
    """The checker: a Forge task's writer is sent back once, then everything passes."""
    criteria = request.json_schema["properties"].get("criteria")
    n = criteria["items"]["properties"]["n"]["maximum"] if criteria else 0
    task = request.messages[-1].content.split("\n\n")[0]
    results = []
    if n and task not in SENT_BACK:
        SENT_BACK.add(task)
        results = [{"id": "t2", "ok": False, "fix": "Añade el total con IVA (145,20 €) al informe."}]
    return json.dumps({"results": results, **({"criteria": [{"n": i, "ok": True, "note": ""}
                                                           for i in range(1, n + 1)]} if n else {})})


class DemoProvider(Provider):
    def default_capabilities(self):
        return Capabilities(native_tools=True, adapters=False)

    async def list_models(self):
        return ["scripted-test-model"]

    async def stream(self, request):
        system = request.messages[0].content if request.messages else ""
        last = request.messages[-1]
        props = (request.json_schema or {}).get("properties", {})
        if "steps" in props:  # a Forge blueprint
            yield StreamEvent(kind="text", text=json.dumps(BLUEPRINT))
            yield StreamEvent(kind="done")
            return
        if "results" in props:  # the checker of a multi-step run
            yield StreamEvent(kind="text", text=checker_answer(request))
            yield StreamEvent(kind="done")
            return
        if request.json_schema is not None and "subtasks" not in json.dumps(request.json_schema):
            yield StreamEvent(kind="text", text='```json\n{"pais": "España", "iva": 21}\n```')  # an answer contract
            yield StreamEvent(kind="done")
            return
        if request.json_schema is not None:
            plan = {"subtasks": [
                {"id": "t1", "specialist": "marketing", "instruction": "Design the launch campaign for the ETF", "depends_on": []},
                {"id": "t2", "specialist": "finance", "instruction": "Estimate the expected ROI of the campaign", "depends_on": ["t1"]},
            ]}
            yield StreamEvent(kind="text", text=json.dumps(plan))
            yield StreamEvent(kind="done")
            return
        tools = {t.name for t in request.tools or []}
        if last.role == "user" and "Save these files" in system and "write_file" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c5", name="write_file", arguments={
                "path": "informe.md", "content": "# Informe\n\nBase 120 €, IVA 25,20 €, total con IVA 145,20 €.\n"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "archivo" in last.content.lower() and request.tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c1", name="write_file",
                              arguments={"path": "notas.md", "content": "# Notas\n"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "word" in last.content.lower() and "create_docx" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c2", name="create_docx", arguments={
                "path": "informes/informe.docx", "content": "# Informe\n\n- Ventas: **+12 %**\n"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "boe" in last.content.lower() and "mcp__playwright__browser_navigate" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c4", name="mcp__playwright__browser_navigate",
                              arguments={"url": "https://www.boe.es/buscar"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "en paper" in last.content.lower() and "paper_order" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c6", name="paper_order", arguments={
                "symbol": "BTC/USDT", "side": "buy", "amount": 0.01}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "orden real" in last.content.lower() and "propose_live_order" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c7", name="propose_live_order", arguments={
                "symbol": "BTC/USDT", "side": "buy", "amount": 0.001}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "con la app" in last.content.lower() and "mcp__prices__get_price" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c8", name="mcp__prices__get_price", arguments={
                "symbol": "BTC"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "factura" in last.content.lower() and "ask_user" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c3", name="ask_user", arguments={
                "question": "¿Para qué país es la factura?", "options": ["España", "Francia"]}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "tool" and last.name == "ask_user":
            answer = f"Entendido ({last.content}). Para España, el IVA general es del **21 %**."
        elif last.role == "user" and "landing" in last.content.lower() and "# Design system:" in system:
            tokens = system.split("```css\n", 1)[1].split("\n```", 1)[0]  # pasted as the design system asks
            answer = ("Tu landing con el sistema de diseño:\n\n```html\n<title>Landing</title>\n<style>" + tokens +
                      "\nbody{background:var(--bg);color:var(--fg);font-family:var(--font-body)}"
                      "\n.cta{background:var(--accent);color:var(--accent-on);border:0;padding:12px 20px;"
                      "border-radius:var(--radius-md)}</style>\n<h1>Landing</h1>\n<button class=\"cta\">Empezar</button>\n```")
        elif last.role == "user" and "página" in last.content.lower():
            answer = "Aquí tienes la página:\n\n```html\n" + PROBE_PAGE + "\n```"
        elif last.role == "user" and "# Project instructions" in system:
            answer = "Respuesta del proyecto: sigo sus instrucciones y uso sus archivos."
        elif last.role == "tool" and last.name == "mcp__prices__get_price":
            answer = "Aquí tienes el precio en la vista de la app."
        elif last.role == "user" and "# What the user sees in app views" in system:
            answer = "En la vista veo: " + system.split("## Precios\n", 1)[1].split("\n", 1)[0]
        elif last.role == "tool" and last.name == "paper_order":
            answer = "Comprados **0,01 BTC** en la cuenta simulada, con comisión y deslizamiento."
        elif last.role == "tool" and last.name == "propose_live_order":
            answer = "Te he propuesto la orden. **No se ha enviado**: confírmala en la tarjeta si la quieres."
        elif last.role == "tool":
            answer = f"He creado el archivo. Resultado de la herramienta: `{last.content}`"
        elif "Spike Finance" in system.split("\n")[0]:
            answer = ("**ROI estimado:** con un presupuesto de 50.000 € y 1.200 nuevos inversores con un ticket medio "
                      "de 2.000 €, el ROI bruto sería del **12 %** (cálculo: `(56.000 - 50.000) / 50.000`).")
        elif "Spike Marketing" in system.split("\n")[0]:
            answer = "1. Público: inversores minoristas de 25-40 años.\n2. Canales: newsletter, YouTube y SEO.\n3. Mensaje: *diversificación sencilla y barata*."
        elif "This is a Forge task" in system:
            answer = "Listo: guardé **informe.md** con la base, el IVA (25,20 €) y el total con IVA (145,20 €)."
        elif "Specialist reports" in last.content:
            answer = ("## Plan de lanzamiento\n\n| Fase | Acción | KPI |\n|---|---|---|\n| 1 | Newsletter + SEO | CTR > 3 % |\n"
                      "| 2 | Vídeos en YouTube | CAC < 40 € |\n\n**ROI esperado:** ~12 % en el primer año, con supuestos explícitos.\n\n"
                      "```python\nroi = (56_000 - 50_000) / 50_000\nprint(f\"{roi:.0%}\")\n```")
        else:
            answer = ("¡Hola! Soy **SPIKE**. Puedo ayudarte con finanzas, medicina, marketing, código y más. "
                      "Este es un proveedor *de prueba* para tests de interfaz.")
        for i in range(0, len(answer), 12):
            yield StreamEvent(kind="text", text=answer[i:i + 12])
            await asyncio.sleep(0.01)
        yield StreamEvent(kind="done", finish_reason="stop")


# An MCP App (SEP-1865) view: it shows the tool's input and result, calls an app-only tool, asks to open a link,
# gives the model context, and probes its sandbox (SPIKE's API and the parent page must both be out of reach).
APP_PAGE = """<!doctype html><html><head><title>Precios</title><style>body{font:15px system-ui;margin:12px}</style></head>
<body><b id="input">…</b> <span id="price">…</span>
<button id="refresh">Actualizar</button> <button id="link">Enlace</button> <button id="ctx">Contexto</button>
<p id="probe">…</p><p id="out"></p>
<script>
let n = 0; const waiting = {};
const send = (m) => parent.postMessage({ jsonrpc: "2.0", ...m }, "*");
const request = (method, params) => new Promise((ok, ko) => { const id = ++n; waiting[id] = { ok, ko }; send({ id, method, params }); });
window.addEventListener("message", (e) => {
  const m = e.data || {};
  if (m.id && waiting[m.id]) { m.error ? waiting[m.id].ko(m.error) : waiting[m.id].ok(m.result); delete waiting[m.id]; return; }
  if (m.method === "ui/notifications/tool-input") document.getElementById("input").textContent = m.params.arguments.symbol;
  if (m.method === "ui/notifications/tool-result") document.getElementById("price").textContent = m.params.structuredContent.price;
});
request("ui/initialize", { appCapabilities: {}, clientInfo: { name: "precios", version: "1" }, protocolVersion: "2026-01-26" })
  .then((r) => { document.getElementById("out").textContent = r.hostInfo.name; send({ method: "ui/notifications/initialized" }); });
document.getElementById("refresh").onclick = async () => {
  const r = await request("tools/call", { name: "refresh_price", arguments: { symbol: "BTC" } });
  document.getElementById("price").textContent = r.structuredContent.price;
};
document.getElementById("link").onclick = () => request("ui/open-link", { url: "https://example.com/" })
  .then(() => { document.getElementById("out").textContent = "opened"; }, () => { document.getElementById("out").textContent = "denied"; });
document.getElementById("ctx").onclick = () => request("ui/update-model-context", { content: [{ type: "text", text: "BTC a 50100 USD" }] })
  .then(() => { document.getElementById("out").textContent = "context sent"; });
const r = [];
try { r.push(parent.document.title !== undefined ? "parent:open" : "parent:blocked"); } catch (e) { r.push("parent:blocked"); }
Promise.allSettled([fetch("/api/health"), fetch("http://127.0.0.1:" + (location.ancestorOrigins?.[0]?.split(":")[2] || "8741") + "/api/health")])
  .then((x) => { r.push(x.every((y) => y.status === "rejected") ? "api:blocked" : "api:open"); document.getElementById("probe").textContent = r.join(" "); });
</script></body></html>"""


class ScriptedApp:
    """Stands in for an MCP server with an app (the real protocol is tested in tests/test_mcp_apps.py)."""

    async def call_tool(self, name, args):
        price = 50_000 if name == "get_price" else 50_100
        raw = {"content": [{"type": "text", "text": f"{args.get('symbol')}: {price}"}],
               "structuredContent": {"symbol": args.get("symbol"), "price": price}, "isError": False}
        return CallResult(text=raw["content"][0]["text"], is_error=False, raw=raw)

    async def read_resource(self, uri):
        return {"contents": [{"uri": uri, "mimeType": APP_MIME, "text": APP_PAGE,
                              "_meta": {"ui": {"csp": {"connectDomains": ["https://api.example.com"]},
                                               "prefersBorder": True}}}]}


class ScriptedBrowser:
    """Stands in for the Playwright MCP server, so the browser guard's questions can be seen in the UI (the real
    browser is exercised in tests/test_browser.py)."""

    async def call_tool(self, name, args):
        return CallResult(text=f"Page URL: {args.get('url')}\nPage Title: BOE", is_error=False)


class ScriptedExchange:
    """Stands in for a ccxt exchange (the real library is tested in tests/test_finance.py with fakes too): fixed
    prices, a test network, and orders recorded instead of sent anywhere."""

    PRICES = {"BTC/USDT": 50_000.0, "ETH/USDT": 2_500.0}
    ORDERS: list = []

    def __init__(self, exchange_id, config=None):
        self.id = exchange_id

    def set_sandbox_mode(self, on):
        pass

    async def fetch_ticker(self, symbol):
        return {"last": self.PRICES.get(symbol, 100.0), "percentage": 1.2, "timestamp": None}

    async def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return []

    async def fetch_balance(self):
        return {"total": {}}

    async def create_order(self, symbol, type_, side, amount, price=None):
        self.ORDERS.append((symbol, side, amount))
        return {"id": f"E2E-{len(self.ORDERS)}", "status": "closed", "filled": amount, "average": 50_010.0}

    async def close(self):
        pass


async def scripted_tuner(model, quick=False):
    """Stands in for spike.tune in UI tests (the real one is tested against llama-server in tests/test_tune.py)."""
    yield {"type": "tune_start", "threads": [4, 2], "gpu_layers": 0, "prompt": 256, "gen": 32}
    for threads, kv, gen in ((4, "q8_0", 9.1), (2, "q8_0", 6.0), (4, "f16", 9.3)):
        await asyncio.sleep(0.2)
        yield {"type": "tune_result", "threads": threads, "kv_cache_type": kv, "gpu_layers": 0, "gen_tok_s": gen,
               "prompt_tok_s": 80.0, "peak_rss_mb": 3100.0}
    best = {"threads": 4, "kv_cache_type": "q8_0", "gpu_layers": 0, "context": 32768}
    yield {"type": "tune_done", "best": best, "report": {"date_utc": "2026-10-17T12:00:00Z", "best": best,
                                                         "results": [], "context": {"measured": False}}}


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="spike-e2e-"))
    os.environ["SPIKE_HOME"] = str(home)
    os.environ["SPIKE_WORKSPACE"] = str(home / "ws")
    os.environ["SPIKE_NO_KEYRING"] = "1"
    state = AppState(home=home, provider_factory=lambda cfg: DemoProvider(cfg), market_factory=ScriptedExchange)
    model = home / "models" / "scripted.gguf"  # only checked for existence: the tuner below is scripted too
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"GGUF")
    state.update_settings({"local_runtime": {**state.settings()["local_runtime"], "model": str(model)}})
    playwright = state.connectors.get("playwright")
    state.connectors.connections["playwright"] = Connection(status="running", tools=[McpTool(
        playwright, ScriptedBrowser(), {"name": "browser_navigate", "inputSchema": {"type": "object"}},
        "mcp__playwright__browser_navigate", "ask", state.connectors._guard(playwright))])
    prices = state.connectors.add_custom({"id": "prices", "name": "Precios", "transport": "stdio",
                                          "command": "scripted"})  # never started: its connection is scripted
    client = ScriptedApp()
    get_price = McpTool(prices, client, {"name": "get_price", "_meta": {"ui": {"resourceUri": "ui://precios/vista"}},
                                         "inputSchema": {"type": "object"}}, "mcp__prices__get_price", "allow")
    refresh = McpTool(prices, client, {"name": "refresh_price", "_meta": {"ui": {
        "resourceUri": "ui://precios/vista", "visibility": ["app"]}}}, "mcp__prices__refresh_price", "ask")
    state.connectors.connections["prices"] = Connection(client=client, status="running", tools=[get_price],
                                                        by_remote={"get_price": get_price, "refresh_price": refresh})
    app = create_app(state, allowed_hosts={"127.0.0.1", "localhost"})  # as `spike serve` runs it
    app.state.tuner = scripted_tuner
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8741")), log_level="warning")


if __name__ == "__main__":
    main()
