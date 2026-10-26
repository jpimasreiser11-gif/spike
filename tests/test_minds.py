"""Parallel Minds: N independent answers to one message and the best of them, picked from the trust labels. Off unless a
request asks for it; the provider guard (paid calls, monthly limits) counts every one of the N calls and refuses the
batch before anything starts when it would cross a limit."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.orchestrator.minds import TEMPERATURES, Candidate, Mind, mind_options, pick, plan_minds, run_minds
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.providers.openai_compat import OpenAICompatProvider
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import default_registry
from tests.helpers import ScriptedProvider, call, text

QUESTION = "Dime algo del modelo Zorvak: el modelo Zorvak tiene 12 capas."
# by temperature: the one at 0.7 restates the user and invents nothing; 0.3 mixes; 1.0 only invents
ANSWERS = {
    0.3: "El modelo Zorvak tiene 12 capas. Fue entrenado en 2019 con 40 GPUs. Cuesta 300 euros al mes.",
    0.7: "El modelo Zorvak tiene 12 capas.",
    1.0: "Fue entrenado en 2019 con 40 GPUs. Su latencia media es de 35 ms.",
}


def by_temperature(request):
    """The answer of that temperature; an ordinary run (no temperature set) gets the plain one."""
    return text(ANSWERS[0.7 if request.temperature is None else round(request.temperature, 1)])


def counts(v: int, h: int, u: int) -> dict[str, int]:
    return {"verified": v, "hypothesis": h, "unchecked": u}


def cand(index, v=0, h=0, u=0, answered=True, failed=False) -> Candidate:
    return Candidate(index, text="answer" if answered else "", counts=counts(v, h, u), verifier_failed=failed)


# ---------------------------------------------------------------- the minds and the pick
@pytest.mark.parametrize("n", [2, 3, 4])
def test_minds_differ_by_a_fixed_temperature_spread(n):
    minds = plan_minds(n)
    assert [m.index for m in minds] == list(range(n))
    assert [m.temperature for m in minds] == list(TEMPERATURES[n])
    assert len(set(m.temperature for m in minds)) == n and all(m.mode is None and m.provider_id is None for m in minds)


@pytest.mark.parametrize("n", [None, 0, 1, 5, True, "3"])
def test_the_number_of_minds_is_two_to_four(n):
    with pytest.raises(ValueError, match="2 to 4"):
        plan_minds(n)


def test_picked_specialists_and_providers_keep_the_users_temperature_unless_two_picks_are_equal():
    minds = plan_minds(None, [{"mode": "finance"}, {"mode": "math", "provider_id": "openai"}, {"mode": "finance"}])
    assert [(m.mode, m.provider_id) for m in minds] == [("finance", None), ("math", "openai"), ("finance", None)]
    assert [m.temperature for m in minds] == [None, None, TEMPERATURES[3][2]]  # the repeated pick still differs
    assert plan_minds(None, [{"mode": "auto"}, {}])[0].mode is None
    with pytest.raises(ValueError, match="picked"):
        plan_minds(3, [{}, {}])
    assert [m.index for m in plan_minds(2, [{}, {}])] == [0, 1]


def test_the_pick_prefers_more_verified_and_fewer_unchecked_and_is_deterministic():
    a = cand(0, v=5, u=3)  # net 2
    b = cand(1, v=2, u=0)  # net 2, fewer unchecked
    c = cand(2, v=3, u=0)  # net 3
    d = cand(3, v=0, u=0)  # nothing to check
    assert pick([a, b, c, d])[0] == 2
    assert pick([a, b])[0] == 1  # same net: fewer unchecked wins
    assert pick([cand(0, v=2, u=1), cand(1, v=1, u=0)])[0] == 1  # same net (1): fewer unchecked
    assert pick([cand(0, v=1, u=1, h=9), cand(1, v=1, u=1)])[0] == 0  # hypotheses count neither way: tie -> first
    for order in ([a, b, c, d], [d, c, b, a], [b, d, a, c]):  # the order the minds finished in changes nothing
        assert pick(order)[0] == 2 and pick(order)[1] == [2, 1, 0, 3]


def test_a_failed_checker_and_a_missing_answer_lose_to_any_answer():
    failed = cand(0, v=9, failed=True)
    plain = cand(1, v=1, u=1)
    assert pick([failed, plain])[0] == 1
    silent = cand(0, v=9, answered=False)
    assert pick([silent, plain]) == (1, [1, 0], "only")
    errored = Candidate(2, text="something", error="boom")
    assert pick([errored, plain])[0] == 1
    assert pick([silent, errored]) == (None, [0, 2], "none")  # equal keys: the lower mind first


def test_ties_go_to_the_lower_mind_and_the_reason_says_so():
    tied = [cand(2, v=1), cand(0, v=1), cand(1, v=1)]
    assert pick(tied) == (0, [0, 1, 2], "order")
    assert pick([cand(0, v=1), cand(1, v=2)]) == (1, [1, 0], "labels")


def test_each_mind_gets_its_options_with_the_labels_on_and_read_only_tools():
    opts = OrchestratorOptions(mode="auto", temperature=None, trust=False, json_schema={"type": "object"})
    mine = mind_options(opts, Mind(1, mode="finance", temperature=0.7))
    assert mine.mode == "finance" and mine.temperature == 0.7 and mine.trust and mine.read_only
    assert mine.json_schema is None and not mine.trust_model_pass
    assert mind_options(OrchestratorOptions(temperature=0.2), Mind(0)).temperature == 0.2  # the user's own setting
    assert opts.read_only is False and opts.trust is False  # the chat's options are left alone


# ---------------------------------------------------------------- the runner
CATALOG = load_catalog()


def orchestrator(provider, tmp_path, broker=None):
    return Orchestrator(CATALOG, lambda spec: Backend(provider=provider, model=None, adapter=None),
                        default_registry(tmp_path), broker or PermissionBroker({"write_file": "allow"}))


async def collect(minds, provider, tmp_path, concurrent=False, opts=None):
    orch = orchestrator(provider, tmp_path)
    return [e async for e in run_minds(minds, lambda m: orch, [], QUESTION, opts or OrchestratorOptions(mode="core"),
                                       concurrent=concurrent)]


@pytest.mark.parametrize("concurrent", [False, True])
async def test_n_answers_are_produced_and_the_pick_follows_the_labels(tmp_path, concurrent):
    provider = ScriptedProvider(by_temperature)
    evs = await collect(plan_minds(3), provider, tmp_path, concurrent)
    assert sorted(r.temperature for r in provider.requests) == [0.3, 0.7, 1.0]  # three calls, three temperatures
    results = {e["mind"]: e for e in evs if e["type"] == "mind_result"}
    assert {i: r["text"] for i, r in results.items()} == {0: ANSWERS[0.3], 1: ANSWERS[0.7], 2: ANSWERS[1.0]}
    assert results[1]["counts"] == counts(1, 0, 0) and results[2]["counts"]["verified"] == 0
    assert results[2]["counts"]["unchecked"] == 2 and results[0]["counts"]["unchecked"] == 2
    pick_ev = next(e for e in evs if e["type"] == "minds_pick")
    assert pick_ev["chosen"] == 1 and pick_ev["ranking"] == [1, 0, 2] and pick_ev["why"] == "labels"
    done = evs[-1]
    assert done["type"] == "done" and done["text"] == ANSWERS[0.7] and not done["error"]
    trust = [e for e in evs if e["type"] == "trust" and "mind" not in e]  # the chosen answer's, as an ordinary run's
    assert len(trust) == 1 and trust[0]["counts"] == counts(1, 0, 0)
    assert all(e["mind"] in (0, 1, 2) for e in evs if "mind" in e)
    assert evs[0]["type"] == "minds_start" and evs[0]["n"] == 3
    assert [e["type"] for e in evs[-3:]] == ["minds_pick", "trust", "done"]


async def test_a_mind_that_fails_does_not_stop_the_others(tmp_path):
    def script(request):
        if request.temperature == 0.3:
            raise RuntimeError("boom")
        return by_temperature(request)

    evs = await collect(plan_minds(3), ScriptedProvider(script), tmp_path)
    results = {e["mind"]: e for e in evs if e["type"] == "mind_result"}
    assert not results[0]["ok"] and "boom" in results[0]["error"] and results[1]["ok"] and results[2]["ok"]
    assert next(e for e in evs if e["type"] == "minds_pick")["chosen"] == 1
    assert evs[-1]["text"] == ANSWERS[0.7]


async def test_when_no_mind_answers_the_run_ends_with_an_error(tmp_path):
    def script(request):
        raise RuntimeError("boom")

    evs = await collect(plan_minds(2), ScriptedProvider(script), tmp_path)
    pick_ev = next(e for e in evs if e["type"] == "minds_pick")
    assert pick_ev["chosen"] is None and pick_ev["why"] == "none"
    assert evs[-1]["type"] == "done" and evs[-1]["text"] == "" and "none of the 2 minds answered" in evs[-1]["error"]
    assert not any(e["type"] == "trust" and "mind" not in e for e in evs)


async def test_minds_cannot_write_files_run_code_or_ask_questions(tmp_path):
    """N copies of a turn must not write N times: a mind sees only tools that read or compute."""
    provider = ScriptedProvider(lambda r: text("Listo.") if any(m.role == "tool" for m in r.messages)
                                else call("write_file", {"path": "x.txt", "content": "hola"}))
    evs = await collect(plan_minds(2), provider, tmp_path)
    assert not (tmp_path / "x.txt").exists()
    results = [e for e in evs if e["type"] == "tool_result"]
    assert results and all(not r["ok"] and "not available" in r["content"] for r in results)
    names = {t.name for r in provider.requests for t in r.tools}
    assert {"calculator", "read_file", "web_fetch"} <= names
    assert not names & {"write_file", "python", "create_docx", "remember", "ask_user"}
    # the control: the same script outside Parallel Minds does write the file
    plain = Orchestrator(CATALOG, lambda spec: Backend(provider=provider, model=None, adapter=None),
                         default_registry(tmp_path), PermissionBroker({"write_file": "allow"}))
    [_ async for _ in plain.run([], "guarda x", OrchestratorOptions(mode="core"))]
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "hola"


async def test_minds_with_picked_specialists_and_providers_run_where_they_were_told(tmp_path):
    provider_a, provider_b = ScriptedProvider(by_temperature, name="a"), ScriptedProvider(by_temperature, name="b")
    chosen = {"finance": provider_a, "math": provider_b}
    orchs = {sid: Orchestrator(CATALOG, lambda spec, p=p: Backend(provider=p, model=None, adapter=None),
                               default_registry(tmp_path), PermissionBroker()) for sid, p in chosen.items()}
    minds = plan_minds(None, [{"mode": "finance", "provider_id": "finance"}, {"mode": "math", "provider_id": "math"}])
    evs = [e async for e in run_minds(minds, lambda m: orchs[m.provider_id], [], QUESTION,
                                      OrchestratorOptions(mode="auto"))]
    routes = {e["mind"]: [s["id"] for s in e["specialists"]] for e in evs if e["type"] == "route"}
    assert routes == {0: ["finance"], 1: ["math"]}
    assert len(provider_a.requests) == 1 and len(provider_b.requests) == 1
    assert provider_a.requests[0].temperature is None  # picked minds use the user's setting


# ---------------------------------------------------------------- through the app
class Remote:
    """A fake OpenAI-compatible API: a fixed answer and the usage it reports; it keeps every request body."""

    def __init__(self, tokens_in=1000, tokens_out=200):
        self.bodies: list[str] = []
        self.usage = (tokens_in, tokens_out)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content.decode())
        chunks = [{"choices": [{"index": 0, "delta": {"content": ANSWERS[0.7]}, "finish_reason": None}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                  {"choices": [], "usage": {"prompt_tokens": self.usage[0], "completion_tokens": self.usage[1]}}]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    remote = Remote()
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        if cfg.kind == "openai":
            return OpenAICompatProvider(cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(remote)))
        p = scripts.setdefault(cfg.id, ScriptedProvider(by_temperature, name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")  # creates the local provider
    return client, state, remote, scripts


def add_remote(client, **extra):
    body = {"preset": "openai", "api_key": "sk-test", "model": "gpt-test", "allow_paid": True,
            "limits": {"price_in": 2.0, "price_out": 10.0}, **extra}
    assert client.post("/api/providers", json=body).status_code == 200


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def chat(client, minds=None, message=QUESTION, **extra):
    body = {"message": message, "mode": "core", "provider_id": "spike-local", **extra}
    if minds is not None:
        body["parallel_minds"] = minds
    return client.post("/api/chat", json=body)


def stored(client, evs) -> dict:
    conv = next(e for e in evs if e["type"] == "conversation")
    msgs = client.get(f"/api/conversations/{conv['id']}").json()["messages"]
    return next(m for m in msgs if m["role"] == "assistant")


def test_minds_in_the_app_produce_n_answers_and_keep_the_others_with_their_labels(env):
    client, _, _, scripts = env
    r = chat(client, {"n": 3})
    assert r.status_code == 200, r.text
    evs = events_of(r)
    assert sorted(q.temperature for q in scripts["spike-local"].requests) == [0.3, 0.7, 1.0]
    assert evs[-1]["type"] == "done" and evs[-1]["text"] == ANSWERS[0.7]
    trust = next(e for e in evs if e["type"] == "trust" and "mind" not in e)
    assert trust["counts"] == counts(1, 0, 0)
    answer = stored(client, evs)
    assert answer["content"] == ANSWERS[0.7]  # the chosen answer is what the chat goes on from
    minds = answer["meta"]["minds"]
    assert minds["n"] == 3 and minds["chosen"] == 1 and minds["ranking"] == [1, 0, 2] and minds["why"] == "labels"
    assert [m["index"] for m in minds["minds"]] == [0, 1, 2] and [m["temperature"] for m in minds["minds"]] == [0.3, 0.7, 1.0]
    assert [m["text"] for m in minds["minds"]] == [ANSWERS[0.3], ANSWERS[0.7], ANSWERS[1.0]]
    assert all(m["trust"]["claims"] for m in minds["minds"])  # each one keeps its labelled claims
    assert minds["minds"][1]["counts"] == counts(1, 0, 0) and minds["minds"][1]["route"][0]["id"] == "core"
    assert answer["meta"]["trust"]["counts"] == counts(1, 0, 0) and answer["meta"]["route"]["specialists"][0]["id"] == "core"
    assert len(answer["meta"]["usage"]) == 0  # the scripted provider reports no usage
    # the next turn sees one assistant message, the chosen one
    conv = next(e for e in evs if e["type"] == "conversation")["id"]
    scripts["spike-local"]._script = lambda req: text("ok")
    follow = chat(client, None, "gracias", conversation_id=conv)
    assert follow.status_code == 200
    sent = scripts["spike-local"].requests[-1].messages
    assert [m.content for m in sent if m.role == "assistant"] == [ANSWERS[0.7]]


def test_minds_run_together_with_the_parallel_setting(env):
    client, _, _, scripts = env
    client.put("/api/settings", json={"parallel": True})
    scripts["spike-local"]._script = lambda request: text(ANSWERS[0.3 if request.temperature == 0.3 else 0.7])
    evs = events_of(chat(client, {"n": 2}))
    assert sorted(q.temperature for q in scripts["spike-local"].requests) == [0.3, 0.9]
    assert next(e for e in evs if e["type"] == "minds_pick")["chosen"] == 1  # the same pick as one after the other


def test_trust_labels_are_used_even_when_the_user_turned_them_off(env):
    client, *_ = env
    client.put("/api/settings", json={"trust": {"enabled": False}})
    evs = events_of(chat(client, {"n": 2}))
    assert any(e["type"] == "trust" for e in evs) and evs[-1]["text"]


def test_off_by_default_everywhere(env):
    client, state, _, scripts = env
    evs = events_of(chat(client))
    assert len(scripts["spike-local"].requests) == 1
    assert not any(e["type"].startswith("mind") for e in evs) and "minds" not in stored(client, evs)["meta"]
    assert state.options("auto").read_only is False and state.options("auto").trust is False
    assert chat(client, {}).status_code == 400  # asking for minds without saying how many is a mistake, not "off"
    assert len(scripts["spike-local"].requests) == 1


async def test_the_cli_path_runs_one_mind(env):
    """`spike chat` builds `state.options(mode)` and runs the orchestrator: no parameter makes that N runs."""
    _, state, _, scripts = env
    orch = state.orchestrator()
    evs = [e async for e in orch.run([], QUESTION, state.options("core"))]
    assert len(scripts["spike-local"].requests) == 1 and not any("mind" in e or e["type"].startswith("mind") for e in evs)


async def test_mcp_ignores_a_request_for_minds(env):
    from spike.server.mcp_server import SpikeMcp

    _, state, _, scripts = env
    result = await SpikeMcp(state).call("ask_spike", {"question": QUESTION, "specialist": "core",
                                                      "parallel_minds": {"n": 3}})
    assert not result["isError"] and len(scripts["spike-local"].requests) == 1


def test_v1_ignores_a_request_for_minds(env, monkeypatch):
    client, _, _, scripts = env
    monkeypatch.setenv("SPIKE_API_TOKEN", "secret")  # the test client is not "this computer"
    r = client.post("/v1/chat/completions", headers={"Authorization": "Bearer secret"},
                    json={"model": "spike-core", "parallel_minds": {"n": 3},
                          "messages": [{"role": "user", "content": QUESTION}]})
    assert r.status_code == 200, r.text
    assert len(scripts["spike-local"].requests) == 1


@pytest.mark.parametrize("minds,status", [({"n": 1}, 422), ({"n": 5}, 422), ({"picks": [{}]}, 422),
                                          ({"n": 3, "picks": [{}, {}]}, 400), ({"n": 2, "picks": [{"mode": "zz"}, {}]}, 400),
                                          ({"picks": [{"provider_id": "zz"}, {}]}, 400)])
def test_bad_requests_for_minds(env, minds, status):
    client, _, _, scripts = env
    assert chat(client, minds).status_code == status
    assert scripts["spike-local"].requests == []


def test_minds_cannot_be_combined_with_a_contract_or_a_blueprint(env):
    client, *_ = env
    r = chat(client, {"n": 2}, response_schema={"type": "object"})
    assert r.status_code == 400 and "prose answer" in r.json()["detail"]
    forge = {"goal": "g", "requirements": [], "criteria": [], "steps": [{
        "id": "t1", "specialist": "core", "role": "execute", "instruction": "haz algo", "depends_on": [],
        "deliverables": []}]}
    assert chat(client, {"n": 2}, forge=forge).status_code == 400


# ---------------------------------------------------------------- the cost shown first, and the guard
def test_the_estimate_gives_the_multiplier_and_the_cost_at_the_users_prices_without_calling_anything(env):
    client, _, remote, scripts = env
    add_remote(client)
    r = client.post("/api/minds/estimate", json={"n": 3, "message": "hola", "provider_id": "openai", "mode": "core"})
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["n"] == 3 and est["multiplier"] == 3 and est["blocked"] is None and not est["multi_step"]
    [p] = est["providers"]
    assert p["provider_id"] == "openai" and p["calls"] == 3 and p["paid"] and not p["local"]
    assert p["tokens_out"] == 3 * 2048 and p["tokens_in"] > 0
    assert p["cost"] == pytest.approx((p["tokens_in"] * 2.0 + p["tokens_out"] * 10.0) / 1e6, abs=1e-6)
    assert est["cost"] == p["cost"] and est["unpriced"] == []
    assert remote.bodies == [] and scripts["spike-local"].requests == []
    local = client.post("/api/minds/estimate", json={"n": 2, "message": "hola", "mode": "core",
                                                     "provider_id": "spike-local"}).json()
    assert local["multiplier"] == 2 and local["cost"] is None and local["providers"][0]["local"]
    assert local["providers"][0]["calls"] == 2 and local["unpriced"] == []


def test_the_estimate_says_when_a_provider_has_no_price_and_when_a_plan_costs_more(env):
    client, *_ = env
    add_remote(client, limits={})
    est = client.post("/api/minds/estimate", json={"n": 2, "message": "hola", "provider_id": "openai",
                                                   "mode": "core"}).json()
    assert est["cost"] is None and est["unpriced"] == ["OpenAI"]
    plan = client.post("/api/minds/estimate", json={
        "n": 2, "provider_id": "openai",
        "message": "Plan a marketing campaign for an ETF and estimate the ROI of the investment"}).json()
    assert plan["multi_step"] is True and plan["providers"][0]["calls"] > 2


def test_the_guard_counts_n_calls_and_refuses_before_starting_when_the_limit_would_be_crossed(env):
    client, _, remote, scripts = env
    add_remote(client, limits={"price_in": 2.0, "price_out": 10.0, "monthly_tokens": 5000})
    refused = chat(client, {"n": 3}, provider_id="openai")  # 3 calls of up to ~2200 tokens: 6600 > 5000
    assert refused.status_code == 403
    assert "3 calls" in refused.json()["detail"] and "monthly limit" in refused.json()["detail"]
    assert remote.bodies == [] and client.get("/api/calls").json() == []  # nothing was sent, nothing was logged
    assert client.get("/api/conversations").json() == []  # not even the message was stored
    ok = chat(client, {"n": 2}, provider_id="openai")  # 2 calls: 4400 <= 5000
    assert ok.status_code == 200, ok.text
    assert len(remote.bodies) == 2
    log = client.get("/api/calls?remote=true").json()
    assert [c["status"] for c in log] == ["ok", "ok"]  # every one of the N calls went through the guard


def test_a_spending_limit_is_checked_in_money_too(env):
    client, *_ = env
    add_remote(client, limits={"price_in": 2.0, "price_out": 10.0, "monthly_cost": 0.04})
    # one call is up to ~2200 tokens in and out: 0.022; three would be 0.066 > 0.04, two 0.044 > 0.04
    assert chat(client, {"n": 2}, provider_id="openai").status_code == 403
    client.patch("/api/providers/openai", json={"limits": {"price_in": 2.0, "price_out": 10.0, "monthly_cost": 0.05}})
    assert chat(client, {"n": 2}, provider_id="openai").status_code == 200


def test_the_paid_call_permission_applies_to_the_batch(env):
    client, _, remote, _ = env
    add_remote(client, allow_paid=False)
    r = chat(client, {"n": 2}, provider_id="openai")
    assert r.status_code == 403 and "may bill your account" in r.json()["detail"]
    assert remote.bodies == [] and client.get("/api/conversations").json() == []
    est = client.post("/api/minds/estimate", json={"n": 2, "message": "hola", "provider_id": "openai", "mode": "core"})
    assert "may bill your account" in est.json()["blocked"]


def test_a_limit_reached_by_an_earlier_mind_stops_the_next_mind_at_its_own_call(env):
    """The estimate is not the only protection: the guard checks the limit again before each of the N calls."""
    client, _, remote, _ = env
    remote.usage = (7900, 200)  # the first call uses the whole limit, more than the estimate allowed for
    add_remote(client, limits={"price_in": 2.0, "price_out": 10.0, "monthly_tokens": 8000})
    r = chat(client, {"n": 2}, provider_id="openai")
    assert r.status_code == 200, r.text
    evs = events_of(r)
    assert len(remote.bodies) == 1  # the second mind's call was stopped before it was sent
    results = {e["mind"]: e for e in evs if e["type"] == "mind_result"}
    assert results[0]["ok"] and not results[1]["ok"] and "monthly limit is reached" in results[1]["error"]
    log = client.get("/api/calls?remote=true").json()
    assert sorted(c["status"] for c in log) == ["blocked", "ok"]
    assert evs[-1]["text"] == ANSWERS[0.7]  # the mind that did answer is the pick


def test_picked_providers_each_go_through_their_own_guard(env):
    client, _, remote, scripts = env
    add_remote(client, allow_paid=False)
    picks = {"picks": [{"provider_id": "spike-local"}, {"provider_id": "openai"}]}
    r = chat(client, picks)
    assert r.status_code == 403 and remote.bodies == [] and scripts["spike-local"].requests == []
    client.patch("/api/providers/openai", json={"allow_paid": True})
    evs = events_of(chat(client, picks))
    assert len(remote.bodies) == 1 and len(scripts["spike-local"].requests) == 1
    assert {e["mind"] for e in evs if e["type"] == "mind_result"} == {0, 1}
