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


class DemoProvider(Provider):
    def default_capabilities(self):
        return Capabilities(native_tools=True, adapters=False)

    async def list_models(self):
        return ["scripted-test-model"]

    async def stream(self, request):
        system = request.messages[0].content if request.messages else ""
        last = request.messages[-1]
        if request.json_schema is not None:
            plan = {"subtasks": [
                {"id": "t1", "specialist": "marketing", "instruction": "Design the launch campaign for the ETF", "depends_on": []},
                {"id": "t2", "specialist": "finance", "instruction": "Estimate the expected ROI of the campaign", "depends_on": ["t1"]},
            ]}
            yield StreamEvent(kind="text", text=json.dumps(plan))
            yield StreamEvent(kind="done")
            return
        if last.role == "user" and "archivo" in last.content.lower() and request.tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c1", name="write_file",
                              arguments={"path": "notas.md", "content": "# Notas\n"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        tools = {t.name for t in request.tools or []}
        if last.role == "user" and "word" in last.content.lower() and "create_docx" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c2", name="create_docx", arguments={
                "path": "informes/informe.docx", "content": "# Informe\n\n- Ventas: **+12 %**\n"}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "user" and "factura" in last.content.lower() and "ask_user" in tools:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall(id="c3", name="ask_user", arguments={
                "question": "¿Para qué país es la factura?", "options": ["España", "Francia"]}))
            yield StreamEvent(kind="done", finish_reason="tool_calls")
            return
        if last.role == "tool" and last.name == "ask_user":
            answer = f"Entendido ({last.content}). Para España, el IVA general es del **21 %**."
        elif last.role == "user" and "página" in last.content.lower():
            answer = "Aquí tienes la página:\n\n```html\n" + PROBE_PAGE + "\n```"
        elif last.role == "user" and "# Project instructions" in system:
            answer = "Respuesta del proyecto: sigo sus instrucciones y uso sus archivos."
        elif last.role == "tool":
            answer = f"He creado el archivo. Resultado de la herramienta: `{last.content}`"
        elif "Spike Finance" in system.split("\n")[0]:
            answer = ("**ROI estimado:** con un presupuesto de 50.000 € y 1.200 nuevos inversores con un ticket medio "
                      "de 2.000 €, el ROI bruto sería del **12 %** (cálculo: `(56.000 - 50.000) / 50.000`).")
        elif "Spike Marketing" in system.split("\n")[0]:
            answer = "1. Público: inversores minoristas de 25-40 años.\n2. Canales: newsletter, YouTube y SEO.\n3. Mensaje: *diversificación sencilla y barata*."
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
    state = AppState(home=home, provider_factory=lambda cfg: DemoProvider(cfg))
    model = home / "models" / "scripted.gguf"  # only checked for existence: the tuner below is scripted too
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"GGUF")
    state.update_settings({"local_runtime": {**state.settings()["local_runtime"], "model": str(model)}})
    app = create_app(state, allowed_hosts={"127.0.0.1", "localhost"})  # as `spike serve` runs it
    app.state.tuner = scripted_tuner
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8741")), log_level="warning")


if __name__ == "__main__":
    main()
