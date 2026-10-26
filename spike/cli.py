"""`spike` command line: serve the app, check the machine, manage models, chat and benchmark."""

from __future__ import annotations

import argparse
import asyncio
import codecs
import json
import logging
import os
import signal
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
    binary = find_binary()
    report: dict = {"spike": __version__, "hardware": hw.to_dict(), "recommendation": asdict(rec),
                    "llama_server": str(binary or "not found"), "models": []}
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
    if args.strict:  # for scripts and installers: exit 1 when SPIKE cannot answer locally yet
        missing = []
        if not binary:
            missing.append("llama-server was not found (install llama.cpp or set SPIKE_LLAMA_SERVER)")
        if not report["models"] and not args.no_model_check:
            missing.append("no local model (run: spike models pull)")
        for line in missing:
            print(f"error: {line}", file=sys.stderr)
        return 1 if missing else 0
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
        path, verified = asyncio.run(download(args.model, args.quant, progress=progress))
    except httpx.HTTPError as exc:
        print(f"\nerror: could not download {args.model} from the Hugging Face Hub: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, PermissionError, ValueError) as exc:  # missing file, license refused, bad checksum
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    print(f"\nsaved {path} " + ("(sha256 verified)" if verified else "(the Hub gave no SHA-256 to check)"))
    from spike.server.state import AppState

    state = AppState()
    runtime = dict(state.settings()["local_runtime"])  # a copy: unset settings hand out the shared defaults
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
                from spike.evolution import prompts
                from spike.evolution.checks import run_checks

                report = await run_checks(state, replay=args.replay, prompt_versions=args.prompts)
                if args.json:
                    print(json.dumps(report, indent=2, ensure_ascii=False))
                for c in [] if args.json else report["checks"]:
                    print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['name']:<9} {c['detail']}")
                    for r in (c.get("results") or []) if c["name"] == "prompts" else []:
                        print(f"       {'ok  ' if r['ok'] else 'fail'} {r['specialist']} {r['what']} v{r['version']}: "
                              f"{prompts.verdict_text(r)}")
                    for r in [] if c["name"] == "prompts" else c.get("results") or []:
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
            if args.action == "optimize":
                if not args.component:
                    print("error: name the specialist to optimise, e.g. spike evolve optimize medicine", file=sys.stderr)
                    return 2

                async def show(ev: dict) -> None:
                    print(f"  [{ev['calls']} answers] trying {ev['label']}", flush=True)

                report = await state.optimize_prompt(args.component, args.try_line, args.max_calls, show)
                if args.json:
                    print(json.dumps(report, indent=2, ensure_ascii=False))
                elif "baseline" in report:
                    b = report["baseline"]
                    print(f"In use: {b['passed']}/{b['total']} of your eval questions pass.")
                    if report.get("confirmed"):
                        c = report["confirmed"]
                        print(f"Best: {c['passed']}/{c['total']} on its second run, with: {'; '.join(report['changes'])}")
                print("Accepted: now in use." if report["accepted"] else "Nothing changed: " + "; ".join(report["reasons"]))
                return 0 if report["accepted"] else 1
            if args.action == "strategy":
                return evolve_strategy(state, args)
            if args.action == "candidate":
                if not args.component:
                    print("error: name the specialist, e.g. spike evolve candidate medicine --try \"Cita la guía\"",
                          file=sys.stderr)
                    return 2
                modes = dict(pair.split("=", 1) for pair in args.skill if "=" in pair)
                version = state.propose_prompt(args.component, args.try_line, modes)
                print(f"Candidate prompt v{version['id']} for {args.component}: {version['reason']}\n"
                      f"It changes nothing yet. Compare it with `spike evolve check --prompts`; use it with "
                      f"`spike evolve activate {args.component}`, which refuses it if it scores lower on your eval "
                      f"questions than the version in use.")
                return 0
            if args.action == "activate":
                if not args.component:
                    print("error: name the specialist, e.g. spike evolve activate medicine", file=sys.stderr)
                    return 2
                from spike.evolution import prompts

                report = await state.activate_prompt(args.component, args.version)
                print(f"v{report['version']}: {prompts.verdict_text(report)}")
                if report["activated"]:
                    print(f"Activated: now in use. Go back with: spike evolve rollback prompt:{args.component}")
                else:
                    print("Blocked, nothing changed: " + (report.get("reason") or "it scores more than "
                          f"{prompts.TOLERANCE_POINTS:g} points below the version in use"))
                return 0 if report["activated"] else 1
            if args.action == "personal-adapter":
                return evolve_personal(state, args)
            if args.action == "dataset":
                from spike.evolution import dataset

                made = state.build_examples()
                approved = list(reversed(state.evolution.store.items("example", "approved")))
                out = Path(args.component or ".")
                out.mkdir(parents=True, exist_ok=True)
                (out / "spike-training.jsonl").write_text(dataset.export_chats(approved), encoding="utf-8")
                (out / "spike-preferences.jsonl").write_text(dataset.export_pairs(approved), encoding="utf-8")
                waiting = len(state.evolution.store.items("example", "proposed"))
                print(f"{made['proposed']} new examples to review, {made['skipped']} not usable; {waiting} waiting for "
                      f"your review in Settings → Evolution. Wrote {len(approved)} approved examples to "
                      f"{out / 'spike-training.jsonl'} and {out / 'spike-preferences.jsonl'}.")
                return 0
            if args.action == "rollback":
                if not args.component:
                    print("error: name what to roll back: router, adapter:<specialist> or prompt:<specialist>",
                          file=sys.stderr)
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
        except (LookupError, ValueError, FileNotFoundError, PermissionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            await state.close()

    return asyncio.run(run())


def evolve_strategy(state, args: argparse.Namespace) -> int:
    """`spike evolve strategy`: the tool and skill counts per task type, and the tie-break learned from them."""
    from spike.evolution import strategy

    if args.reset:
        print(f"Forgot {state.reset_strategy()} recorded uses; skill ties go back to the router's own order.")
        return 0
    report = state.learn_strategy()
    rows = state.evolution.strategy_overview()["rows"]
    if args.json:
        print(json.dumps({"rows": rows, "report": report}, indent=2, ensure_ascii=False))
        return 0
    print(f"{'kind':<6} {'name':<28} {'task type':<22} {'worked':>8}  rate")
    for r in rows:
        print(f"{r['kind']:<6} {r['name']:<28} {r['task_type']:<22} {r['good']:>3}/{r['n']:<4}  {r['rate']:.0%}"
              + ("" if r["enough"] else f"  (needs {strategy.MIN_SAMPLES} uses to count)"))
    if not rows:
        print("Nothing recorded yet: tools and skills are counted as you use SPIKE.")
    print("Used only to break ties between skills that score the same, once every one has "
          f"{strategy.MIN_SAMPLES} recorded uses for the task type, and only if `spike evolve check` passes with it.")
    if report["accepted"]:
        print(f"Tie-break in use (v{report['version']}), from {report['uses']} recorded uses.")
    else:
        print("Not in use: " + "; ".join(report["reasons"]))
    return 0


def evolve_personal(state, args: argparse.Namespace) -> int:
    """`spike evolve personal-adapter`: choose what goes into a personal adapter, then train it (Apple silicon)."""
    from spike.evolution import personal

    evo = state.evolution.store
    if args.enable or args.disable:
        state.update_settings({"evolution": {**state.evolution_settings(), "personal_adapter": bool(args.enable)}})
        print("Personal adapter " + ("on: nothing is used until you mark chats or approve corrections, and nothing "
                                     "is trained until you run this command and confirm." if args.enable else "off."))
        return 0
    enabled = bool(state.evolution_settings()["personal_adapter"])
    if not enabled:
        print("The personal adapter is off. Turn it on in Settings > Evolución or with "
              "`spike evolve personal-adapter --enable`; nothing was done.", file=sys.stderr)
        return 1
    for cid in args.mark:
        personal.mark_chat(evo, state.store, cid)
    overview = personal.build_set(evo, state.store, bool(state.evolution_settings()["training_data"]))
    known = {e["id"] for e in overview["entries"]}
    for ref in [*args.exclude, *args.include]:
        if ref not in known:
            print(f"error: '{ref}' is not an example in the personal set (see --list)", file=sys.stderr)
            return 2
        personal.set_excluded(evo, ref, ref in args.exclude)
    for cid in args.unmark:
        personal.unmark_chat(evo, cid)
    if args.exclude or args.include or args.mark or args.unmark:
        overview = personal.build_set(evo, state.store, bool(state.evolution_settings()["training_data"]))
    print("\n".join(personal.summary(overview)))
    if args.list:
        for e in overview["entries"]:
            flag = "excluded" if e["excluded"] else "repeated" if e["duplicate"] else "used"
            print(f"  {e['id']:<44} {e['source']:<10} {flag:<9} {e['question'][:60]!r}")
        return 0
    here = personal.availability()
    if not here["available"]:
        print("error: " + here["reason"], file=sys.stderr)
        return 1
    if overview["counts"]["used"] < personal.MIN_EXAMPLES:
        print(f"error: at least {personal.MIN_EXAMPLES} examples are needed to train.", file=sys.stderr)
        return 1
    question = (f"Train a personal adapter on these {overview['counts']['used']} examples? "
                "It takes hours and stays on this computer. [y/N] ")
    if not args.yes and (not sys.stdin.isatty() or input(question).strip().lower() != "y"):
        print("Not started. Run again with --yes to train without this question.", file=sys.stderr)
        return 1
    llama_cpp = args.llama_cpp or os.environ.get("SPIKE_LLAMA_CPP") or ""
    model = args.model or state.settings()["local_runtime"].get("model") or ""
    if not llama_cpp or not model:
        print("error: pass --llama-cpp (the llama.cpp checkout) and --model (the base GGUF, or set it in Settings).",
              file=sys.stderr)
        return 2
    result = personal.run(personal.Job(
        evo, state.store, state.evolution_settings(), state.adapters_path(), state.home / "personal",
        Path(llama_cpp).expanduser(), Path(model).expanduser(), runner=personal.run_command, log=print))
    print(result["message"])
    return {"accepted": 0, "rejected": 2}.get(result["status"], 1)


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
        if args.provider and not state.provider_config(args.provider):
            print(f"error: unknown provider '{args.provider}' (see Settings → Providers)", file=sys.stderr)
            return 2
        if args.model:
            state.update_settings({"local_runtime": {**state.settings()["local_runtime"], "model": args.model}})
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

            report = await evaluate.evaluate(base, tasks, modes, meta, progress,
                                             Path(args.keep).expanduser() if args.keep else None)
        finally:
            if args.start_local:
                await state.stop_runtime()
            await state.close()
        for mode, s in report["summary"].items():
            print(f"{mode:<8} {s['passed']}/{s['n']} = {s['rate']:.0%}  (95 % CI {s['ci95'][0]:.0%}–{s['ci95'][1]:.0%})")
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {args.out}")
        return 0

    return asyncio.run(run())


def cmd_dev(args: argparse.Namespace) -> int:
    """`spike dev [folder]`: SPIKE's agent codes in a folder from the terminal, asking before edits and commands."""
    from spike.dev import terminal
    from spike.dev.session import DevSession
    from spike.dev.tools import stop_commands
    from spike.server.state import AppState

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a folder", file=sys.stderr)
        return 2
    state = AppState()
    if args.provider and not state.provider_config(args.provider):
        print(f"error: unknown provider '{args.provider}' (see Settings → Providers)", file=sys.stderr)
        return 2
    if args.specialist != "auto" and args.specialist not in state.catalog.specialists:
        print(f"error: unknown specialist '{args.specialist}'; one of: auto, {', '.join(state.catalog.specialists)}",
              file=sys.stderr)
        return 2
    loop = asyncio.new_event_loop()  # one loop for the session; Ctrl-C stops a request, not the session

    def leave(signum, frame):  # closing the terminal or `kill`: still stop running commands and the engine
        raise SystemExit(128 + signum)

    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), leave)
    try:
        if args.start_local:
            loop.run_until_complete(state.start_runtime())
        for pid in state.providers_for_run(args.provider):
            loop.run_until_complete(state.refresh_adapters(pid))
        session = DevSession(state, root, provider_id=args.provider, specialist=args.specialist,
                             accept_edits=args.accept_edits, resume=args.resume)
        return terminal.main(session, loop, args.prompt)
    finally:
        stop_commands()
        if args.start_local:
            loop.run_until_complete(state.stop_runtime())
        loop.run_until_complete(state.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def cmd_adapters(args: argparse.Namespace) -> int:
    from spike.evolution import adapters
    from spike.evolution.checks import answer_with_spike
    from spike.evolution.prompts import eval_set
    from spike.server.state import AppState

    async def run() -> tuple[str, dict]:
        state = AppState()
        try:
            spec = state.catalog.get(args.specialist)
            questions = [] if args.skip_local_eval else eval_set(state.evolution.store, spec.id)

            async def reload() -> None:  # llama-server loads the adapters in place when it starts
                try:
                    await state.start_runtime()
                except (OSError, RuntimeError, ValueError) as exc:
                    raise RuntimeError(f"could not start the local engine for your eval ({exc}); close the SPIKE app "
                                       "first, since its engine keeps the old adapter loaded, or pass "
                                       "--skip-local-eval") from exc
                state.installed_adapters.clear()

            if questions:
                await reload()
            result = await adapters.install_checked(
                state.evolution.store, state.adapters_path(), spec, Path(args.gguf), Path(args.eval), questions,
                lambda q: answer_with_spike(state, {**q, "specialist": spec.id}), reload,
                Path(args.config) if args.config else None, args.variant)
            return spec.id, result
        finally:
            await state.stop_runtime()
            await state.close()

    try:
        sid, result = asyncio.run(run())
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    v = result["version"]
    if result.get("unchanged"):
        print(f"{sid}: this adapter is already in use (v{v['id']}).")
        return 0
    for reason in v["report"]["reasons"]:
        print(f"  {reason}")
    local = result.get("local_eval")
    if local:
        print(f"  your eval for {sid}: {local['before']}/{local['questions']} before, {local['after']}/"
              f"{local['questions']} with the new adapter" + (f"; lost: {', '.join(local['lost'])}" if local["lost"] else ""))
    if result.get("rolled_back"):
        print(f"Not kept: the new adapter does worse on your own eval for {sid}, so the previous one is back.")
        return 1
    if local is None:
        print("  no accepted eval questions with checks for this specialist: only the training eval was checked")
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


def cmd_render(args: argparse.Namespace) -> int:
    from spike.motion.render import MotionError, render, scene_html

    if args.install_browser:  # Playwright's own Chromium, downloaded by Playwright into its cache
        import subprocess

        return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
    if not args.scene:
        print("error: give the scene file", file=sys.stderr)
        return 2
    scene = Path(args.scene)
    out = Path(args.output) if args.output else scene.with_suffix(".mp4")
    try:
        if scene.suffix.lower() not in (".html", ".htm", ".svg") or not scene.is_file():
            raise MotionError(f"{scene} is not an .html or .svg scene file")
        html = scene_html(scene.read_text(encoding="utf-8", errors="replace"), scene.suffix.lower())
        done = asyncio.run(render(html, out, size=args.size, fps=args.fps, seconds=args.seconds))
    except MotionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{out}: {done.width}x{done.height}, {done.fps} fps, {done.seconds:g} s, {done.frames} frames, "
          f"{done.codec}, {done.bytes // 1024} KB")
    for line in [*done.notes, *(f"JavaScript error: {e}" for e in done.errors),
                 *(f"blocked: {u}" for u in done.blocked)]:
        print(f"  {line}", file=sys.stderr)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from spike.connectors.validation import CATALOG, validate_connectors
    from spike.skills.validation import validate_skills

    issues = (validate_skills([Path(p) for p in args.paths]) if args.command == "skills" else
              validate_connectors(Path(args.paths) if args.paths else CATALOG))
    if issues:
        heading = "Validación fallida" if args.lang == "es" else "Validation failed"
        print(f"{heading} ({len(issues)})", file=sys.stderr)
        for issue in issues:
            print(issue.message(args.lang), file=sys.stderr)
        return 1
    print("Validación correcta" if args.lang == "es" else "Validation passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spike", description="SPIKE local AI system")
    p.add_argument("--version", action="version", version=f"spike {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    for kind in ("skills", "connectors"):
        validator = sub.add_parser(kind, help=f"validate {kind} / validar {kind}")
        actions = validator.add_subparsers(dest="action", required=True)
        validate = actions.add_parser("validate", help="offline checks / comprobaciones sin red")
        validate.add_argument("paths", nargs="*" if kind == "skills" else "?", default=[])
        validate.add_argument("--lang", choices=("es", "en"), default="en", help="language / idioma")
        validate.set_defaults(func=cmd_validate)

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
    d.add_argument("--strict", action="store_true", help="exit 1 when llama-server or a local model is missing")
    d.add_argument("--no-model-check", action="store_true", help="with --strict: do not require a local model")
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
    b.add_argument("--server-context", type=int, default=0,
                   help="llama-server context for every length (default: longest prompt + gen + 256)")
    b.add_argument("--port", type=int, default=8799)
    b.add_argument("--out", help="write the JSON report here")
    b.set_defaults(func=cmd_bench)

    t = sub.add_parser("tune", help="measure threads and KV cache on this machine and save the fastest settings")
    t.add_argument("--model", help="GGUF to tune for (default: the local model in Settings)")
    t.add_argument("--quick", action="store_true", help="shorter runs (less precise)")
    t.set_defaults(func=cmd_tune)

    ev = sub.add_parser("evolve", help="check, learn, optimise or roll back what SPIKE learned from its use")
    ev.add_argument("action", choices=["check", "router", "strategy", "optimize", "candidate", "activate", "dataset",
                                       "personal-adapter", "rollback", "export"])
    ev.add_argument("component", nargs="?", help="optimize, candidate, activate: a specialist; dataset: output "
                                                 "folder; rollback: router, strategy, adapter:<specialist>, "
                                                 "adapter:personal or prompt:<specialist>; export: output file")
    ev.add_argument("--try", dest="try_line", action="append", default=[],
                    help="optimize: an instruction line to try, besides the rules saved from corrections; candidate: "
                         "a line to add")
    ev.add_argument("--skill", action="append", default=[], metavar="NAME=MODE",
                    help="candidate: set a skill to always, off or auto")
    ev.add_argument("--version", type=int, help="activate: the candidate version (default: the newest)")
    ev.add_argument("--max-calls", type=int, help="optimize: at most this many model answers (default 120)")
    ev.add_argument("--replay", action="store_true", help="check: answer the accepted eval candidates again")
    ev.add_argument("--prompts", action="store_true",
                    help="check: compare learned and candidate prompts on your eval questions (runs the model)")
    ev.add_argument("--reset", action="store_true", help="strategy: forget every recorded tool and skill use")
    ev.add_argument("--enable", action="store_true", help="personal-adapter: turn the feature on")
    ev.add_argument("--disable", action="store_true", help="personal-adapter: turn the feature off")
    ev.add_argument("--list", action="store_true", help="personal-adapter: list every example and whether it is used")
    ev.add_argument("--mark", action="append", default=[], metavar="CHAT", help="personal-adapter: use this chat")
    ev.add_argument("--unmark", action="append", default=[], metavar="CHAT", help="personal-adapter: stop using it")
    ev.add_argument("--exclude", action="append", default=[], metavar="ID", help="personal-adapter: leave an example out")
    ev.add_argument("--include", action="append", default=[], metavar="ID", help="personal-adapter: put it back")
    ev.add_argument("--llama-cpp", help="personal-adapter: llama.cpp checkout (default $SPIKE_LLAMA_CPP)")
    ev.add_argument("--model", help="personal-adapter: base GGUF (default: the local model in Settings)")
    ev.add_argument("--yes", action="store_true", help="personal-adapter: train without asking")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=cmd_evolve)

    fg = sub.add_parser("forge", help="run the Forge test tasks and measure their success rate")
    fg.add_argument("action", choices=["eval"])
    fg.add_argument("--provider", help="provider for every role (default: the app's bindings)")
    fg.add_argument("--baseline", action="store_true", help="also run each task with the core model alone")
    fg.add_argument("--only", help="comma-separated task ids")
    fg.add_argument("--tasks", help="another tasks file (JSONL)")
    fg.add_argument("--start-local", action="store_true", help="start the local engine first (and stop it after)")
    fg.add_argument("--model", help="GGUF for the local engine (saved as the local model, as `spike tune` does)")
    fg.add_argument("--out", help="write the JSON report here")
    fg.add_argument("--keep", metavar="DIR",
                    help="keep each task's files here (DIR/<task>-<mode>), with Forge's plan and verdicts")
    fg.set_defaults(func=cmd_forge)

    dv = sub.add_parser("dev", help="code in a folder from the terminal: SPIKE reads, edits and runs commands with "
                                    "your OK, and /undo puts files back")
    dv.add_argument("path", nargs="?", default=".", help="the folder to work in (default: this one)")
    dv.add_argument("--provider", help="provider for every specialist (default: the app's bindings)")
    dv.add_argument("--specialist", default="code", help="who answers: a specialist id, or auto (default: code)")
    dv.add_argument("-p", "--print", dest="prompt", help="run one request without questions and print the answer")
    dv.add_argument("--accept-edits", action="store_true", help="edit and create files without asking (commands "
                                                                 "still ask)")
    dv.add_argument("-c", "--continue", dest="resume", action="store_true",
                    help="continue the latest conversation in this folder")
    dv.add_argument("--start-local", action="store_true", help="start the local engine first (and stop it after)")
    dv.set_defaults(func=cmd_dev)

    ad = sub.add_parser("adapters", help="install a trained adapter if its eval results pass acceptance")
    ad.add_argument("action", choices=["install"])
    ad.add_argument("gguf", help="the LoRA adapter GGUF")
    ad.add_argument("--specialist", required=True)
    ad.add_argument("--eval", required=True,
                    help="eval run directory (or its summary.json) from evals/run_eval.py, or evals/pairwise.py")
    ad.add_argument("--config", help="training config whose acceptance rule to apply (training/configs/<id>.yaml)")
    ad.add_argument("--variant", help="the adapter's variant name in the eval run, when it has several")
    ad.add_argument("--skip-local-eval", action="store_true",
                    help="do not check the adapter against your accepted eval questions (Settings → Evolution)")
    ad.set_defaults(func=cmd_adapters)

    mc = sub.add_parser("mcp", help="serve SPIKE's specialists as MCP tools over stdio (Claude Code, Cursor, Codex)")
    mc.add_argument("--start-local", action="store_true",
                    help="start the local engine in this process (when the SPIKE app is not running)")
    mc.set_defaults(func=cmd_mcp)

    rd = sub.add_parser("render", help="turn an animated HTML/SVG scene into an MP4, WebM or GIF (Spike Motion)")
    rd.add_argument("scene", nargs="?", help="the scene file (.html or .svg)")
    rd.add_argument("-o", "--output", help="video file (.mp4, .webm or .gif); default: the scene's name with .mp4")
    rd.add_argument("--size", default="16:9", help="16:9, 9:16, 1:1, 4:5, 1080p or WIDTHxHEIGHT (default 16:9)")
    rd.add_argument("--fps", type=int, default=30, help="frames per second (default 30)")
    rd.add_argument("--seconds", type=float, help="length; default: the scene's spike-duration or its animations")
    rd.add_argument("--install-browser", action="store_true",
                    help="download Playwright's Chromium to render with (when Chrome is not installed)")
    rd.set_defaults(func=cmd_render)
    return p


def _never_crash_on_output() -> None:
    """Legacy consoles (cp1252 on Windows CI, ASCII under LANG=C) cannot print the arrows and dashes SPIKE uses.

    Keep the stream's encoding, so the console still shows what it can, and print "?" for the rest instead of
    raising UnicodeEncodeError halfway through a command. UTF-8 terminals are left untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        name = getattr(stream, "encoding", None)
        reconfigure = getattr(stream, "reconfigure", None)  # absent on streams a test or a host swapped in
        if not name or reconfigure is None:
            continue
        try:
            if codecs.lookup(name).name != "utf-8":
                reconfigure(errors="replace")
        except (LookupError, ValueError, OSError):  # unknown codec name, or a stream already closed
            continue


def main(argv: list[str] | None = None) -> int:
    _never_crash_on_output()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
