"""`spike` command line: serve the app, check the machine, manage models, chat and benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser
from dataclasses import asdict
from pathlib import Path

from spike import __version__


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from spike.server.app import create_app
    from spike.server.state import AppState

    state = AppState()
    app = create_app(state)
    if args.start_local:
        try:
            asyncio.run(state.start_runtime())
        except Exception as exc:  # the app still starts; the UI shows how to fix it
            print(f"warning: local runtime not started: {exc}", file=sys.stderr)
    url = f"http://{args.host}:{args.port}"
    print(f"SPIKE {__version__} running at {url}")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    if state.runtime:
        asyncio.run(state.stop_runtime())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from spike.runtime.gguf import kv_cache_bytes, read_gguf
    from spike.runtime.hardware import detect, recommend
    from spike.runtime.llamacpp_server import find_binary
    from spike.runtime.models import local_models

    hw = detect()
    rec = recommend(hw)
    report: dict = {"spike": __version__, "hardware": hw.to_dict(), "recommendation": asdict(rec),
                    "llama_server": str(find_binary() or "not found"), "models": []}
    for path in [Path(args.model)] if args.model else local_models():
        info = read_gguf(path)
        ctx = args.context or rec.context
        kv = kv_cache_bytes(info, ctx, rec.kv_cache_type)
        report["models"].append({
            "path": str(path), "arch": info.arch, "file_gb": round(info.file_size / 1024**3, 2),
            "context": ctx, "kv_cache_gb": round(kv / 1024**3, 2),
            "estimated_total_gb": round((info.file_size + kv) / 1024**3 + 0.5, 2),  # + compute buffers/runtime
        })
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"SPIKE {__version__}")
        print(f"  CPU   {hw.cpu_model} ({hw.physical_cores} cores) {' '.join(hw.cpu_flags)}")
        print(f"  RAM   {hw.total_ram_gb} GB total, {hw.available_ram_gb} GB available")
        print(f"  OS    {hw.os} {hw.arch}{'  (Apple Silicon: Metal)' if hw.apple_silicon else ''}")
        print(f"  llama-server: {report['llama_server']}")
        print(f"  Recommended: {rec.quant}, context {rec.context}, KV {rec.kv_cache_type}, threads {rec.threads}")
        for note in rec.notes:
            print(f"  note: {note}")
        for m in report["models"]:
            print(f"  model {Path(m['path']).name}: {m['file_gb']} GB + KV {m['kv_cache_gb']} GB at {m['context']} "
                  f"tokens ≈ {m['estimated_total_gb']} GB (estimate; measure with `spike bench`)")
        if not report["models"]:
            print("  No local models yet. Run: spike models pull")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from spike.runtime.models import MODELS, download, local_models

    if args.action == "list":
        for m in MODELS.values():
            print(f"{m.id:12} {m.repo:28} quants={','.join(m.quants)} license={m.license}  {m.notes}")
        print("\nDownloaded:")
        for p in local_models():
            print(f"  {p}  {p.stat().st_size / 1024**3:.2f} GB")
        return 0

    def progress(done: int, total: int) -> None:
        pct = done / total * 100 if total else 0
        print(f"\r  {done / 1024**3:.2f}/{total / 1024**3:.2f} GB ({pct:.0f}%)", end="", flush=True)

    path = asyncio.run(download(args.model, args.quant, progress=progress))
    print(f"\nsaved {path} (sha256 verified)")
    from spike.server.state import AppState

    state = AppState()
    runtime = state.settings()["local_runtime"]
    if not runtime.get("model"):
        runtime["model"] = str(path)
        state.update_settings({"local_runtime": runtime})
        print("set as the local SPIKE model")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    from spike.server.state import AppState

    async def run() -> int:
        state = AppState()
        for pid in state.providers_for_run(args.provider):
            await state.refresh_adapters(pid)
        orchestrator = state.orchestrator(args.provider)
        code = 0
        async for ev in orchestrator.run([], args.message, state.options(args.mode)):
            t = ev["type"]
            if t == "route" and not args.quiet:
                names = ", ".join(s["name"] + (" (prompt profile)" if s["profile_only"] else "") for s in ev["specialists"])
                print(f"[route: {ev['mode']} → {names}]", file=sys.stderr)
            elif t == "delta" and "subtask" not in ev:
                print(ev["text"], end="", flush=True)
            elif t == "subtask_start" and not args.quiet:
                print(f"[{ev['name']}: {ev['instruction'][:80]}]", file=sys.stderr)
            elif t == "permission_request":
                answer = input(f"\nAllow tool {ev['tool']} {json.dumps(ev['arguments'])[:200]}? [y/N] ").strip().lower()
                state.broker.resolve(ev["id"], "allow_once" if answer == "y" else "deny")
            elif t == "error":
                print(f"\nerror: {ev['message']}", file=sys.stderr)
                code = 1
        print()
        return code

    return asyncio.run(run())


def cmd_bench(args: argparse.Namespace) -> int:
    from spike.bench import run_benchmark

    result = asyncio.run(run_benchmark(args))
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spike", description="SPIKE local AI system")
    p.add_argument("--version", action="version", version=f"spike {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the SPIKE app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8740)
    s.add_argument("--open", action="store_true", help="open the browser")
    s.add_argument("--no-local", dest="start_local", action="store_false", help="do not start llama-server")
    s.set_defaults(func=cmd_serve)

    d = sub.add_parser("doctor", help="check hardware, runtime and model memory needs")
    d.add_argument("--model")
    d.add_argument("--context", type=int)
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    m = sub.add_parser("models", help="list or download models")
    m.add_argument("action", choices=["list", "pull"])
    m.add_argument("model", nargs="?", default="qwen3.5-4b")
    m.add_argument("--quant")
    m.set_defaults(func=cmd_models)

    c = sub.add_parser("chat", help="one-shot chat through the orchestrator")
    c.add_argument("message")
    c.add_argument("--mode", default="auto")
    c.add_argument("--provider")
    c.add_argument("-q", "--quiet", action="store_true")
    c.set_defaults(func=cmd_chat)

    b = sub.add_parser("bench", help="measure TTFT, generation speed and memory of a llama-server model")
    b.add_argument("--model", required=True, help="path to a GGUF file")
    b.add_argument("--adapter", action="append", default=[], help="LoRA GGUF to load (repeatable)")
    b.add_argument("--contexts", default="1024,8192,32768", help="prompt lengths in tokens to test")
    b.add_argument("--gen", type=int, default=128, help="tokens to generate per run")
    b.add_argument("--repeats", type=int, default=3)
    b.add_argument("--threads", type=int)
    b.add_argument("--gpu-layers", type=int, default=0, help="0 = CPU only (the 16 GB target); 99 = Metal")
    b.add_argument("--kv", default="q8_0")
    b.add_argument("--port", type=int, default=8799)
    b.add_argument("--out", help="write the JSON report here")
    b.set_defaults(func=cmd_bench)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
