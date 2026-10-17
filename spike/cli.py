"""`spike` command line: serve the app, check the machine, manage models, chat and benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
    if args.host in ("0.0.0.0", "::", ""):
        allowed = None  # reachable by any name; /v1 still needs SPIKE_API_TOKEN from other machines
        print("warning: SPIKE is reachable from your network and the app has no login", file=sys.stderr)
    else:
        allowed = {"127.0.0.1", "localhost", "::1", args.host}
    app = create_app(state, allowed_hosts=allowed)
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

    if args.action == "history":
        return show_history(args.model)
    args.model = args.model or "qwen3.5-4b"
    if args.action == "list":
        for m in MODELS.values():
            print(f"{m.id:20} {m.repo:32} quants={','.join(m.quants)} license={m.license}  {m.notes}")
        print("\nDownloaded:")
        for p in local_models():
            print(f"  {p}  {p.stat().st_size / 1024**3:.2f} GB")
        return 0

    def progress(done: int, total: int) -> None:
        pct = done / total * 100 if total else 0
        print(f"\r  {done / 1024**3:.2f}/{total / 1024**3:.2f} GB ({pct:.0f}%)", end="", flush=True)

    import httpx

    try:
        path = asyncio.run(download(args.model, args.quant, progress=progress))
    except httpx.HTTPError as exc:
        print(f"\nerror: could not download {args.model} from the Hugging Face Hub: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, PermissionError, ValueError) as exc:  # missing file, license refused, bad checksum
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    print(f"\nsaved {path} (sha256 verified)")
    from spike.server.state import AppState

    state = AppState()
    runtime = state.settings()["local_runtime"]
    if not runtime.get("model"):
        runtime["model"] = str(path)
        state.update_settings({"local_runtime": runtime})
        print("set as the local SPIKE model")
    return 0


def _when(ts: float) -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def show_history(component: str | None) -> int:
    """Every version of what Evolution changed (router keywords, specialist adapters), newest first."""
    from spike.evolution.store import EvolutionStore
    from spike.runtime.paths import spike_home

    versions = EvolutionStore(spike_home() / "evolution.db").versions(component)
    if not versions:
        print("No versions yet: SPIKE uses its built-in router and the adapters you installed by hand.")
        return 0
    for v in versions:
        print(f"{'*' if v['active'] else ' '} {v['component']:<20} v{v['id']:<4} {_when(v['created'])}  {v['reason']}")
    print("\n* = in use. Go back with: spike evolve rollback <component>")
    return 0


def cmd_evolve(args: argparse.Namespace) -> int:
    from spike.server.state import AppState

    async def run() -> int:
        state = AppState()
        try:
            if args.action == "check":
                from spike.evolution.checks import run_checks

                report = await run_checks(state, replay=args.replay)
                if args.json:
                    print(json.dumps(report, indent=2, ensure_ascii=False))
                for c in [] if args.json else report["checks"]:
                    print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['name']:<9} {c['detail']}")
                    for r in c.get("results") or []:
                        print(f"       {'pass' if r['passed'] else 'fail'} {r['question'][:70]}"
                              + (f"  ({'; '.join(r['problems'])})" if r["problems"] else "")
                              + ("" if r["checked"] else "  [no text checks: only that it answers without error]"))
                return 0 if report["ok"] else 1
            if args.action == "router":
                report = state.learn_router()
                b, a = report["before"], report["after"]
                print(f"Learned from {report['learned_from']} route corrections, {report['keywords']} keywords.")
                for split in ("corrections", "dev", "test"):
                    if b[split]["n"]:
                        print(f"  {split:<11} n={b[split]['n']:<3} first choice {b[split]['primary']:.2f} -> "
                              f"{a[split]['primary']:.2f}, exact {b[split]['exact']:.2f} -> {a[split]['exact']:.2f}")
                print("Accepted: now in use." if report["accepted"] else "Not used: " + "; ".join(report["reasons"]))
                return 0 if report["accepted"] else 1
            if args.action == "rollback":
                if not args.component:
                    print("error: name what to roll back: router or adapter:<specialist>", file=sys.stderr)
                    return 2
                previous = state.rollback(args.component)
                print(f"{args.component}: " + (f"back to v{previous['id']} ({previous['reason']})" if previous
                                               else "back to the built-in version"))
                if args.component.startswith("adapter:"):
                    print("Restart the local engine (or the SPIKE app) to load it.")
                return 0
            out = state.evolution.export()
            if args.component and args.component != "-":
                Path(args.component).write_text(out, encoding="utf-8")
                print(f"wrote {out.count(chr(10))} accepted eval candidates to {args.component}")
            else:
                print(out, end="")
            return 0
        except (LookupError, ValueError, FileNotFoundError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            await state.close()

    return asyncio.run(run())


def cmd_forge(args: argparse.Namespace) -> int:
    """Run the Forge test tasks and report each mode's success rate (`spike forge eval`)."""
    from spike.forge import evaluate
    from spike.server.state import AppState

    tasks = evaluate.load_tasks(Path(args.tasks) if args.tasks else evaluate.TASKS)
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
    modes = ["forge", "baseline"] if args.baseline else ["forge"]

    async def run() -> int:
        state = AppState()
        try:
            if args.start_local:
                await state.start_runtime()
            for pid in state.providers_for_run(args.provider):
                await state.refresh_adapters(pid)
            base = state.orchestrator(args.provider)
            core = base.resolve(base.catalog.core)
            meta = {"provider": core.provider.config.name, "model": core.model or core.provider.config.model,
                    "local": core.provider.config.local, "tasks": len(tasks)}

            def progress(r: dict) -> None:
                print(f"{'pass' if r['passed'] else 'FAIL'} {r['mode']:<8} {r['id']:<10} {r['elapsed_s']:>6.1f}s"
                      + "".join(f"\n       {f['check']}: {f['why']}" for f in r["failed"])
                      + (f"\n       error: {r['error']}" if r["error"] else ""), file=sys.stderr)

            report = await evaluate.evaluate(base, tasks, modes, meta, progress)
        finally:
            await state.close()
        for mode, s in report["summary"].items():
            print(f"{mode:<8} {s['passed']}/{s['n']} = {s['rate']:.0%}  (95 % CI {s['ci95'][0]:.0%}–{s['ci95'][1]:.0%})")
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {args.out}")
        return 0

    return asyncio.run(run())


def cmd_adapters(args: argparse.Namespace) -> int:
    from spike.evolution import adapters
    from spike.server.state import AppState

    state = AppState()
    try:
        spec = state.catalog.get(args.specialist)
        result = adapters.install(state.evolution.store, state.adapters_path(), spec, Path(args.gguf),
                                  Path(args.eval), Path(args.config) if args.config else None, args.variant)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    v = result["version"]
    if result.get("unchanged"):
        print(f"{spec.id}: this adapter is already in use (v{v['id']}).")
        return 0
    for reason in v["report"]["reasons"]:
        print(f"  {reason}")
    print(f"Installed {result['path']} as {v['component']} v{v['id']}. Restart the local engine (or the SPIKE app) "
          f"to load it. Go back with: spike evolve rollback {v['component']}")
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


def cmd_tune(args: argparse.Namespace) -> int:
    from spike.server.state import AppState

    async def run() -> int:
        state = AppState()
        if args.model:
            state.update_settings({"local_runtime": {**state.settings()["local_runtime"], "model": args.model}})
        try:
            async for ev in state.run_tune(quick=args.quick):
                if ev["type"] == "tune_start":
                    print(f"Measuring threads {ev['threads']} (prompt {ev['prompt']} tokens, {ev['gen']} generated)...")
                elif ev["type"] == "tune_result":
                    print(f"  threads {ev['threads']:>2}  KV {ev['kv_cache_type']:<5} generation {ev['gen_tok_s']:>7} tok/s"
                          f"  prompt {ev['prompt_tok_s']:>8} tok/s  peak RSS {ev['peak_rss_mb']} MB")
                elif ev["type"] == "tune_done":
                    b, c = ev["best"], ev["report"]["context"]
                    print(f"Saved: threads {b['threads']}, KV {b['kv_cache_type']}, context {b['context']} "
                          f"(context estimated: {c['estimated_gb']} GB of a {c['budget_gb']} GB budget, not measured)")
        except (ValueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            await state.close()
        return 0

    return asyncio.run(run())


def cmd_mcp(args: argparse.Namespace) -> int:
    from spike.server.mcp_server import serve_stdio
    from spike.server.state import AppState

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)  # stdout carries the protocol
    asyncio.run(serve_stdio(AppState(), start_local=args.start_local))
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
    m.add_argument("action", choices=["list", "pull", "history"])
    m.add_argument("model", nargs="?", help="model to pull (default qwen3.5-4b); for history, a component")
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

    t = sub.add_parser("tune", help="measure threads and KV cache on this machine and save the fastest settings")
    t.add_argument("--model", help="GGUF to tune for (default: the local model in Settings)")
    t.add_argument("--quick", action="store_true", help="shorter runs (less precise)")
    t.set_defaults(func=cmd_tune)

    ev = sub.add_parser("evolve", help="check, learn or roll back what SPIKE learned from its use")
    ev.add_argument("action", choices=["check", "router", "rollback", "export"])
    ev.add_argument("component", nargs="?", help="rollback: router or adapter:<specialist>; export: output file")
    ev.add_argument("--replay", action="store_true", help="check: answer the accepted eval candidates again")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=cmd_evolve)

    fg = sub.add_parser("forge", help="run the Forge test tasks and measure their success rate")
    fg.add_argument("action", choices=["eval"])
    fg.add_argument("--provider", help="provider for every role (default: the app's bindings)")
    fg.add_argument("--baseline", action="store_true", help="also run each task with the core model alone")
    fg.add_argument("--only", help="comma-separated task ids")
    fg.add_argument("--tasks", help="another tasks file (JSONL)")
    fg.add_argument("--start-local", action="store_true", help="start the local engine first")
    fg.add_argument("--out", help="write the JSON report here")
    fg.set_defaults(func=cmd_forge)

    ad = sub.add_parser("adapters", help="install a trained adapter if its eval results pass acceptance")
    ad.add_argument("action", choices=["install"])
    ad.add_argument("gguf", help="the LoRA adapter GGUF")
    ad.add_argument("--specialist", required=True)
    ad.add_argument("--eval", required=True, help="eval run directory (or its summary.json) from evals/run_eval.py")
    ad.add_argument("--config", help="training config whose acceptance rule to apply (training/configs/<id>.yaml)")
    ad.add_argument("--variant", help="the adapter's variant name in the eval run, when it has several")
    ad.set_defaults(func=cmd_adapters)

    mc = sub.add_parser("mcp", help="serve SPIKE's specialists as MCP tools over stdio (Claude Code, Cursor, Codex)")
    mc.add_argument("--start-local", action="store_true",
                    help="start the local engine in this process (when the SPIKE app is not running)")
    mc.set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
