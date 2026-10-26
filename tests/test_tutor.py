"""Tutor progress: the SM-2 schedule, mastery, due topics in the Education specialist's prompt (and nobody else's),
the study tools and the API."""

import pytest
from fastapi.testclient import TestClient

from spike.memory.service import Recall, scopes_for
from spike.memory.store import GLOBAL, MemoryStore
from spike.memory.tools import StudyReview, StudyTopics
from spike.memory.tutor import DAY, MIN_EASE, Tutor, TutorError, schedule, tutor_section
from spike.orchestrator.orchestrator import OrchestratorOptions
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text
from tests.test_memory import no_embedder

T0 = 1_800_000_000.0


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self) -> float:
        return self.now

    def days(self, n: float) -> None:
        self.now += n * DAY


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    yield s
    s.close()


@pytest.fixture
def tutor(store, clock):
    return Tutor(store, clock)


def test_sm2_intervals_and_ease_follow_the_published_rule():
    # grade 4 every time: 1 day, 6 days, then the interval times the ease (2.5, unchanged by a 4)
    rep, interval, ease = 0, 0, 2.5
    seen = []
    for _ in range(5):
        rep, interval, ease = schedule(rep, interval, ease, 4)
        seen.append(interval)
    assert seen == [1, 6, 15, 38, 95] and rep == 5 and ease == pytest.approx(2.5)
    # a perfect answer raises the ease by 0.1; a 3 lowers it by 0.14; the floor is 1.3
    assert schedule(1, 1, 2.5, 5) == (2, 6, pytest.approx(2.6))
    assert schedule(2, 6, 2.5, 3)[2] == pytest.approx(2.36)
    assert schedule(3, 15, 1.35, 3)[2] == MIN_EASE
    # the third success uses the new ease: 6 x 2.6 = 15.6 -> 16
    assert schedule(2, 6, 2.5, 5) == (3, 16, pytest.approx(2.6))
    # forgetting (below 3) starts again: repetitions 0, one day, ease untouched
    assert schedule(4, 38, 2.2, 2) == (0, 1, 2.2) and schedule(4, 38, 2.2, 0) == (0, 1, 2.2)
    for bad in (-1, 6):
        with pytest.raises(TutorError):
            schedule(0, 0, 2.5, bad)


def test_a_new_topic_is_due_at_once_and_the_review_schedules_the_next_one(tutor, clock):
    topic = tutor.add("Derivadas parciales")
    assert topic.mastery == 0 and topic.due(clock.now) and [t.id for t in tutor.due([GLOBAL])] == [topic.id]
    reviewed = tutor.review(topic.id, 4)
    assert (reviewed.mastery, reviewed.interval_days, reviewed.reviews, reviewed.last_quality) == (1, 1, 1, 4)
    assert reviewed.next_review == pytest.approx(T0 + DAY) and reviewed.last_review == T0
    assert tutor.due([GLOBAL]) == []
    clock.days(0.9)
    assert tutor.due([GLOBAL]) == []
    clock.days(0.2)
    assert [t.id for t in tutor.due([GLOBAL])] == [topic.id]
    assert tutor.review(topic.id, 4).interval_days == 6  # the second success
    assert tutor.review(topic.id, 1).mastery == 0  # forgotten: back to the start...
    after = tutor.get(topic.id)
    assert (after.interval_days, after.lapses, after.reviews, after.ease) == (1, 1, 3, pytest.approx(2.5))


def test_mastery_counts_passes_in_a_row_up_to_five(tutor):
    topic = tutor.add("Integrales")
    levels = [tutor.review(topic.id, 4).mastery for _ in range(7)]
    assert levels == [1, 2, 3, 4, 5, 5, 5]
    assert tutor.review(topic.id, 3).mastery == 5 and tutor.review(topic.id, 2).mastery == 0
    with pytest.raises(TutorError):
        tutor.review(topic.id, 6)
    with pytest.raises(TutorError):
        tutor.review(topic.id, True)
    assert tutor.review("nope", 4) is None


def test_a_starting_level_is_scheduled_as_if_it_had_been_passed(tutor, clock):
    known = tutor.add("Álgebra lineal", mastery=3)
    assert (known.mastery, known.interval_days) == (3, 15) and known.next_review == pytest.approx(T0 + 15 * DAY)
    assert tutor.due([GLOBAL]) == []
    assert tutor.review(known.id, 4).interval_days == 38  # the schedule goes on from there
    for bad in (-1, 6, "2", True):
        with pytest.raises(TutorError):
            tutor.add("Otro", mastery=bad)


def test_topics_are_unique_per_scope_and_found_by_name(tutor):
    a = tutor.add("Cálculo", scope="project:p1")
    g = tutor.add("Cálculo")
    with pytest.raises(TutorError, match="already"):
        tutor.add("calculo")
    assert tutor.find("CALCULO", ["project:p1", GLOBAL]).id == a.id and tutor.find("calculo", [GLOBAL]).id == g.id
    assert tutor.find("física", [GLOBAL]) is None
    assert tutor.rename(g.id, notes="capítulo 3").notes == "capítulo 3"
    with pytest.raises(TutorError):
        tutor.rename(g.id, name="")
    for bad in ("", "  ", "x" * 201):
        with pytest.raises(TutorError):
            tutor.add(bad)
    assert tutor.delete_scope("project:p1") == 1 and tutor.get(a.id) is None and tutor.delete(g.id)


def test_due_topics_come_most_overdue_first_and_only_from_the_chats_scopes(tutor, clock):
    old = tutor.add("Viejo")
    tutor.review(old.id, 4)
    clock.days(3)
    mid = tutor.add("Medio", scope="project:p1")
    tutor.add("Otro proyecto", scope="project:p2")
    clock.days(1)
    assert [t.name for t in tutor.due(["project:p1", GLOBAL])] == ["Viejo", "Medio"]
    assert [t.name for t in tutor.due([GLOBAL], limit=1)] == ["Viejo"] and mid.scope == "project:p1"


def test_the_prompt_block_names_what_is_due_within_its_budget(tutor, clock):
    assert tutor_section([], clock.now) == ""
    seen = tutor.add("Límites")
    tutor.review(seen.id, 4)
    tutor.review(seen.id, 4)
    tutor.add("Derivadas", notes="empezar por la definición")
    clock.days(10)
    block = tutor_section(tutor.due([GLOBAL]), clock.now)
    assert block.startswith("# Study progress") and "study_review" in block
    assert "- Límites: mastery 2/5, last reviewed 10 days ago, 4 days overdue" in block
    assert "- Derivadas: new, never reviewed (empezar por la definición)" in block
    for i in range(40):
        tutor.add(f"Tema {i} " + "largo " * 10)
    small = tutor_section(tutor.due([GLOBAL], limit=50), clock.now, budget_tokens=120)
    assert len(small) // 4 <= 130 and small.count("\n- ") < 10


# ------------------------------------------------------------------------------------------- the specialists
def test_only_the_education_specialist_sees_the_study_schedule(tmp_path):
    state = AppState(home=tmp_path)
    topic = state.memory.tutor.add("Probabilidad condicionada")
    opts = OrchestratorOptions(memory=Recall(due=state.memory.tutor.due([GLOBAL])))
    orchestrator = state.orchestrator()
    teacher = orchestrator.system_prompt(state.catalog.specialists["education"], opts)
    assert "# Study progress" in teacher and "Probabilidad condicionada" in teacher
    for other in ("core", "math", "writing"):
        assert "# Study progress" not in orchestrator.system_prompt(state.catalog.specialists[other], opts)
    assert "# Study progress" not in orchestrator.system_prompt(state.catalog.specialists["education"],
                                                                 OrchestratorOptions())
    education_tools = state.catalog.specialists["education"].tools
    assert "study_review" in education_tools and "study_topics" in education_tools
    assert state.tools.get("study_review").default_policy == "ask" and state.tools.get("study_topics").default_policy == "allow"
    assert topic.id


async def test_study_tools_list_topics_and_record_reviews(store, clock, tmp_path):
    state = AppState(home=tmp_path)
    memory = state.memory
    topics, review = StudyTopics(memory, None), StudyReview(memory, "p1")
    assert (await topics.run({})).content == "no topics yet"
    first = await review.run({"topic": "Ley de Ohm", "grade": 4})  # not listed yet: added, in the project
    assert first.ok and first.content == "Ley de Ohm: mastery 1/5, next review in 1 day"
    assert memory.tutor.find("ley de ohm", ["project:p1"]).scope == "project:p1"
    assert (await review.run({"topic": "ley de ohm", "grade": 4})).content.endswith("next review in 6 days")
    assert (await review.run({"topic": "Ley de Ohm", "grade": 1})).content == "Ley de Ohm: mastery 0/5, next review in 1 day"
    bad = await review.run({"topic": "Ley de Ohm", "grade": 9})
    assert not bad.ok and "0 to 5" in bad.content and not (await review.run({"topic": " ", "grade": 3})).ok
    listing = await StudyTopics(memory, "p1").run({})
    assert listing.content == "- Ley de Ohm: mastery 0/5, next review in 1 day"
    assert (await StudyTopics(memory, "p1").run({"due_only": True})).content == "nothing is due"
    assert (await topics.run({})).content == "no topics yet"  # the global chat does not see the project's topics
    assert scopes_for("p1")[0] == "project:p1"


# ------------------------------------------------------------------------------------------- API and chats
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    state.memory.get_embedder = no_embedder
    with TestClient(create_app(state)) as client:
        yield client, state, local


def test_tutor_api_adds_reviews_and_reports_what_is_due(api):
    client, state, _ = api
    pid = client.post("/api/projects", json={"name": "Curso"}).json()["id"]
    made = client.post("/api/tutor", json={"name": "Fracciones"}).json()
    assert made["mastery"] == 0 and made["due"] is True and made["scope"] == "global"
    assert client.post("/api/tutor", json={"name": "fracciones"}).status_code == 400
    assert client.post("/api/tutor", json={"name": "X", "scope": "project:nope"}).status_code == 400
    assert client.post("/api/tutor", json={"name": "Y", "mastery": 9}).status_code == 400
    client.post("/api/tutor", json={"name": "Decimales", "scope": f"project:{pid}", "mastery": 2})
    listed = client.get("/api/tutor").json()
    assert listed["due"] == 1 and [t["name"] for t in listed["topics"]] == ["Fracciones", "Decimales"]
    assert client.get(f"/api/tutor?scope=project:{pid}&due=true").json()["topics"] == []
    done = client.post(f"/api/tutor/{made['id']}/review", json={"grade": 5}).json()
    assert (done["mastery"], done["interval_days"], done["due"], done["ease"]) == (1, 1, False, 2.6)
    assert client.get("/api/tutor").json()["due"] == 0
    assert client.post(f"/api/tutor/{made['id']}/review", json={"grade": 6}).status_code == 422
    assert client.post("/api/tutor/nope/review", json={"grade": 4}).status_code == 404
    assert client.patch(f"/api/tutor/{made['id']}", json={"notes": "repasar"}).json()["notes"] == "repasar"
    assert client.patch("/api/tutor/nope", json={"name": "z"}).status_code == 404
    assert client.delete(f"/api/tutor/{made['id']}").json() == {"ok": True}
    assert client.delete(f"/api/tutor/{made['id']}").status_code == 404
    client.delete(f"/api/projects/{pid}")
    assert client.get("/api/tutor").json()["topics"] == []  # the project's topics went with it


def test_the_tutor_chat_carries_due_topics_and_can_record_a_review(api):
    client, state, local = api
    client.post("/api/tutor", json={"name": "Teorema de Pitágoras"})
    local._script = [text("Vamos a repasar.")]
    client.post("/api/chat", json={"message": "Quiero repasar lo que estudio", "mode": "education"})
    system = local.requests[-1].messages[0].content
    assert "# Study progress" in system and "Teorema de Pitágoras: new, never reviewed" in system
    local._script = [text("Sin deberes.")]
    client.post("/api/chat", json={"message": "Quiero repasar lo que estudio", "mode": "core"})
    assert "# Study progress" not in local.requests[-1].messages[0].content

    state.update_settings({"tool_policies": {"study_review": "allow"}})
    local._script = [call("study_review", {"topic": "Teorema de Pitágoras", "grade": 4}), text("Anotado.")]
    client.post("/api/chat", json={"message": "Lo he sabido bien", "mode": "education"})
    topic = client.get("/api/tutor").json()["topics"][0]
    assert (topic["mastery"], topic["reviews"], topic["last_quality"], topic["due"]) == (1, 1, 4, False)
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "Seguimos", "mode": "education"})
    assert "# Study progress" not in local.requests[-1].messages[0].content  # nothing is due now


def test_nothing_study_related_reaches_a_temporary_chat(api):
    client, state, local = api
    client.post("/api/tutor", json={"name": "Trigonometría"})
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "repasemos", "mode": "education", "temporary": True})
    assert "# Study progress" not in local.requests[-1].messages[0].content
