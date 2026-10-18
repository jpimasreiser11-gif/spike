"""An MCP server with an MCP App (SEP-1865), built with the official Python SDK (dev dependency): a tool whose
results a `ui://` view shows, a tool only the view may call, and one only the model may call.

Usage: python mcp_app_server.py [stdio | http PORT]
"""

import json
import sys
from typing import TypedDict

from mcp.server.mcpserver import MCPServer

server = MCPServer("spike-app-test")
VIEW = "ui://prices/view"


class Price(TypedDict):
    symbol: str
    price: int


PAGE = """<!doctype html><html><head><title>Prices</title></head><body>
<h1 id="price">…</h1><button id="refresh">Refresh</button><p id="log"></p>
<script>
let id = 0; const waiting = {};
function request(method, params) {
  const n = ++id; parent.postMessage({ jsonrpc: "2.0", id: n, method, params }, "*");
  return new Promise((ok, ko) => { waiting[n] = { ok, ko }; });
}
window.addEventListener("message", (e) => {
  const m = e.data || {};
  if (m.id && waiting[m.id]) { m.error ? waiting[m.id].ko(m.error) : waiting[m.id].ok(m.result); delete waiting[m.id]; return; }
  if (m.method === "ui/notifications/tool-result") document.getElementById("price").textContent = m.params.structuredContent.price;
});
request("ui/initialize", { appCapabilities: {}, clientInfo: { name: "prices", version: "1" }, protocolVersion: "2026-01-26" })
  .then(() => parent.postMessage({ jsonrpc: "2.0", method: "ui/notifications/initialized" }, "*"));
document.getElementById("refresh").onclick = async () => {
  const r = await request("tools/call", { name: "refresh_price", arguments: { symbol: "BTC" } });
  document.getElementById("price").textContent = r.structuredContent.price;
};
</script></body></html>"""


@server.tool(meta={"ui": {"resourceUri": VIEW}}, structured_output=True)
def get_price(symbol: str) -> Price:
    """Current price of an asset, shown in an interactive view."""
    return {"symbol": symbol, "price": 50000}


@server.tool(meta={"ui": {"resourceUri": VIEW, "visibility": ["app"]}}, structured_output=True)
def refresh_price(symbol: str) -> Price:
    """Refresh the price (for the view only)."""
    return {"symbol": symbol, "price": 50100}


@server.tool(meta={"ui": {"visibility": ["model"]}})
def model_only(text: str) -> str:
    """Only the model may call this."""
    return text


@server.tool(meta={"ui/resourceUri": "ui://prices/old"})
def old_style(symbol: str) -> str:
    """Declares its view with the deprecated flat key."""
    return symbol


@server.resource(VIEW, name="prices_view", mime_type="text/html;profile=mcp-app", meta={"ui": {
    "csp": {"connectDomains": ["https://api.example.com", "http://127.0.0.1:8740", "https://localhost"],
            "resourceDomains": ["https://cdn.example.com", "javascript:alert(1)"]}, "prefersBorder": True}})
def prices_view() -> str:
    return PAGE


@server.resource("ui://prices/old", name="old_view", mime_type="text/html;profile=mcp-app")
def old_view() -> str:
    return "<!doctype html><p>old</p>"


@server.resource("ui://prices/undeclared", name="undeclared", mime_type="text/html;profile=mcp-app")
def undeclared() -> str:
    return "<!doctype html><p>no tool declares me</p>"


@server.resource("note://readme", name="readme", mime_type="text/plain")
def readme() -> str:
    return json.dumps({"hello": "world"})


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run("stdio")
