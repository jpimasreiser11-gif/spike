"""EV8: prompt regression. A prompt version the user proposes is a candidate: it is compared with the version in use on
the local eval set (the questions made from saved corrections and fixed failures) with the deterministic scorer, and it
cannot become the version in use if it scores more than the tolerance below it. The verdict is kept in the version's
history and there is a rollback. No model is used: the answers come from stubs."""

import pytest

from spike.cli import main
from spike.evolution import checks, prompts
from spike.evolution.checks import run_checks
from spike.evolution.prompts import Scores, Variant
from spike.evolution.store import EvolutionStore
from tests.helpers import text
from tests.test_evolution import env as evolution_env
from tests.test_evolution_levels import QUESTIONS, RULE, accept, fake_answer, run

env = pytest.fixture(evolution_env.__wrapped__) if hasattr(evolution_env, "__wrapped__") else evolution_env

BAD = "Responde siempre en inglés."


def big_set(n: int = 50) -> list[dict]:
    return [{"id": f"q{i}", "question": f"q{i}", "checks": {"include": ["ok"], "exclude": []},
             "from": "failure" if i % 2 else "correction"} for i in range(n)]


async def breaks_what_it_names(q, variant):
    """Answers "ok" unless the variant has an instruction with the question's id (that is how a prompt 'breaks' it)."""
    return ("no" if q["id"] in variant.instructions else "ok"), None


def gate(ok, detail=""):
    return lambda: (ok, detail)


# ---------------------------------------------------------------- proposing a candidate
def test_a_proposed_candidate_is_stored_but_not_in_use(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    first = prompts.propose(store, "finance", [RULE, "  ", RULE.lower()], {"financial-ratio-analysis": "off"})
    assert not first["active"] and first["component"] == "prompt:finance"
    assert first["data"] == {"instructions": [RULE], "skills": {"financial-ratio-analysis": "off"}}
    assert first["report"] == {"status": "candidate", "source": "manual",
                               "changes": [f"add: {RULE}", "skill financial-ratio-analysis: off"]}
    assert first["reason"].startswith("candidate: add: ")
    assert prompts.active(store, "finance") == Variant() and store.active("prompt:finance") is None
    assert [v["id"] for v in prompts.pending(store, "finance")] == [first["id"]]
    assert prompts.pending(store, "medicine") == []


def test_a_candidate_starts_from_the_version_in_use(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    store.add_version("prompt:finance", Variant.of([RULE], {"a": "off", "b": "always"}).to_dict())
    candidate = prompts.propose(store, "finance", ["Cita la ley"], {"a": "auto", "c": "always"})
    assert candidate["data"] == Variant.of([RULE, "Cita la ley"], {"b": "always", "c": "always"}).to_dict()
    assert candidate["replaces"] == store.active("prompt:finance")["id"]
    assert prompts.active(store, "finance") == Variant.of([RULE], {"a": "off", "b": "always"})  # unchanged


def test_a_candidate_that_changes_nothing_or_is_malformed_is_refused(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    store.add_version("prompt:finance", Variant.of([RULE]).to_dict())
    with pytest.raises(ValueError, match="nothing to change"):
        prompts.propose(store, "finance", [RULE.upper()])
    with pytest.raises(ValueError, match="nothing to change"):
        prompts.propose(store, "finance", [], {})
    with pytest.raises(ValueError, match="skill mode must be one of always, off, auto, got 'maybe'"):
        prompts.propose(store, "finance", [], {"x": "maybe"})
    with pytest.raises(ValueError, match="at most 8 learned lines"):
        prompts.propose(store, "finance", [f"línea {i}" for i in range(8)])
    assert len(store.versions("prompt:finance")) == 1  # nothing was stored by the refused ones


# ---------------------------------------------------------------- the comparison and its tolerance
def test_the_tolerance_is_in_points_of_pass_rate_and_documented_in_the_report():
    assert prompts.TOLERANCE_POINTS == 2.0
    scores = Scores(big_set(50), breaks_what_it_names)
    one = run(prompts.compare(scores, Variant(), Variant.of(["q0"])))
    assert one["drop_points"] == 2.0 and one["ok"] and one["evaluated"]  # exactly at the tolerance: allowed
    assert one["baseline"]["passed"] == 50 and one["candidate"]["passed"] == 49 and one["lost"] == ["q0"]
    two = run(prompts.compare(scores, Variant(), Variant.of(["q0", "q1"])))
    assert two["drop_points"] == 4.0 and not two["ok"] and two["lost"] == ["q0", "q1"] and two["gained"] == []
    assert two["tolerance_points"] == 2.0 and two["origins"] == {"correction": 25, "failure": 25}
    wide = run(prompts.compare(scores, Variant(), Variant.of(["q0", "q1"]), tolerance=5.0))
    assert wide["ok"] and wide["tolerance_points"] == 5.0  # the limit is a parameter, not a constant buried in a test


def test_on_a_small_set_one_lost_question_is_already_beyond_the_tolerance():
    scores = Scores(big_set(10), breaks_what_it_names)
    lost = run(prompts.compare(scores, Variant(), Variant.of(["q3"])))
    assert lost["drop_points"] == 10.0 and not lost["ok"]
    better = run(prompts.compare(scores, Variant.of(["q3", "q4"]), Variant.of(["q4"])))
    assert better["drop_points"] == -10.0 and better["ok"] and better["gained"] == ["q3"] and better["lost"] == []
    same = run(prompts.compare(scores, Variant.of(["q3"]), Variant.of(["q3", "ignored"])))
    assert same["drop_points"] == 0.0 and same["ok"]


def test_fewer_than_three_questions_cannot_tell_a_better_prompt_from_luck():
    for n in (0, 2):
        report = run(prompts.compare(Scores(big_set(n), breaks_what_it_names), Variant(), Variant.of(["q0"])))
        assert not report["evaluated"] and not report["ok"] and report["questions"] == n
        assert f"only {n} accepted eval questions" in report["reason"] and "accept at least 3" in report["reason"]
        assert prompts.verdict_text(report) == report["reason"]
    assert run(prompts.compare(Scores(big_set(3), breaks_what_it_names), Variant(), Variant()))["ok"]


def test_each_version_is_scored_once_per_set():
    calls = []

    async def counting(q, variant):
        calls.append((q["id"], variant))
        return "ok", None

    scores = Scores(big_set(3), counting)
    run(prompts.compare(scores, Variant(), Variant.of(["x"])))
    run(prompts.compare(scores, Variant(), Variant.of(["y"])))  # the baseline is not scored again
    assert len(calls) == 9


def test_the_set_is_the_accepted_questions_with_checks_of_the_specialist(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store, questions=QUESTIONS[:2])
    store.add("candidate", {"question": "de un fallo", "specialist": "finance", "checks": {"include": ["x"]},
                            "from": "failure"}, status="accepted")
    store.add("candidate", {"question": "sin checks", "specialist": "finance", "checks": {}, "from": "failure"},
              status="accepted")
    store.add("candidate", {"question": "pendiente", "specialist": "finance", "checks": {"include": ["x"]},
                            "from": "failure"}, status="proposed")
    accept(store, specialist="medicine", questions=QUESTIONS[2:])
    questions = prompts.eval_set(store, "finance")
    assert len(questions) == 3
    origins = run(prompts.compare(Scores(questions, fake_answer({}, set())), Variant(), Variant()))["origins"]
    assert origins == {"correction": 2, "failure": 1}


# ---------------------------------------------------------------- activating
def test_a_candidate_within_the_tolerance_becomes_the_version_in_use_and_rolls_back(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store)
    answer = fake_answer({RULE: {0, 1, 2}}, base={3})
    before = store.add_version("prompt:finance", Variant.of(["Sé breve"]).to_dict(), reason="mine")
    candidate = prompts.propose(store, "finance", [RULE])
    report = run(prompts.activate(store, "finance", None, answer, gate(True)))
    assert report["activated"] and report["ok"] and report["version"] == candidate["id"]
    assert report["baseline"]["passed"] == 1 and report["candidate"]["passed"] == 4 and report["drop_points"] == -75.0
    now = store.active("prompt:finance")
    assert now["id"] == candidate["id"] and now["replaces"] == before["id"]
    assert prompts.active(store, "finance") == Variant.of(["Sé breve", RULE])
    assert now["report"]["status"] == "activated" and now["report"]["regression"]["against"] == before["id"]
    assert now["reason"].startswith("activated after the check: 4/4 eval questions against 1/4 for the version in use")
    assert prompts.pending(store, "finance") == []
    assert store.rollback("prompt:finance")["id"] == before["id"]  # the history says what to go back to
    assert prompts.active(store, "finance") == Variant.of(["Sé breve"])


def test_a_candidate_that_scores_lower_is_blocked_and_the_verdict_is_kept(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store)
    answer = fake_answer({BAD: {-4}}, base={0, 1, 2, 3})  # the candidate's line breaks question 4
    candidate = prompts.propose(store, "finance", [BAD])
    report = run(prompts.activate(store, "finance", candidate["id"], answer, gate(True)))
    assert not report["activated"] and report["drop_points"] == 25.0 and report["lost"]
    kept = store.version(candidate["id"])
    assert not kept["active"] and store.active("prompt:finance") is None and prompts.active(store, "finance") == Variant()
    assert kept["report"]["status"] == "blocked" and kept["report"]["regression"]["drop_points"] == 25.0
    assert kept["report"]["regression"]["against"] is None  # it was compared with the built-in prompt
    assert kept["reason"] == "blocked: 3/4 eval questions against 4/4 for the version in use (-25.0 points, tolerance -2)"
    assert prompts.pending(store, "finance") == []  # a blocked one is not offered again, but stays in the history
    assert [v["id"] for v in store.versions("prompt:finance")] == [candidate["id"]]
    with pytest.raises(LookupError, match="no candidate prompt version for finance"):
        run(prompts.activate(store, "finance", None, answer))


def test_a_candidate_is_blocked_by_the_other_regression_checks_even_if_it_scores_higher(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store)
    candidate = prompts.propose(store, "finance", [RULE])
    report = run(prompts.activate(store, "finance", None, fake_answer({RULE: {0, 1, 2}}, {3}),
                                  gate(False, "router 0.50 < 0.85")))
    assert not report["activated"] and report["reason"] == "regression checks failed: router 0.50 < 0.85"
    kept = store.version(candidate["id"])
    assert not kept["active"] and kept["report"]["status"] == "blocked"
    assert kept["reason"] == "blocked: regression checks failed: router 0.50 < 0.85"


def test_a_candidate_with_too_few_questions_is_blocked_not_trusted(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store, questions=QUESTIONS[:2])
    candidate = prompts.propose(store, "finance", [RULE])
    report = run(prompts.activate(store, "finance", None, fake_answer({RULE: {0, 1}}, set()), gate(True)))
    assert not report["activated"] and not report["evaluated"] and "only 2 accepted eval questions" in report["reason"]
    assert store.version(candidate["id"])["report"]["status"] == "blocked" and store.active("prompt:finance") is None


def test_activate_refuses_what_is_not_a_candidate_of_that_specialist(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store)
    answer = fake_answer({RULE: {0, 1, 2}}, {3})
    with pytest.raises(LookupError, match="no candidate prompt version for finance"):
        run(prompts.activate(store, "finance", None, answer))
    other = prompts.propose(store, "medicine", ["Cita la guía"])
    with pytest.raises(LookupError, match="with id"):
        run(prompts.activate(store, "finance", other["id"], answer))
    with pytest.raises(LookupError, match="with id 99"):
        run(prompts.activate(store, "finance", 99, answer))
    mine = prompts.propose(store, "finance", [RULE])
    assert run(prompts.activate(store, "finance", mine["id"], answer))["activated"]
    with pytest.raises(ValueError, match=f"v{mine['id']} is already in use"):
        run(prompts.activate(store, "finance", mine["id"], answer))


def test_the_newest_pending_candidate_is_the_one_activated_by_default(tmp_path):
    store = EvolutionStore(tmp_path / "e.db")
    accept(store)
    older = prompts.propose(store, "finance", ["Una línea"])
    newer = prompts.propose(store, "finance", [RULE])
    assert [v["id"] for v in prompts.pending(store, "finance")] == [newer["id"], older["id"]]
    report = run(prompts.activate(store, "finance", None, fake_answer({RULE: {0, 1, 2}}, {3}), gate(True)))
    assert report["version"] == newer["id"]
    assert [v["id"] for v in prompts.pending(store, "finance")] == [older["id"]]


# ---------------------------------------------------------------- in `spike evolve check`
def test_the_check_compares_the_version_in_use_and_each_candidate(env):
    _, state, _, _ = env
    store = state.evolution.store
    accept(store)
    answer = fake_answer({RULE: {0, 1, 2}, BAD: {-4}}, base={3})
    assert run(checks.prompts_check(state, answer))["detail"] == "no learned or candidate prompt versions to compare"

    store.add_version("prompt:finance", Variant.of([RULE]).to_dict(), reason="in use")
    good = prompts.propose(store, "finance", ["Una línea más"])
    worse = prompts.propose(store, "finance", [BAD])
    result = run(checks.prompts_check(state, answer))
    assert result["name"] == "prompts" and not result["ok"]
    by = {r["version"]: r for r in result["results"]}
    assert by[store.active("prompt:finance")["id"]]["what"] == "in use" and by[store.active("prompt:finance")["id"]]["ok"]
    assert by[good["id"]]["ok"] and by[good["id"]]["what"] == "candidate" and by[good["id"]]["drop_points"] == 0.0
    assert not by[worse["id"]]["ok"] and by[worse["id"]]["drop_points"] == 25.0
    assert result["detail"].startswith(f"finance candidate v{worse['id']}: 3/4 eval questions against 4/4")
    # the verdicts are written to the versions' history; nothing was activated by the check
    assert store.version(good["id"])["report"]["status"] == "candidate" and not store.version(good["id"])["active"]
    assert "can be activated" in store.version(good["id"])["reason"]
    assert store.version(worse["id"])["report"]["status"] == "blocked"
    assert store.active("prompt:finance")["reason"] == "in use"


def test_the_version_in_use_must_not_score_below_the_built_in_prompt(env):
    _, state, _, _ = env
    accept(state.evolution.store)
    state.evolution.store.add_version("prompt:finance", Variant.of([BAD]).to_dict())
    result = run(checks.prompts_check(state, fake_answer({BAD: {-1, -2}}, base={0, 1, 2, 3})))
    [row] = result["results"]
    assert not result["ok"] and row["what"] == "in use" and row["drop_points"] == 50.0
    assert "finance in use v1: 2/4" in result["detail"]


def test_run_checks_adds_the_prompt_comparison_only_when_asked(env):
    _, state, _, _ = env
    assert [c["name"] for c in run(run_checks(state))["checks"]] == ["router", "catalog", "skills", "adapters", "strategy"]
    report = run(run_checks(state, prompt_versions=True, prompt_answer=fake_answer({}, set())))
    assert [c["name"] for c in report["checks"]][-1] == "prompts" and report["ok"]
    both = run(run_checks(state, replay=True, prompt_versions=True, answer=None, prompt_answer=fake_answer({}, set())))
    assert [c["name"] for c in both["checks"]][-2:] == ["prompts", "replay"]


# ---------------------------------------------------------------- over HTTP
def test_the_app_proposes_checks_and_activates_a_candidate(env):
    client, state, local, _ = env
    accept(state.evolution.store)
    local._script = lambda request: text("Depende del caso." if BAD in request.messages[0].content or
                                         RULE not in request.messages[0].content else "El tipo es del 21 %.")
    assert client.post("/api/evolution/prompts/nope/candidate", json={"instructions": [RULE]}).status_code == 400
    assert client.post("/api/evolution/prompts/finance/candidate", json={"skills": {"x": "maybe"}}).status_code == 400
    assert client.post("/api/evolution/prompts/finance/candidate", json={}).status_code == 400  # nothing to change
    assert client.post("/api/evolution/prompts/finance/activate", json={}).status_code == 404  # no candidate yet

    made = client.post("/api/evolution/prompts/finance/candidate", json={"instructions": [RULE]}).json()
    assert not made["active"] and made["report"]["status"] == "candidate"
    listing = {s["specialist"]: s for s in client.get("/api/evolution/prompts").json()}
    assert listing["finance"]["candidate"]["id"] == made["id"] and listing["finance"]["active"] is None
    assert listing["medicine"]["candidate"] is None

    done = client.post("/api/evolution/prompts/finance/activate", json={"version": made["id"]})
    assert done.status_code == 200 and done.json()["activated"] and done.json()["candidate"]["passed"] == 4
    assert not state.optimizing
    listing = {s["specialist"]: s for s in client.get("/api/evolution/prompts").json()}
    assert listing["finance"]["active"]["id"] == made["id"] and listing["finance"]["candidate"] is None

    worse = client.post("/api/evolution/prompts/finance/candidate", json={"instructions": [BAD]}).json()
    blocked = client.post("/api/evolution/prompts/finance/activate", json={}).json()
    assert not blocked["activated"] and blocked["version"] == worse["id"] and blocked["drop_points"] == 100.0
    listing = {s["specialist"]: s for s in client.get("/api/evolution/prompts").json()}
    assert listing["finance"]["active"]["id"] == made["id"]  # still the good one
    assert listing["finance"]["candidate"]["id"] == worse["id"] and listing["finance"]["candidate"]["report"][
        "status"] == "blocked"

    assert client.post("/api/evolution/prompts/finance/activate", json={"version": 999}).status_code == 404
    assert client.post("/api/evolution/prompts/finance/activate", json={"version": made["id"]}).status_code == 400
    state.optimizing = True
    assert client.post("/api/evolution/prompts/finance/activate", json={}).status_code == 409
    state.optimizing = False
    assert client.post("/api/evolution/rollback", json={"component": "prompt:finance"}).json()["active"] is None
    assert state.evolution.store.active("prompt:finance") is None


def test_the_check_endpoint_compares_prompts_when_asked(env):
    client, state, local, _ = env
    accept(state.evolution.store)
    state.evolution.store.add_version("prompt:finance", Variant.of([RULE]).to_dict())
    local._script = lambda request: text("El tipo es del 21 %." if RULE in request.messages[0].content
                                         else "Depende del caso.")
    names = [c["name"] for c in client.post("/api/evolution/check", json={}).json()["checks"]]
    assert "prompts" not in names
    report = client.post("/api/evolution/check", json={"prompts": True}).json()
    prompts_check = next(c for c in report["checks"] if c["name"] == "prompts")
    assert report["ok"] and prompts_check["ok"] and prompts_check["results"][0]["what"] == "in use"
    assert prompts_check["results"][0]["candidate"]["passed"] == 4 and prompts_check["results"][0]["baseline"][
        "passed"] == 0


# ---------------------------------------------------------------- the command line
def test_the_cli_proposes_checks_activates_and_rolls_back(env, capsys, monkeypatch):
    _, state, _, _ = env
    accept(state.evolution.store)
    scripted = fake_answer({RULE: {0, 1, 2}, BAD: {-4}}, base={3})

    async def fake(state_, q, specialist, variant):
        assert specialist == "finance"
        return await scripted(q, variant)

    monkeypatch.setattr(checks, "answer_with_variant", fake)
    assert main(["evolve", "candidate"]) == 2 and "name the specialist" in capsys.readouterr().err
    assert main(["evolve", "activate"]) == 2 and "name the specialist" in capsys.readouterr().err
    assert main(["evolve", "candidate", "finance", "--try", RULE, "--skill", "financial-ratio-analysis=off"]) == 0
    out = capsys.readouterr().out
    assert "Candidate prompt v1 for finance" in out and "It changes nothing yet" in out
    assert state.evolution.store.active("prompt:finance") is None

    assert main(["evolve", "check", "--prompts"]) == 1  # the skill mode 'off' makes every answer fail in fake_answer
    out = capsys.readouterr().out
    assert "FAIL prompts" in out and "fail finance candidate v1: 0/4 eval questions against 1/4" in out
    assert main(["evolve", "check"]) == 0 and "prompts" not in capsys.readouterr().out

    assert main(["evolve", "candidate", "finance", "--try", "Una línea", "--skill", "financial-ratio-analysis=auto"]) == 0
    capsys.readouterr()
    assert main(["evolve", "activate", "finance", "--version", "2"]) == 0
    out = capsys.readouterr().out
    assert "v2: 1/4 eval questions against 1/4 for the version in use (+0.0 points, tolerance -2)" in out
    assert "Activated: now in use" in out
    assert "spike evolve rollback prompt:finance" in out
    assert state.evolution.store.active("prompt:finance")["id"] == 2

    assert main(["evolve", "candidate", "finance", "--try", BAD]) == 0
    capsys.readouterr()
    assert main(["evolve", "activate", "finance"]) == 1
    assert "Blocked, nothing changed" in capsys.readouterr().out
    assert state.evolution.store.active("prompt:finance")["id"] == 2
    assert main(["evolve", "rollback", "prompt:finance"]) == 0
    assert "back to the built-in version" in capsys.readouterr().out
    assert state.evolution.store.active("prompt:finance") is None


def test_the_cli_refuses_an_unknown_specialist_or_a_candidate_that_changes_nothing(env, capsys):
    assert main(["evolve", "candidate", "nope", "--try", RULE]) == 1
    assert "error: unknown specialist 'nope'" in capsys.readouterr().err
    assert main(["evolve", "candidate", "finance"]) == 1 and "nothing to change" in capsys.readouterr().err
    assert main(["evolve", "activate", "finance"]) == 1 and "no candidate prompt version" in capsys.readouterr().err
