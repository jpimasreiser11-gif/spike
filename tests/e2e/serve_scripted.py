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
        if last.role == "tool":
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


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="spike-e2e-"))
    os.environ["SPIKE_HOME"] = str(home)
    os.environ["SPIKE_WORKSPACE"] = str(home / "ws")
    os.environ["SPIKE_NO_KEYRING"] = "1"
    state = AppState(home=home, provider_factory=lambda cfg: DemoProvider(cfg))
    uvicorn.run(create_app(state), host="127.0.0.1", port=int(os.environ.get("PORT", "8741")), log_level="warning")


if __name__ == "__main__":
    main()
