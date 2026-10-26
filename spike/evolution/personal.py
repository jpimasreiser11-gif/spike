"""A personal adapter (Evolution EV6): a LoRA trained on the user's own approved corrections and marked chats, so the
general assistant answers more the way they asked. Off by default, Apple silicon only, everything on this computer.

What goes in, and nothing else of theirs:
- corrections: the examples they approved one by one (E1/level 3; this needs "Use my corrections to retrain" on);
- chats: the chats they marked for it, one training example per answer that SPIKE's local model wrote, left out when
  it ended in an error, came from an external service or another model (their terms and licenses can forbid training
  on the output), or the next message corrected it;
- anything in either list the user excluded stays out, also as the context of another example. `build_set` counts all
  of it so they see what would be used.
The training mix also holds the public, human-written general chats that every specialist recipe mixes in to avoid
forgetting (training/configs/personal.yaml); that is not their data.

How it is trained: the same pipeline as a specialist (training/prepare.py with --corrections, training/scripts/
train_supervised.sh under the RAM guard, training/export_adapter.py, evals/run_eval.py), with the recipe
training/configs/personal.yaml. The adapter is exported to a staging folder, never to the adapters folder, and is
installed (`adapters.install`, which applies the recipe's acceptance rule to the measured results) only if general
knowledge did not drop by more than 1.5 points, first on general-select and then on the general suite. Without
acceptance nothing is activated. `run` takes the command runner, so tests stub the pipeline; they never train.
It is used by Spike Core, the general assistant (state.py), only while the setting is on."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import yaml

from spike.evolution import adapters
from spike.evolution.dataset import _origin
from spike.evolution.store import EvolutionStore
from spike.memory.learn import correction_rule
from spike.runtime.hardware import HardwareInfo, detect
from spike.specialists.catalog import Specialist

ROOT = Path(__file__).resolve().parents[2]
RECIPE = Path("training") / "configs" / "personal.yaml"
SOURCE = "spike-personal"  # meta.source of the examples; training/prepare.py reads it
STEM = "spike-personal"  # file stem of the adapter, as the specialists' spike-<id>
MIN_EXAMPLES = 30  # fewer would only be memorised; a safety floor of this design, not a measured threshold
MAX_CONTEXT = 6  # messages of the chat before the question that go into an example
MAX_DROP_POINTS = 1.5  # the specialists' limit; the recipe may not loosen it
PERSONAL = Specialist(id="personal", name="Personal adapter", domain="The user's own corrections and chats",
                      description="A LoRA adapter trained on the user's approved corrections and marked chats.",
                      system_prompt="", adapter=STEM)
Runner = Callable[[list[str], dict[str, str]], int]


# ------------------------------------------------------------------ what would be used
def marked(evo: EvolutionStore) -> list[dict[str, Any]]:
    return evo.items("personal", "marked")


def excluded(evo: EvolutionStore) -> set[str]:
    return {i["ref"] for i in evo.items("personal", "excluded")}


def mark_chat(evo: EvolutionStore, store, conversation: str) -> dict[str, Any]:
    """Mark a saved chat for the personal adapter (a temporary chat is never saved, so it cannot be)."""
    chat = store.get_conversation(conversation)
    if chat is None:
        raise LookupError("chat not found")
    existing = evo.find("personal", conversation=conversation)
    if existing and existing["status"] == "marked":
        return existing
    return evo.add("personal", {"conversation": conversation, "title": chat.get("title") or ""}, status="marked")


def unmark_chat(evo: EvolutionStore, conversation: str) -> bool:
    return any(evo.delete(i["id"]) for i in marked(evo) if i["conversation"] == conversation)


def set_excluded(evo: EvolutionStore, ref: str, leave_out: bool) -> None:
    current = next((i for i in evo.items("personal", "excluded") if i["ref"] == ref), None)
    if leave_out and current is None:
        evo.add("personal", {"ref": ref}, status="excluded")
    elif not leave_out and current is not None:
        evo.delete(current["id"])


def _chat_entries(store, conversation: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One example per usable answer of a marked chat, and how many answers were left out for each reason."""
    thread = [m for m in store.messages(conversation) if m["role"] in ("user", "assistant") and m["content"]]
    entries, left = [], {"origin": 0, "corrected": 0}
    for i, answer in enumerate(thread):
        if answer["role"] != "assistant" or i == 0 or thread[i - 1]["role"] != "user":
            continue
        if _origin(answer) is not None:
            left["origin"] += 1
            continue
        if i + 1 < len(thread) and thread[i + 1]["role"] == "user" and correction_rule(thread[i + 1]["content"]):
            left["corrected"] += 1
            continue
        question = thread[i - 1]
        entries.append({"id": f"{conversation}:{answer['id']}", "source": "chat", "conversation": conversation,
                        "question": question["content"], "answer": answer["content"],
                        "context": [{"role": m["role"], "content": m["content"],
                                     "of": f"{conversation}:{m['id']}" if m["role"] == "assistant" else None}
                                    for m in thread[max(0, i - 1 - MAX_CONTEXT):i - 1]]})
    return entries, left


def _messages(entry: dict[str, Any], left_out: set[str]) -> list[dict[str, str]]:
    """The chat an example is trained on: the turns before it (up to MAX_CONTEXT messages) as context, but nothing
    up to and including an answer the user excluded, so an excluded text does not come back as somebody's context."""
    context = entry.get("context") or []
    cut = max((n + 1 for n, m in enumerate(context) if m["of"] in left_out), default=0)
    kept = context[cut:]
    while kept and kept[0]["role"] != "user":  # a window that starts mid-turn starts at the next question instead
        kept = kept[1:]
    return [*({"role": m["role"], "content": m["content"]} for m in kept),
            {"role": "user", "content": entry["question"]}, {"role": "assistant", "content": entry["answer"]}]


def build_set(evo: EvolutionStore, store, training_data: bool) -> dict[str, Any]:
    """Everything that could be used, each entry marked `excluded` or not, with counts for the user to read.
    Approved corrections count only while "Use my corrections to retrain" is on, the same consent as their export."""
    left_out = excluded(evo)
    entries: list[dict[str, Any]] = []
    approved = evo.items("example", "approved")
    for e in reversed(approved if training_data else []):
        entries.append({"id": e["id"], "source": "correction", "conversation": e.get("conversation"),
                        "question": e["question"], "answer": e["chosen"],
                        "messages": [{"role": "user", "content": e["question"]},
                                     {"role": "assistant", "content": e["chosen"]}]})
    chats = {"marked": 0, "missing": 0, "answers_not_used": {"origin": 0, "corrected": 0}}
    for item in reversed(marked(evo)):
        if store.get_conversation(item["conversation"]) is None:
            chats["missing"] += 1  # the chat was deleted
            continue
        chats["marked"] += 1
        found, left = _chat_entries(store, item["conversation"])
        entries += found
        for reason, n in left.items():
            chats["answers_not_used"][reason] += n
    seen: set[str] = set()
    for e in entries:  # the same question and answer from two places is one example
        key = json.dumps([e["question"], e["answer"]], ensure_ascii=False)
        e["duplicate"] = key in seen
        seen.add(key)
        e["excluded"] = e["id"] in left_out
        if e["source"] == "chat":
            e["messages"] = _messages(e, left_out)
    usable = [e for e in entries if not e["excluded"] and not e["duplicate"]]
    return {"entries": entries, "chats": chats,
            "counts": {"approved_corrections": len(approved), "corrections": sum(e["source"] == "correction" for e in entries),
                       "chat_answers": sum(e["source"] == "chat" for e in entries),
                       "excluded": sum(e["excluded"] for e in entries), "duplicates": sum(e["duplicate"] for e in entries),
                       "used": len(usable), "needed": MIN_EXAMPLES, "corrections_need_consent": not training_data},
            "usable": usable}


def export_chats(entries: list[dict[str, Any]]) -> str:
    """The examples to use as chat JSONL, the format training/prepare.py --corrections reads."""
    return "".join(json.dumps({"messages": e["messages"], "meta": {"id": e["id"], "specialist": "personal",
                                                                    "source": SOURCE}}, ensure_ascii=False) + "\n"
                   for e in entries)


def summary(overview: dict[str, Any]) -> list[str]:
    """The counts as lines a person can read (the command line prints them before anything runs)."""
    c, chats = overview["counts"], overview["chats"]
    lines = [f"Approved corrections: {c['corrections']}" + (" (turn on 'Use my corrections to retrain' to include "
                                                           "them)" if c["corrections_need_consent"] else ""),
             f"Marked chats: {chats['marked']} -> {c['chat_answers']} answers by SPIKE's local model"]
    left = chats["answers_not_used"]
    if left["origin"] or left["corrected"]:
        lines.append(f"  not used: {left['origin']} answers from other models or services or with errors, "
                     f"{left['corrected']} that your next message corrected")
    if chats["missing"]:
        lines.append(f"  {chats['missing']} marked chats were deleted")
    lines.append(f"Excluded by you: {c['excluded']}; repeated: {c['duplicates']}")
    lines.append(f"To train on: {c['used']} examples (at least {c['needed']} needed)")
    return lines


# ------------------------------------------------------------------ whether and how it can run
def ram_floor_gb(env: dict[str, str] | None = None) -> float:
    """What the RAM guard waits for before it starts (training/ramguard.py RESUME_FREE_GB)."""
    raw = (os.environ if env is None else env).get("RESUME_FREE_GB")
    return float(raw) if raw else 22.0


def availability(hardware: HardwareInfo | None = None, root: Path = ROOT, has_mlx: bool | None = None,
                 env: dict[str, str] | None = None) -> dict[str, Any]:
    """Can the personal adapter be trained here? `reason` says why not, in words for the user."""
    hw = hardware or detect()
    if not hw.apple_silicon:
        return {"available": False, "reason": f"Not available on this computer ({hw.os} {hw.arch}): the personal adapter "
                "is trained with MLX, which needs a Mac with Apple silicon. Nothing was changed and nothing was sent anywhere."}
    if not (root / "training" / "prepare.py").is_file():
        return {"available": False, "reason": "The training scripts are not here: training the personal adapter needs a "
                "source checkout of SPIKE (the training/ folder), as the specialists' adapters do."}
    if has_mlx is None:
        has_mlx = find_spec("mlx_lm") is not None
    if not has_mlx:
        return {"available": False, "reason": "mlx-lm is not installed in this Python: pip install -r "
                "training/requirements-mac.txt (see docs/TRAINING.md)."}
    floor = ram_floor_gb(env)
    if hw.total_ram_gb < floor:
        return {"available": False, "reason": f"This Mac has {hw.total_ram_gb:g} GB of memory and the RAM guard waits for "
                f"{floor:g} GB to be free before it starts (RESUME_FREE_GB), so training would wait forever."}
    return {"available": True, "reason": ""}


def load_recipe(root: Path = ROOT) -> dict[str, Any]:
    """The recipe, refusing one that loosens the acceptance rule: the personal adapter is accepted on the general
    suite not dropping by more than the specialists' limit, and on nothing weaker."""
    recipe = yaml.safe_load((root / RECIPE).read_text(encoding="utf-8"))
    rule = (recipe.get("acceptance") or {}).get("regression") or {}
    if rule.get("suite") != "general" or not 0 <= rule.get("max_drop_points", 99) <= MAX_DROP_POINTS:
        raise ValueError(f"{RECIPE.as_posix()} must require the general suite to drop by at most {MAX_DROP_POINTS} points")
    return recipe


def in_use(evo: EvolutionStore, settings: dict[str, Any], adapters_dir: Path) -> str | None:
    """The adapter name Spike Core should load: only with the setting on, an accepted version and its file in place."""
    if not settings.get("personal_adapter") or evo.active(adapters.component(PERSONAL)) is None:
        return None
    return STEM if (adapters_dir / f"{STEM}.gguf").is_file() else None


# ------------------------------------------------------------------ the pipeline
def run_command(cmd: list[str], env: dict[str, str]) -> int:
    return subprocess.run(cmd, env={**os.environ, **env}, cwd=ROOT).returncode


@dataclass
class Job:
    evo: EvolutionStore
    store: Any  # the chats
    settings: dict[str, Any]
    adapters_dir: Path
    work: Path  # $SPIKE_HOME/personal: the examples file, staging and the eval runs
    llama_cpp: Path
    model: Path
    root: Path = ROOT
    runner: Runner = run_command
    hardware: HardwareInfo | None = None
    has_mlx: bool | None = None
    log: Callable[[str], None] = print


def _eval_args(recipe: dict[str, Any]) -> list[str]:
    return ["--max-tokens", str(recipe["eval"]["max_tokens"])] if (recipe.get("eval") or {}).get("max_tokens") else []


def _select_rule(acceptance: dict[str, Any]) -> dict[str, Any]:
    """The same rule on the *-select suite (items that never overlap the acceptance sample), as sweep_checkpoints."""
    reg = acceptance["regression"]
    return {"regression": {**reg, "suite": reg["suite"] + "-select"}}


def _finish(result: dict[str, Any], job: Job, status: str, message: str, keep_data: bool = False,
            **extra: Any) -> dict[str, Any]:
    """End a run: drop the files that hold the user's text (the examples, the prepared training data, the trained weights
    and checkpoints) and the staged adapter, whatever the verdict; an accepted adapter was already copied to the adapters
    folder's history. Only a run that stopped while training keeps them, because running the command again resumes."""
    result.update(status=status, message=message, **extra)
    if keep_data:
        return result
    for folder in (job.work / "stage", job.root / "training" / "data" / "personal",
                   job.root / "training" / "runs" / "personal"):
        shutil.rmtree(folder, ignore_errors=True)
    (job.work / "spike-personal.jsonl").unlink(missing_ok=True)
    return result


def run(job: Job) -> dict[str, Any]:
    """Build the set, train, export, evaluate and install the personal adapter only if accepted. Returns {status,
    message, counts, steps, reasons, version}; status is off, unavailable, too_few, failed, rejected or accepted."""
    result: dict[str, Any] = {"status": "failed", "message": "", "steps": [], "reasons": [], "version": None}
    if not job.settings.get("personal_adapter"):
        return {**result, "status": "off", "message": "The personal adapter is off: turn it on in Settings > Evolución "
                "(or `spike evolve personal-adapter --enable`). Nothing was done."}
    here = availability(job.hardware, job.root, job.has_mlx)
    if not here["available"]:
        return {**result, "status": "unavailable", "message": here["reason"]}
    overview = build_set(job.evo, job.store, bool(job.settings.get("training_data")))
    result["counts"] = overview["counts"]
    if overview["counts"]["used"] < MIN_EXAMPLES:
        return {**result, "status": "too_few", "message": f"{overview['counts']['used']} examples to train on; at least "
                f"{MIN_EXAMPLES} are needed. Approve more corrections or mark more chats."}
    try:
        recipe = load_recipe(job.root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return {**result, "status": "failed", "message": str(exc)}
    for what, path in (("llama.cpp checkout", job.llama_cpp / "convert_lora_to_gguf.py"), ("base model", job.model)):
        if not path.is_file():
            return {**result, "status": "failed", "message": f"{what} not found: {path}"}

    py, tr = sys.executable, job.root / "training"
    stage, examples = job.work / "stage", job.work / "spike-personal.jsonl"
    stage.mkdir(parents=True, exist_ok=True)
    examples.parent.mkdir(parents=True, exist_ok=True)
    examples.write_text(export_chats(overview["usable"]), encoding="utf-8")
    recipe_path = job.root / RECIPE
    gguf = stage / f"{STEM}.gguf"
    supervised = os.environ.get("SPIKE_UNSUPERVISED") != "1"  # under the RAM guard unless asked otherwise
    train = ["bash", str(tr / "scripts" / "train_supervised.sh"), "personal"] if supervised else [
        "bash", str(tr / "train.sh"), "personal"]
    eval_cmd = [py, str(job.root / "evals" / "run_eval.py"), "--model", str(job.model), "--adapter", str(gguf),
                *_eval_args(recipe)]
    steps = [
        ("prepare", [py, str(tr / "prepare.py"), str(recipe_path), "--corrections", str(examples)]),
        ("train", train),
        ("export", [py, str(tr / "export_adapter.py"), "personal", "--llama-cpp", str(job.llama_cpp), "--check-model",
                    str(job.model), "--out", str(stage), "--work", str(stage / "work"), "--name", STEM,
                    "--system-from", "core"]),
        ("select", [*eval_cmd, "--suites", "general-select", "--out", str(job.work / "eval-select")]),
    ]
    for name, cmd in steps:
        job.log(f"[{name}] {' '.join(cmd)}")
        code = job.runner(cmd, {})
        result["steps"].append({"name": name, "exit": code})
        if code == 75 and name == "train":
            return _finish(result, job, "failed", "The RAM guard gave up waiting for enough free memory (exit 75). Close "
                           "other apps and run the command again: training resumes from its last checkpoint. The files "
                           "with your text stay in training/data/personal and training/runs/personal until a run "
                           "finishes.", keep_data=True)
        if code != 0:
            return _finish(result, job, "failed", f"{name} failed (exit {code}); see its output above.",
                           keep_data=name == "train")
    # a regression already visible on general-select ends it here: the adapter is not worth the longer general run
    from spike.evolution.acceptance import check_acceptance

    selected, reasons = check_acceptance(adapters.load_results(job.work / "eval-select")[0],
                                         _select_rule(recipe["acceptance"]), STEM)
    result["select"] = {"accepted": selected, "reasons": reasons}
    if not selected:
        return _finish(result, job, "rejected", "Rejected on general-select: " + "; ".join(reasons), reasons=reasons)
    final = [*eval_cmd, "--suites", "general", "--acceptance", str(recipe_path), "--out", str(job.work / "eval-general")]
    job.log(f"[evaluate] {' '.join(final)}")
    code = job.runner(final, {})
    result["steps"].append({"name": "evaluate", "exit": code})
    if code not in (0, 2):  # 2 is run_eval.py's "rejected"; install below applies the rule to the numbers itself
        return _finish(result, job, "failed", f"evaluate failed (exit {code}); see its output above.")
    try:
        installed = adapters.install(job.evo, job.adapters_dir, PERSONAL, gguf, job.work / "eval-general", recipe_path)
    except ValueError as exc:
        text = str(exc).removeprefix("refused: the adapter does not pass its acceptance rule: ")
        return _finish(result, job, "rejected", f"Rejected, not activated: {text}", reasons=[text])
    version = installed["version"]
    return _finish(result, job, "accepted", f"Accepted and installed as {version['component']} v{version['id']}. Restart the "
                   f"local engine (or SPIKE) to load it; go back with: spike evolve rollback adapter:personal",
                   reasons=version["report"].get("reasons", []), version=version["id"], finished=time.time())
