"""Self-generated replay: the base model's own answers as anti-forgetting data. No network and no model: the server
is a fake llama-server behind httpx's MockTransport (so the real Teacher client parses its answers), the Hub, the
dataset and the tokenizer are replaced, as in tests/test_training.py."""

import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from spike_train.distill import Teacher  # noqa: E402
from spike_train.self_replay import (  # noqa: E402
    DROP_REASONS,
    MIN_ANSWER_TOKENS,
    TOKEN_MARGIN,
    check_server,
    first_user_prompts,
    repetition,
)

from spike.specialists.catalog import load_catalog  # noqa: E402
from tests.test_training import LEAKED, TEACHER_LICENSES, oasst, prepare_env  # noqa: E402

BASE = "Qwen/Qwen3.5-4B"
MEDICINE = ROOT / "training" / "configs" / "medicine.yaml"
SYSTEM = load_catalog().get("medicine").system_prompt
BUILD = "b11669-620d2225c"


def count_tokens(chat: dict) -> int:
    """A tokenizer stand-in: a token per word and four per message of template."""
    return sum(len(m["content"].split()) + 4 for m in chat["messages"])


class FakeServer:
    """llama-server behind MockTransport. `answer(user)` is (content, finish_reason, reasoning) for a prompt; `adapters`
    is what GET /lora-adapters returns (None: the server has no such endpoint; a number: the HTTP status it answers);
    `down` makes every request fail to connect."""

    def __init__(self, answer=None, adapters=(), props=None, down=False):
        self.answer = answer or (lambda user: (f"Answer to {user}: a short plain reply with several words.", "stop", ""))
        self.adapters = adapters
        self.down = down
        self.props = {"build_info": BUILD, "model_path": "/models/Qwen3.5-4B-Q4_K_M.gguf"} if props is None else props
        self.chats: list[dict] = []   # bodies of the chat requests
        self.calls: list[str] = []    # every request, in order
        self.fail_from: int | None = None   # chat request number (0-based) from which the server answers HTTP 500

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("connection refused")
        if request.url.path == "/lora-adapters":
            if self.adapters is None or isinstance(self.adapters, int):
                return httpx.Response(404 if self.adapters is None else self.adapters)
            return httpx.Response(200, json=self.adapters)
        if request.url.path == "/props":
            return httpx.Response(200, json=self.props)
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        if self.fail_from is not None and len(self.chats) >= self.fail_from:
            return httpx.Response(500)
        self.chats.append(body)
        content, finish, reasoning = self.answer(body["messages"][-1]["content"])
        message = {"role": "assistant", "content": content, **({"reasoning_content": reasoning} if reasoning else {})}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish}],
                                         "usage": {"completion_tokens": len(content.split())}})

    def teacher(self, *args, **kwargs) -> Teacher:
        teacher = Teacher(*args, **kwargs)
        teacher.client = httpx.AsyncClient(transport=httpx.MockTransport(self))
        return teacher


def trees(prompts: list[str]) -> list[dict]:
    """oasst2 rows: one prompter message with its best-ranked human answer per prompt."""
    return [row for i, p in enumerate(prompts) for row in (oasst(f"q{i}", None, "prompter", p),
                                                            oasst(f"a{i}", f"q{i}", "assistant", "a human answer", rank=0))]


def generate(tmp_path, monkeypatch, server: FakeServer, *flags: str, rows: list[dict] | None = None, cfg: Path = MEDICINE):
    """self_replay.py main() on a fake dataset and a fake server; returns (exit code, output file)."""
    import prepare
    import self_replay

    prepare_env(tmp_path / "data", monkeypatch)    # fake Hub licenses for the datasets and in-memory oasst2 rows
    monkeypatch.setitem(TEACHER_LICENSES, BASE, "apache-2.0")
    if rows is not None:
        monkeypatch.setattr(prepare, "load_rows", lambda src, offset=0, limit=None, **k: iter(
            rows[offset: None if limit is None else offset + limit]))
    monkeypatch.setattr(self_replay, "load_token_counter", lambda base_model: count_tokens)
    monkeypatch.setattr(self_replay, "Teacher", server.teacher)
    out = tmp_path / "self_replay.jsonl"
    monkeypatch.setattr(sys, "argv", ["self_replay.py", str(cfg), "--base-url", "http://127.0.0.1:8091/v1",
                                      "--out", str(out), *flags])
    return self_replay.main(), out


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------ the repetition rule
NATURAL = [
    "Hello. I am Spike Medicine. Before we can discuss any specific medical advice, treatment plan, or differential "
    "diagnosis, I must establish a baseline of safety and context. In evidence-based medicine, the quality of our "
    "reasoning is entirely dependent on the accuracy of the initial data.",
    "Scurvy results from vitamin C deficiency, which impairs collagen synthesis.\n\n1. Rest\n2. Fluids\n3. Review in a week\n\n"
    "| dose | days |\n| --- | --- |\n| 5 mg | 3 |\n| 10 mg | 3 |\n\nAnswer: B",
    "La hipertensión se define como una presión arterial sostenida por encima de 140/90 mmHg. El tratamiento empieza "
    "con cambios en el estilo de vida: menos sal, ejercicio regular y control del peso. Si no basta, se añade un "
    "fármaco de primera línea según las comorbilidades del paciente.",
    "Use a list comprehension. Then sort the result. Then print it. Then check the length. Then print the first item.",
]
# the first medicine adapter's own failure (training/runs/medicine/export.json): one Spanish sentence three times
LOOP = "La medicina es la ciencia que se encarga de la prevención, diagnóstico y tratamiento de las enfermedades."


@pytest.mark.parametrize("text, expected", [
    ("\n".join([LOOP] * 3), "repeated_sentence"),
    (f"{LOOP} Otra frase distinta. {LOOP.upper().rstrip('.')}", "repeated_sentence"),   # case and punctuation do not hide it
    ("Take two tablets daily.\n- Take two tablets daily with water or milk.\n- Take two tablets daily with water or milk.",
     "repeated_sentence"),
    ("take it and rest " * 12, "repeated_ngrams"),                       # no punctuation to split on
    *[(text, None) for text in NATURAL],
    ("Answer: B\n\nAnswer: B", None),                                      # formulaic lines below the word limit
    ("ok. ok. ok.", None),
    ("", None),
])
def test_repetition_rule(text, expected):
    assert repetition(text) == expected


# ------------------------------------------------------------------ the server checks
async def check(server: FakeServer) -> dict:
    teacher = server.teacher("http://127.0.0.1:8091/v1", BASE)
    try:
        return await check_server(teacher)
    finally:
        await teacher.aclose()


async def test_the_server_must_be_the_base_model_alone():
    applied = [{"id": 0, "path": "/home/x/.spike/adapters/spike-medicine.gguf", "scale": 1.0}]
    with pytest.raises(ValueError, match=r"LoRA adapters applied.*spike-medicine.gguf.*without --lora"):
        await check(FakeServer(adapters=applied))
    with pytest.raises(ValueError, match="adapters applied"):  # one of several is enough, and a small scale counts
        await check(FakeServer(adapters=[{"id": 0, "path": "a.gguf", "scale": 0.0}, {"id": 1, "path": "b.gguf", "scale": 0.25}]))
    with pytest.raises(ValueError, match="adapters applied"):  # a scale it cannot read is not zero
        await check(FakeServer(adapters=[{"id": 0, "path": "a.gguf"}]))
    # loaded but switched off (what SPIKE's own server start does), or none loaded, is the base model
    off = await check(FakeServer(adapters=[{"id": 0, "path": "a.gguf", "scale": 0.0}]))
    assert off == {"build": BUILD, "model_file": "Qwen3.5-4B-Q4_K_M.gguf", "adapters_checked": True}
    assert (await check(FakeServer(adapters=[])))["adapters_checked"] is True


async def test_a_server_without_the_adapter_endpoint_is_recorded_and_one_that_cannot_say_is_refused():
    other = await check(FakeServer(adapters=None, props={}))   # mlx_lm.server, vLLM: no /lora-adapters, no build
    assert other == {"build": None, "model_file": None, "adapters_checked": False}
    with pytest.raises(ValueError, match=r"gave no list of adapters \(HTTP 200\)"):
        await check(FakeServer(adapters={"error": "?"}))
    with pytest.raises(ValueError, match=r"gave no list of adapters \(HTTP 500\)"):
        await check(FakeServer(adapters=500))


async def test_an_unreachable_server_is_refused():
    with pytest.raises(ValueError, match="cannot reach the server at http://127.0.0.1:8091"):
        await check(FakeServer(down=True))


# ------------------------------------------------------------------ generation
def test_prompts_are_the_first_user_turn_once_per_distinct_text():
    chat = {"messages": [{"role": "user", "content": " Why is the sky blue? "}, {"role": "assistant", "content": "a"},
                         {"role": "user", "content": "And at sunset?"}, {"role": "assistant", "content": "b"}]}
    again = {"messages": [{"role": "user", "content": "why is the SKY blue"}, {"role": "assistant", "content": "c"}]}
    seen: set[str] = set()
    prompts = first_user_prompts([chat, None, again, {"messages": [{"role": "user", "content": "  "}]},
                                  {"messages": [{"role": "user", "content": "Second?"}]}], "oasst2", seen)
    assert [(p.source, p.text) for p in prompts] == [("oasst2", "Why is the sky blue?"), ("oasst2", "Second?")]
    assert first_user_prompts([again], "other", seen) == []   # the same text from another source is not asked twice


def test_each_row_is_the_base_models_greedy_no_thinking_answer_under_the_specialist_prompt(tmp_path, monkeypatch, capsys):
    server = FakeServer()
    two_turns = [oasst("q", None, "prompter", "What is a vaccine?"), oasst("a", "q", "assistant", "human", rank=0),
                 oasst("q2", "a", "prompter", "Is it safe?"), oasst("a2", "q2", "assistant", "human two", rank=0)]
    code, out = generate(tmp_path, monkeypatch, server, rows=[*two_turns, *trees(["What is a vaccine?", "Name a prime."])])
    assert code == 0
    # two chats start with "What is a vaccine?" and a third repeats it: one request for it, one for the other prompt
    assert [c["messages"][-1]["content"] for c in server.chats] == ["What is a vaccine?", "Name a prime."]
    for body in server.chats:
        assert body["temperature"] == 0.0 and body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["messages"][0] == {"role": "system", "content": SYSTEM} and len(body["messages"]) == 2
    rows = read_rows(out)
    assert [r["messages"][1]["content"] for r in rows] == ["What is a vaccine?", "Name a prime."]
    first = rows[0]
    assert [m["role"] for m in first["messages"]] == ["system", "user", "assistant"]
    assert first["messages"][2]["content"] == "Answer to What is a vaccine?: a short plain reply with several words."
    used = count_tokens({"messages": [*first["messages"][:2], {"role": "assistant", "content": ""}]})
    meta = first["meta"]
    assert meta["max_tokens"] == server.chats[0]["max_tokens"] == 768 - used - TOKEN_MARGIN   # the prompt and answer fit
    assert len(meta.pop("prompt_id")) == 16
    assert meta == {
        "source": "self_replay", "generator": BASE, "generator_license": "apache-2.0", "prompt_source": "oasst2",
        "server": {"build": BUILD, "model_file": "Qwen3.5-4B-Q4_K_M.gguf", "adapters_checked": True},
        "settings": {"specialist": "medicine", "temperature": 0.0, "thinking": False, "max_seq_length": 768},
        "max_tokens": 768 - used - TOKEN_MARGIN, "completion_tokens": len(first["messages"][2]["content"].split()),
        "finish_reason": "stop"}
    summary = json.loads(capsys.readouterr().out)
    assert summary == json.loads(out.with_suffix(".summary.json").read_text())
    assert summary["prompts"] == 2 and summary["kept"] == 2 and summary["generator_license"] == "apache-2.0"
    assert summary["dropped"] == dict.fromkeys(DROP_REASONS, 0)
    assert not out.with_name(out.name + ".partial").exists()


def by_residue(user: str):
    """The 8 kinds of answer a server can give, chosen by the prompt's number ('general question 13' -> 5)."""
    kind = int(user.rsplit(" ", 1)[1]) % 8
    return {
        0: ("A start that was cut off by the limit", "length", ""),
        1: ("", "stop", ""),
        2: ("The same sentence is said again here. The same sentence is said again here.", "stop", ""),
        3: ("An answer that came after thinking", "stop", "First I think about it."),
        4: ("take it and rest " * 12, "stop", ""),
        5: ("An answer of a kind the server did not finish", "abort", ""),
        6: (" ".join(f"w{i}" for i in range(700)), "stop", ""),   # fits the request's budget, not the trainer's count
        7: (f"A good answer to {user}, with its own words.", "stop", ""),
    }[kind]


def test_answers_that_hit_the_limit_are_empty_or_repeat_themselves_are_dropped_and_counted(tmp_path, monkeypatch):
    server = FakeServer(by_residue)
    code, out = generate(tmp_path, monkeypatch, server, "--limit", "64")
    assert code == 0 and len(server.chats) == 64
    summary = json.loads(out.with_suffix(".summary.json").read_text())
    assert summary["prompts"] == 64 and summary["kept"] == 8
    assert summary["dropped"] == {"prompt_too_long": 0, "thinking": 8, "hit_length_limit": 8, "unfinished": 8, "empty": 8,
                                  "repeated_sentence": 8, "repeated_ngrams": 8, "too_long": 8}
    rows = read_rows(out)
    assert len(rows) == 8 and all(r["messages"][2]["content"].startswith("A good answer") for r in rows)


def test_a_prompt_with_no_room_for_an_answer_is_dropped_without_asking_the_server(tmp_path, monkeypatch):
    long_prompt = "word " * 700
    server = FakeServer()
    code, out = generate(tmp_path, monkeypatch, server, rows=trees(["Short one?", long_prompt, "Another short?"]))
    assert code == 0
    assert [c["messages"][-1]["content"] for c in server.chats] == ["Short one?", "Another short?"]
    assert json.loads(out.with_suffix(".summary.json").read_text())["dropped"]["prompt_too_long"] == 1
    assert MIN_ANSWER_TOKENS == 16 and all(c["max_tokens"] >= MIN_ANSWER_TOKENS for c in server.chats)


def test_nothing_kept_writes_no_replay_file(tmp_path, monkeypatch):
    server = FakeServer(lambda user: ("", "length", ""))
    with pytest.raises(SystemExit, match=r"no answer was kept.*hit_length_limit.*--jinja"):
        generate(tmp_path, monkeypatch, server, "--limit", "5")
    assert not (tmp_path / "self_replay.jsonl").exists()


# ------------------------------------------------------------------ what is refused, and before what
@pytest.mark.parametrize("hub, message", [
    ("other", "license 'other' is not allowed for role 'train'"),
    ("cc-by-nc-4.0", "license 'cc-by-nc-4.0' is not allowed for role 'train'"),
    (None, "no license declared"),
])
def test_a_generator_whose_license_is_not_allowed_or_unknown_is_refused_before_the_server_is_asked(
        tmp_path, monkeypatch, hub, message):
    server = FakeServer()
    prepare_env(tmp_path / "data", monkeypatch)
    monkeypatch.setitem(TEACHER_LICENSES, BASE, hub)
    import self_replay

    monkeypatch.setattr(self_replay, "Teacher", server.teacher)
    monkeypatch.setattr(sys, "argv", ["self_replay.py", str(MEDICINE), "--base-url", "http://x/v1", "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit, match=f"refusing to generate: generator '{BASE}': {message}"):
        self_replay.main()
    assert server.calls == [] and not (tmp_path / "o").exists()


def test_a_license_the_hub_cannot_be_asked_for_is_refused(tmp_path, monkeypatch):
    def down(repo):
        raise httpx.ConnectError("no network")

    server = FakeServer()
    prepare_env(tmp_path / "data", monkeypatch)
    monkeypatch.setattr("spike_train.licenses.hub_model_license", down)
    import self_replay

    monkeypatch.setattr(self_replay, "Teacher", server.teacher)
    monkeypatch.setattr(sys, "argv", ["self_replay.py", str(MEDICINE), "--base-url", "http://x/v1", "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit, match="cannot read its license on the Hugging Face Hub.*--base-repo"):
        self_replay.main()
    assert server.calls == []


def test_a_server_with_an_adapter_applied_is_refused_before_any_prompt_is_sent(tmp_path, monkeypatch):
    server = FakeServer(adapters=[{"id": 0, "path": "/a/spike-medicine.gguf", "scale": 1.0}])
    with pytest.raises(SystemExit, match=r"refusing to generate: the server has LoRA adapters applied"):
        generate(tmp_path, monkeypatch, server)
    assert "/v1/chat/completions" not in server.calls and not (tmp_path / "self_replay.jsonl").exists()


def test_the_generator_must_be_the_recipes_base_model(tmp_path, monkeypatch):
    server = FakeServer()
    with pytest.raises(SystemExit, match="--base-repo Qwen/Qwen3.6-35B-A3B is not the recipe's base model"):
        generate(tmp_path, monkeypatch, server, "--base-repo", "Qwen/Qwen3.6-35B-A3B")
    assert server.calls == []


# ------------------------------------------------------------------ an interrupted run
def test_resume_continues_an_interrupted_run_and_refuses_changed_settings(tmp_path, monkeypatch):
    out = tmp_path / "self_replay.jsonl"
    partial = out.with_name(out.name + ".partial")
    crashing = FakeServer()
    crashing.fail_from = 40    # the second batch of 32 fails on its 9th request
    with pytest.raises(httpx.HTTPStatusError):
        generate(tmp_path, monkeypatch, crashing, "--limit", "70")
    assert not out.exists() and len(partial.read_text().splitlines()) == 1 + 32   # the header and the first batch
    with partial.open("a") as f:   # a kill in the middle of writing a line
        f.write('{"prompt_id": "abc", "ro')

    with pytest.raises(SystemExit, match="left by an interrupted run: --resume continues it"):
        generate(tmp_path, monkeypatch, FakeServer(), "--limit", "70")

    server = FakeServer()
    code, out = generate(tmp_path, monkeypatch, server, "--limit", "70", "--resume")
    assert code == 0 and len(server.chats) == 70 - 32   # only what was not done
    summary = json.loads(out.with_suffix(".summary.json").read_text())
    assert summary["prompts"] == 70 and summary["kept"] == 70 and summary["resumed_prompts"] == 32
    rows = read_rows(out)
    assert [r["messages"][1]["content"] for r in rows] == [f"general question {i}" for i in range(70)]   # in prompt order
    assert not partial.exists()

    # a partial file made by another server build (or generator, or limits) is not mixed with new answers
    crashing = FakeServer()
    crashing.fail_from = 5
    with pytest.raises(httpx.HTTPStatusError):
        generate(tmp_path, monkeypatch, crashing, "--limit", "70")
    other = FakeServer(props={"build_info": "b99999-other", "model_path": "/m/x.gguf"})
    with pytest.raises(SystemExit, match="made with other settings"):
        generate(tmp_path, monkeypatch, other, "--limit", "70", "--resume")


# ------------------------------------------------------------------ prepare.py
def self_generated_config(tmp_path) -> Path:
    cfg = yaml.safe_load(MEDICINE.read_text())
    cfg["replay"]["self_generated"] = True
    path = tmp_path / "medicine-self.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def prepare_with(tmp_path, monkeypatch, *args: str, cfg: Path | None = None):
    """prepare.py main() for medicine on in-memory sources; returns (exit code, output folder)."""
    import prepare

    out = prepare_env(tmp_path / "data", monkeypatch)
    monkeypatch.setitem(TEACHER_LICENSES, BASE, "apache-2.0")
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(cfg or MEDICINE), "--out", str(tmp_path / "data"), *args])
    return prepare.main(), out


def replay_file(tmp_path, n: int = 40, mutate=None) -> Path:
    """What self_replay.py writes, made by hand so a test can break one thing."""
    rows = []
    for i in range(n):
        row = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"general question {i}"},
                            {"role": "assistant", "content": f"The base model's own answer {i} to this."}],
               "meta": {"source": "self_replay", "generator": BASE, "generator_license": "apache-2.0",
                        "prompt_source": "oasst2", "prompt_id": f"p{i}"}}
        rows.append(mutate(i, row) if mutate else row)
    path = tmp_path / "files" / "self_replay.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_prepare_stops_when_the_recipe_wants_self_generated_replay_and_has_no_file(tmp_path, monkeypatch):
    import prepare

    cfg = self_generated_config(tmp_path)
    out = prepare_env(tmp_path / "data", monkeypatch)
    downloads = []
    monkeypatch.setattr(prepare, "load_rows", lambda *a, **k: downloads.append(a) or iter([]))
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(cfg), "--out", str(tmp_path / "data")])
    with pytest.raises(SystemExit, match=r"replay.self_generated\) but no file was given.*self_replay.py .*--self-replay"):
        prepare.main()
    assert not downloads and not (out / "train.jsonl").exists() and not (out / "manifest.json").exists()   # at once
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--self-replay", str(tmp_path / "missing.jsonl")])
    with pytest.raises(SystemExit, match="missing.jsonl: no such file"):
        prepare.main()
    assert not downloads and not (out / "train.jsonl").exists()


def test_prepare_takes_the_replay_from_the_self_replay_file_and_records_it(tmp_path, monkeypatch):
    """generate (fake server) -> prepare: the replay in the mix is the base model's answers, not oasst2's, and the
    manifest names the file by hash, with its rows and its generator and license."""
    from model_card import training_credits

    server = FakeServer()
    code, replay = generate(tmp_path, monkeypatch, server, "--limit", "60")
    assert code == 0
    code, out = prepare_with(tmp_path, monkeypatch, "--self-replay", str(replay), cfg=self_generated_config(tmp_path))
    assert code == 0
    manifest = json.loads((out / "manifest.json").read_text())
    record = manifest["sources"]["self_replay:self_replay.jsonl"]
    assert record == {"role": "train", "self_generated": True, "sha256": hashlib.sha256(replay.read_bytes()).hexdigest(),
                      "rows": 60, "kept": 60,
                      "teachers": {BASE: {"license_hub": "apache-2.0", "license_recorded": "apache-2.0"}}}
    assert manifest["sources"]["oasst2"]["license_hub"] == "apache-2.0" and manifest["sources"]["oasst2"]["kept"] == 60
    assert "built" not in manifest["sources"]["oasst2"]   # its chats were not built: only its prompts were used
    counts = manifest["counts"]
    assert counts["domain"] == 50 and counts["replay_available"] == 60
    assert counts["train"] + counts["valid"] - counts["domain"] == int(50 * 0.3 / 0.7)   # mix_and_split unchanged
    chats = [json.loads(x) for name in ("train", "valid") for x in (out / f"{name}.jsonl").read_text().splitlines()]
    general = [c for c in chats if c["messages"][1]["content"].startswith("general question")]
    assert len(general) == 21 and all(c["messages"][0]["content"] == SYSTEM for c in general)
    assert all(c["messages"][2]["content"].startswith("Answer to general question") for c in general)   # not "a general answer"
    assert not any(c["messages"][2]["content"] == "a general answer" for c in chats)
    assert all("meta" not in c for c in chats)   # the provenance stays in the manifest
    assert [c["license"] for c in training_credits(manifest) if c["teacher"]] == ["apache-2.0"]   # the model card sees it


def test_prepare_uses_the_file_given_even_when_the_config_does_not_ask_for_self_generated_replay(tmp_path, monkeypatch):
    code, out = prepare_with(tmp_path, monkeypatch, "--self-replay", str(replay_file(tmp_path)))
    assert code == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sources"]["self_replay:self_replay.jsonl"]["rows"] == 40 and "self_generated" not in manifest["config"]["replay"]
    assert manifest["sources"]["oasst2"].get("built") is None


def test_the_default_replay_is_unchanged_without_a_file(tmp_path, monkeypatch):
    code, out = prepare_with(tmp_path, monkeypatch)
    manifest = json.loads((out / "manifest.json").read_text())
    assert code == 0 and manifest["sources"]["oasst2"]["built"] == 200 and not any(
        name.startswith("self_replay") for name in manifest["sources"])
    chats = [json.loads(x) for x in (out / "train.jsonl").read_text().splitlines()]
    assert any(c["messages"][-1]["content"] == "a general answer" for c in chats)   # the human-written replay


def test_prepare_filters_the_replay_rows_like_any_other_chat(tmp_path, monkeypatch):
    def mutate(i, row):
        if i == 0:
            row["messages"][1]["content"] = LEAKED                      # shares a 13-gram with an eval set
        if i == 1:
            row["messages"][1]["content"] = "LONG " + "word " * 5       # the faked tokenizer counts it over 768
        if i == 2:
            row["messages"][2]["content"] = "x"                         # below the quality floor
        return row

    code, out = prepare_with(tmp_path, monkeypatch, "--self-replay", str(replay_file(tmp_path, mutate=mutate)))
    manifest = json.loads((out / "manifest.json").read_text())
    assert code == 0 and manifest["sources"]["self_replay:self_replay.jsonl"]["kept"] == 37
    assert manifest["dropped"]["contaminated"] == 2 and manifest["dropped"]["too_long"] == 1 + 1   # + the long medmcqa one
    assert manifest["dropped"]["format_or_quality"] == 1 and manifest["counts"]["replay_available"] == 37


def break_license(license_id):
    def mutate(i, row):
        row["meta"]["generator_license"] = license_id
        return row
    return mutate


@pytest.mark.parametrize("hub, reason", [
    ("other", "license 'other' is not allowed for role 'train'"),
    (None, "no license declared"),
])
def test_prepare_checks_the_generators_license_again_on_the_hub(tmp_path, monkeypatch, hub, reason):
    import prepare

    path = replay_file(tmp_path)   # the file says Apache-2.0
    out = prepare_env(tmp_path / "data", monkeypatch)
    monkeypatch.setitem(TEACHER_LICENSES, BASE, hub)   # the Hub says otherwise now
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(MEDICINE), "--out", str(tmp_path / "data"), "--self-replay", str(path)])
    with pytest.raises(SystemExit, match=f"refusing self_replay.jsonl: generator '{BASE}': {reason}"):
        prepare.main()
    assert not (out / "train.jsonl").exists()


def test_prepare_offline_trusts_the_recorded_generator_license_but_still_applies_the_allowlist(tmp_path, monkeypatch):
    import prepare

    def no_hub(repo):
        raise AssertionError("the Hub must not be asked")

    ok = replay_file(tmp_path / "ok")
    prepare_env(tmp_path / "ok" / "data", monkeypatch)
    monkeypatch.setattr(prepare.licenses, "hub_model_license", no_hub)
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(MEDICINE), "--out", str(tmp_path / "ok" / "data"),
                                      "--self-replay", str(ok), "--skip-license-check"])
    assert prepare.main() == 0
    for recorded, reason in (("other", "license 'other' is not allowed"), (None, "no license declared")):
        bad = replay_file(tmp_path / str(recorded), mutate=break_license(recorded))
        prepare_env(tmp_path / str(recorded) / "data", monkeypatch)
        monkeypatch.setattr(prepare.licenses, "hub_model_license", no_hub)
        monkeypatch.setattr(sys, "argv", ["prepare.py", str(MEDICINE), "--out", str(tmp_path / str(recorded) / "data"),
                                          "--self-replay", str(bad), "--skip-license-check"])
        with pytest.raises(SystemExit, match=f"refusing self_replay.jsonl: generator '{BASE}': {reason}"):
            prepare.main()


@pytest.mark.parametrize("mutate, message", [
    (lambda i, row: {**row, "meta": {"generator": BASE}}, r"self_replay.jsonl:1 has no self-replay record"),
    (lambda i, row: {**row, "meta": {k: v for k, v in row["meta"].items() if k != "generator"}},
     r"self_replay.jsonl:1 has no self-replay record"),
    (lambda i, row: {**row, "messages": row["messages"][1:]}, r"self_replay.jsonl:1 is not a \(system, user, assistant\) chat"),
    (lambda i, row: {**row, "messages": [{"role": "system", "content": "an older prompt"}, *row["messages"][1:]]},
     r"self_replay.jsonl:1 is not a \(system, user, assistant\) chat under the specialist's current system prompt"),
    (lambda i, row: {**row, "meta": {**row["meta"], "prompt_source": "smoltalk"}},
     r"self_replay.jsonl:1 has prompts from 'smoltalk', which replay.sources of the config does not list \(oasst2\)"),
    (lambda i, row: {**row, "meta": {**row["meta"], "generator_license": "mit"}} if i == 1 else row,
     r"self_replay.jsonl:2 records another license for 'Qwen/Qwen3.5-4B' than the rows before it"),
])
def test_prepare_refuses_a_file_that_is_not_what_the_recipe_asked_for(tmp_path, monkeypatch, mutate, message):
    path = replay_file(tmp_path, n=3, mutate=mutate)
    with pytest.raises(SystemExit, match=message):
        prepare_with(tmp_path, monkeypatch, "--self-replay", str(path))
    assert not (tmp_path / "data" / "medicine" / "train.jsonl").exists()
