"""Trustworthy answers: the text matching, the citation inspector, the claim labels and the model pass that may only
lower them. The run's events are written by hand, as the orchestrator yields them; nothing here calls a model."""

import json

import pytest

from spike.core.types import StreamEvent
from spike.memory.service import Recall
from spike.memory.store import Hit, Memory
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import default_registry
from spike.trust.citations import inspect, marked_refs
from spike.trust.claims import (
    Claim,
    Report,
    analyse,
    apply_downgrades,
    parse_downgrades,
    split_claims,
)
from spike.trust.evidence import Evidence, key
from spike.trust.match import (
    Doc,
    find_fragment,
    fold,
    names,
    number_values,
    numbers,
    support,
)
from tests.helpers import ScriptedProvider, call, text

NOTES = "El cliente Norte paga a 60 días.\nLos demás clientes pagan a 30 días.\nEl descuento por pronto pago es del 2 %."


def run_events(*calls) -> list[dict]:
    """tool_call + tool_result events for (name, arguments, result[, ok])."""
    events = []
    for i, (name, args, result, *ok) in enumerate(calls, 1):
        events.append({"type": "tool_call", "id": f"c{i}", "name": name, "arguments": args})
        events.append({"type": "tool_result", "id": f"c{i}", "name": name, "ok": ok[0] if ok else True,
                       "content": result[:4000], **({"full": result} if len(result) > 4000 else {})})
    return events


def evidence_of(events=(), user="", recall=None) -> Evidence:
    ev = Evidence(user, recall)
    for e in events:
        ev.see(e)
    return ev


def labels(answer: str, ev: Evidence) -> dict[str, tuple[str, str]]:
    return {c.text: (c.label, c.why) for c in analyse(answer, ev).claims}


def label_of(sentence: str, ev: Evidence) -> tuple[str, str]:
    """(label, rule) of an answer that is one sentence."""
    return labels(sentence, ev)[sentence]


# ------------------------------------------------------------------------------------------------ matching
def test_two_spellings_of_a_text_fold_to_the_same_words():
    assert fold("  El «Cliente”  NORTE – paga a 60  días ") == fold('el "cliente" norte - paga a 60 dias')
    assert fold("**negrita** y `código`").split() == ["negrita", "y", "codigo"]


@pytest.mark.parametrize("a, b", [("1.200", "1200"), ("1,200", "1200"), ("12,5", "12.5"), ("1.234,5", "1,234.5"),
                                  ("0,50", "0.5"), ("1.234.567", "1,234,567")])
def test_the_same_number_written_two_ways_is_the_same_number(a, b):
    assert number_values(a) & number_values(b)


@pytest.mark.parametrize("a, b", [("1.200", "1.300"), ("12,5", "125"), ("21", "12"), ("1.234,5", "1.234,6")])
def test_different_numbers_do_not_match(a, b):
    assert not number_values(a) & number_values(b)


def test_numbers_and_names_are_found_in_a_sentence():
    assert [n.raw for n in numbers("Con 50.000 € y 1.200 inversores, el 12 % el 2026-10-26")] == [
        "50.000", "1.200", "12", "2026", "10", "26"]
    found = names("Según notas.md, el cliente Norte de IVA usa Python y ZX-ALBATROS-9931 en https://x.es/a")
    assert set(found) == {"https://x.es/a", "notas.md", "Norte", "IVA", "Python", "ZX-ALBATROS-9931"}
    assert names("El cliente paga a plazos.") == []  # the capital that starts a sentence is not a name


def test_a_quote_is_found_whatever_its_case_quotes_or_spaces():
    doc = Doc(NOTES)
    quotes = ("el cliente norte paga a 60 días", "El  cliente   Norte\npaga a 60 dias", "“El cliente Norte paga a 60 días.”")
    for quote in quotes:
        found = find_fragment(quote, doc)
        assert found and found.ok and found.ratio == 1.0


def test_a_quote_with_a_typo_is_found_by_similarity_but_one_with_another_number_or_name_is_not():
    doc = Doc(NOTES)
    typo = find_fragment("El cliente Norte paga a 60 dís", doc)
    assert typo and typo.ok and typo.ratio < 1.0
    assert not find_fragment("El cliente Norte paga a 90 días", doc).ok  # another number is not a typo
    assert not find_fragment("El cliente Sur paga a 60 días", doc).ok  # nor is another name
    assert not find_fragment("El cliente Norte nunca paga a tiempo", doc).ok


def test_an_ellipsis_in_a_quote_skips_text_but_keeps_the_order():
    doc = Doc(NOTES)
    assert find_fragment("El cliente Norte paga ... descuento por pronto pago es del 2 %", doc).ok
    assert not find_fragment("descuento por pronto pago es del 2 % ... El cliente Norte paga", doc).ok


def test_support_needs_the_numbers_and_names_of_the_claim():
    assert support("El cliente Norte paga a 60 días", NOTES).ok
    changed = support("El cliente Norte paga a 90 días", NOTES)
    assert not changed.ok and changed.score == 0.0 and changed.missing == ["90"]
    other = support("El cliente Sur paga a 60 días", NOTES)
    assert not other.ok and other.missing == ["Sur"]
    assert not support("El clima de Madrid es soleado en verano", NOTES).ok  # no words in common
    assert support("la IVA del 21 %", "salio 21").ok is False  # 'IVA' is an acronym and must be there ...
    assert support("la IVA del 21 %", "salio 21", acronyms=False).missing == []  # ... except in a tool's output


# ------------------------------------------------------------------------------------------------ the inspector
def notes_evidence() -> Evidence:
    return evidence_of(run_events(("read_file", {"path": "notas.md"}, NOTES)))


def test_a_correct_citation_passes():
    ev = notes_evidence()
    found, _ = inspect("Según notas.md, «el cliente Norte paga a 60 días».", ev.sources)
    assert len(found) == 1 and found[0].ok and found[0].how == "cue" and found[0].found == 1.0
    assert "60 días" in found[0].fragment
    marked, _ = inspect("El cliente Norte paga a 60 días [fuente: notas.md].", ev.sources)
    assert len(marked) == 1 and marked[0].ok and marked[0].how == "marked"


def test_a_fabricated_fragment_is_caught():
    ev = notes_evidence()
    found, _ = inspect("Según notas.md, «el cliente Norte nunca paga a tiempo y debe dinero».", ev.sources)
    assert [(c.status, c.source) for c in found] == [("no_fragment", "s1")]
    assert found[0].found < 0.85


def test_a_fabricated_source_is_caught():
    ev = notes_evidence()
    found, _ = inspect("El cliente Norte paga a 60 días [fuente: informe-final.pdf].", ev.sources)
    assert [(c.status, c.ref) for c in found] == [("no_source", "informe-final.pdf")]
    assert not marked_refs("sin marcas") and marked_refs("(source: a.md, p. 3; b.md · 2026-01-02)") == ["a.md", "b.md"]


def test_a_changed_number_fails_support():
    ev = notes_evidence()
    found, _ = inspect("Según notas.md, el cliente Norte paga a 90 días.", ev.sources)
    assert len(found) == 1 and found[0].status == "unsupported" and found[0].missing == ["90"] and found[0].score == 0.0
    quote, _ = inspect("Según notas.md, «el cliente Norte paga a 60 días», pero a 90 días en agosto.", ev.sources)
    assert quote[0].status == "unsupported" and quote[0].missing == ["90"]


def test_a_quote_found_in_a_source_counts_as_citing_it_and_one_found_nowhere_is_not_judged():
    ev = notes_evidence()
    implicit, _ = inspect('En el archivo se lee "los demás clientes pagan a 30 días" sin más.', ev.sources)
    assert len(implicit) == 1 and implicit[0].how == "quote" and implicit[0].ok and implicit[0].label == "notas.md"
    nowhere, _ = inspect('Como dijo alguien, "la fortuna favorece a los audaces siempre".', ev.sources)
    assert nowhere == []
    short, _ = inspect('Lo llaman "pronto pago" en el contrato.', ev.sources)
    assert short == []  # a term in quotes is not a quotation


def test_naming_a_file_is_not_citing_it_but_a_cue_is():
    ev = evidence_of(run_events(("write_file", {"path": "informe.md", "content": "Base 120 €, IVA 25,20 €."}, "ok")))
    assert inspect("He guardado el resumen en informe.md.", ev.sources)[0] == []
    described, _ = inspect("El archivo informe.md contiene un resumen muy largo del trabajo.", ev.sources)
    assert described == []  # a file the model wrote is not judged
    cited, _ = inspect("Según informe.md, el IVA es de 25,20 €.", ev.sources)
    assert len(cited) == 1 and cited[0].ok


def test_a_memory_citation_by_id_and_a_recalled_file_passage():
    memory = Memory(id="ab12cd34ef567890", scope="global", kind="fact", text="El cliente Norte paga a 60 días.",
                    source="", created=0, updated=0)
    doc = Memory(id="99aa88bb77cc6655", scope="global", kind="document", text=NOTES, source="file:contrato.md",
                 created=0, updated=0)
    recall = Recall(hits=[Hit(memory, memory.text, 0.1, ["words"], chunk=7), Hit(doc, NOTES, 0.1, ["words"], chunk=8)])
    ev = evidence_of(recall=recall)
    by_id, _ = inspect("El cliente Norte paga a 60 días [source: mem:ab12cd34].", ev.sources)
    assert by_id[0].ok and by_id[0].label == "fact · ab12cd34"
    wrong, _ = inspect("El cliente Norte paga a 90 días [source: mem:ab12cd34].", ev.sources)
    assert wrong[0].status == "unsupported"
    in_file, _ = inspect("El descuento por pronto pago es del 2 % [fuente: contrato.md].", ev.sources)
    assert in_file[0].ok and in_file[0].label == "contrato.md"
    assert [s.chunk for s in ev.sources.items if s.chunk] == [7, 8]
    assert key("file: ./Docs/Contrato.md#L12") == "docs/contrato.md" and key("https://www.x.es/a/") == "x.es/a"


# ------------------------------------------------------------------------------------------------ splitting
def test_an_answer_is_split_into_claims_without_code_headings_questions_or_greetings():
    answer = (
        "# Resumen\n\nClaro, aquí tienes el resultado. El IVA de 120 € es 25,20 €. ¿Quieres más detalle?\n\n"
        "```python\nprint('no soy una afirmación 123')\n```\n\n"
        "- Norte: 90 € de ingresos en 2024\n- El Sr. Pérez dirige la oficina de Madrid. Abre a las 9.\n\n"
        "| Región | Ingresos |\n|---|---|\n| Norte | 90 € |\n\nEstos son los pasos:\n\n"
        "Una línea que sigue\nen la siguiente línea del párrafo. Fin.\n")
    assert split_claims(answer) == [
        "El IVA de 120 € es 25,20 €.", "Norte: 90 € de ingresos en 2024", "El Sr. Pérez dirige la oficina de Madrid.",
        "Abre a las 9.", "Norte · 90 €", "Una línea que sigue en la siguiente línea del párrafo."]


def test_decimals_and_file_names_do_not_split_a_sentence():
    assert split_claims("Pi vale 3.14159 y está en notas.md. Otra frase aparte.") == [
        "Pi vale 3.14159 y está en notas.md.", "Otra frase aparte."]


def test_a_unit_before_a_full_stop_ends_the_sentence_but_a_title_does_not():
    assert split_claims("La latencia es de 35 ms. Cuesta 300 euros. Habló con la Sra. Pérez. Fin de línea.") == [
        "La latencia es de 35 ms.", "Cuesta 300 euros.", "Habló con la Sra. Pérez.", "Fin de línea."]


# ------------------------------------------------------------------------------------------------ labels
SQL_RESULT = "Tables:\nventas (ventas.csv): 6 rows\n\nResult:\nregion | ingresos\nnorte | 90.0\nsur | 70.0"
FIXTURE = [
    ("data_sql", {"sql": "SELECT region, sum(unidades * precio) AS ingresos FROM ventas GROUP BY region",
                  "files": ["ventas.csv"]}, SQL_RESULT),
    ("python", {"code": "print(120 * 21 / 100)"}, "25.2"),
    ("read_file", {"path": "notas.md"}, NOTES),
]
ANSWER = """## Resultado

El norte ingresa 90 € y el sur 70 €, según la consulta.
El IVA del 21 % sobre 120 € es 25,2 €.
Según notas.md, «el cliente Norte paga a 60 días».
Según notas.md, el cliente Norte paga a 90 días.
El total de ingresos de 2025 fue de 4.500 € en toda la empresa.
Probablemente el sur crezca el próximo trimestre.
Por tanto, conviene priorizar al cliente Norte.
Es muy sencillo.
¿Quieres que lo detalle?
"""


def test_labels_for_a_fixture_answer_with_tool_results():
    got = labels(ANSWER, evidence_of(run_events(*FIXTURE), user="¿Cuánto ingresa cada región?"))
    assert got == {
        "El norte ingresa 90 € y el sur 70 €, según la consulta.": ("verified", "tool"),
        "El IVA del 21 % sobre 120 € es 25,2 €.": ("verified", "command"),
        "Según notas.md, «el cliente Norte paga a 60 días».": ("verified", "cited"),
        "Según notas.md, el cliente Norte paga a 90 días.": ("unchecked", "citation_failed"),
        "El total de ingresos de 2025 fue de 4.500 € en toda la empresa.": ("unchecked", "unbacked"),
        "Probablemente el sur crezca el próximo trimestre.": ("hypothesis", "hedged"),
        "Por tanto, conviene priorizar al cliente Norte.": ("hypothesis", "inference"),
        "Es muy sencillo.": ("hypothesis", "generic"),
    }
    report = analyse(ANSWER, evidence_of(run_events(*FIXTURE)))
    assert report.counts == {"verified": 3, "hypothesis": 3, "unchecked": 2}
    tool = report.claims[0]
    assert tool.basis == [{"kind": "tool", "label": "data_sql", "score": tool.basis[0]["score"]}]
    assert [c for c in report.claims if c.why == "citation_failed"][0].citations[0].missing == ["90"]


def test_nothing_is_verified_without_evidence():
    got = labels("El IVA del 21 % sobre 120 € es 25,2 €. Python fue creado por Guido van Rossum en 1991.", evidence_of())
    assert {v for v, _ in got.values()} == {"unchecked"}


def test_a_failed_tool_is_not_evidence_and_a_number_it_did_not_print_is_not_backed():
    ev = evidence_of(run_events(("python", {"code": "1/0"}, "ZeroDivisionError", False)))
    assert label_of("El resultado de la división es 25,2.", ev) == ("unchecked", "unbacked")
    ev = evidence_of(run_events(("python", {"code": "print(25.2)"}, "25.2")))
    assert label_of("El resultado de python es 26.", ev)[0] == "unchecked"
    assert label_of("El resultado de python es 25,2.", ev) == ("verified", "command")


def test_a_name_the_output_lacks_keeps_a_claim_unchecked():
    ev = evidence_of(run_events(("data_sql", {"sql": "select 1"}, "region | ingresos\nnorte | 90\nsur | 70")))
    assert label_of("El cliente Madrid ingresa 90 €.", ev)[0] == "unchecked"
    assert label_of("El norte ingresa 90 €.", ev) == ("verified", "tool")


def test_the_user_s_own_words_back_a_restatement_and_the_model_s_written_file_only_a_claim_that_names_it():
    written = "# Informe\n\nBase 120 €, IVA 25,20 €, total con IVA 145,20 €.\n"
    ev = evidence_of(run_events(("write_file", {"path": "informe.md", "content": written}, "wrote")),
                     user="Mi base es de 120 € y el IVA es del 21 %.")
    got = labels("Tu base es de 120 € con un IVA del 21 %. Guardé informe.md con la base, el IVA (25,20 €) y el "
                 "total con IVA (145,20 €). El total con IVA es de 145,20 €.", ev)
    assert list(got.values()) == [("verified", "user"), ("verified", "file"), ("unchecked", "unbacked")]


def test_a_recalled_note_backs_a_claim_without_a_citation_and_a_long_source_is_read_by_passage():
    memory = Memory(id="ab12cd34ef567890", scope="global", kind="fact", text="El cliente Norte paga a 60 días.",
                    source="", created=0, updated=0)
    ev = evidence_of(recall=Recall(hits=[Hit(memory, memory.text, 0.1, ["words"])]))
    assert label_of("El cliente Norte paga a 60 días.", ev) == ("verified", "memory")
    filler = " ".join(f"palabra{i}" for i in range(400))
    page = f"{filler} La tasa de interés del contrato Alfa es del 3,5 % anual. {filler}"
    fetched = f"[HTTP 200] https://x.es/contrato\n\n{page}"
    ev = evidence_of(run_events(("web_fetch", {"url": "https://x.es/contrato"}, fetched)))
    assert label_of("La tasa de interés del contrato Alfa es del 3,5 % anual.", ev) == ("verified", "page")
    assert label_of("La tasa de interés del contrato Alfa es del 4,5 % anual.", ev)[0] == "unchecked"


def test_the_full_tool_result_is_used_when_the_event_was_cut_and_the_key_never_reaches_the_client():
    filler = "relleno de texto sin importancia\n" * 300
    long = f"linea inicial\n{filler}La cifra final del informe anual es 4321 euros.\n"
    events = run_events(("read_file", {"path": "anual.txt"}, long))
    assert "full" in events[1] and len(events[1]["content"]) == 4000
    ev = evidence_of(events)
    assert "full" not in events[1]
    assert label_of("La cifra final del informe anual es 4321 euros.", ev) == ("verified", "file")


def test_the_same_call_id_in_two_parallel_subtasks_is_not_mixed_up():
    notes = "El cliente Norte paga a 60 días."
    events = [
        {"type": "tool_call", "id": "c1", "name": "read_file", "arguments": {"path": "a.md"}, "subtask": "t1"},
        {"type": "tool_call", "id": "c1", "name": "python", "arguments": {"code": "print(7)"}, "subtask": "t2"},
        {"type": "tool_result", "id": "c1", "name": "python", "ok": True, "content": "7", "subtask": "t2"},
        {"type": "tool_result", "id": "c1", "name": "read_file", "ok": True, "content": notes, "subtask": "t1"},
    ]
    got = [(s.kind, s.label) for s in evidence_of(events).sources.items if s.kind != "user"]
    assert got == [("command", "python"), ("file", "a.md")]


def test_the_checker_failing_is_known_from_its_events():
    ev = evidence_of()
    assert not ev.verifier_failed
    ev.see({"type": "verify", "method": "llm", "returned": []})
    assert not ev.verifier_failed
    ev.see({"type": "verify", "method": "unavailable", "returned": []})
    assert ev.verifier_failed
    ev = evidence_of([{"type": "verify", "method": "llm", "returned": [{"subtask": "t1", "fix": "x"}]}])
    assert ev.verifier_failed
    ev.see({"type": "forge_report", "verified": True, "unresolved": []})
    assert not ev.verifier_failed  # the Forge report is the last word


# ------------------------------------------------------------------------------------------------ the model pass
def small_report() -> Report:
    claims = [Claim("c1", "a", "verified", "tool"), Claim("c2", "b", "hypothesis", "hedged"),
              Claim("c3", "c", "unchecked", "unbacked")]
    return Report(claims=claims, sources=[])


def test_the_model_pass_can_lower_a_label_and_never_raise_one():
    report = small_report()
    verdict = parse_downgrades('{"downgrade": [{"id": "c1", "label": "unchecked"}, {"id": "c2", "label": "verified"}, '
                               '{"id": "c3", "label": "verified"}, {"id": "c3", "label": "hypothesis"}, '
                               '{"id": "c9", "label": "unchecked"}, {"id": "c2", "label": "nonsense"}]}', report.claims)
    assert verdict == {"c1": "unchecked"}
    assert apply_downgrades(report, {"c1": "hypothesis", "c2": "verified", "c3": "verified"}) == 1
    assert [(c.label, c.downgraded) for c in report.claims] == [
        ("hypothesis", True), ("hypothesis", False), ("unchecked", False)]
    assert parse_downgrades("not json at all", report.claims) == {}
    assert parse_downgrades('{"downgrade": 3}', report.claims) == {}


# ------------------------------------------------------------------------------------------------ the orchestrator
RUN_ANSWER = ("Según notas.md, «el cliente Norte paga a 60 días».\nEl cliente Norte paga a 90 días [fuente: notas.md].\n"
              "El cliente Norte tiene 40 empleados.")


def orchestrator_over(provider, tmp_path):
    return Orchestrator(load_catalog(), lambda spec: Backend(provider=provider, model=None, adapter=None),
                        default_registry(tmp_path), PermissionBroker())


async def run_core(provider, tmp_path, **opts):
    (tmp_path / "notas.md").write_text(NOTES, encoding="utf-8")
    orch = orchestrator_over(provider, tmp_path)
    return [e async for e in orch.run([], "¿Qué dice notas.md del cliente Norte?", OrchestratorOptions(mode="core", **opts))]


async def test_the_orchestrator_adds_a_trust_event_before_done(tmp_path):
    provider = ScriptedProvider([call("read_file", {"path": "notas.md"}), text(RUN_ANSWER)])
    events = await run_core(provider, tmp_path, trust=True)
    kinds = [e["type"] for e in events]
    assert kinds[-2:] == ["trust", "done"] and kinds.count("trust") == 1
    trust = events[-2]
    assert trust["counts"] == {"verified": 1, "hypothesis": 0, "unchecked": 2}
    assert [(c["label"], c["why"]) for c in trust["claims"]] == [
        ("verified", "cited"), ("unchecked", "citation_failed"), ("unchecked", "unbacked")]
    failed = trust["claims"][1]["citations"][0]
    assert failed["status"] == "unsupported" and failed["missing"] == ["90"] and failed["ok"] is False
    assert trust["verifier_failed"] is False and trust["private"] is True  # the model read a file of the user's
    assert [s["kind"] for s in trust["sources"]] == ["file"]
    assert all("full" not in e for e in events)  # the whole tool result never leaves the run


async def test_without_the_option_there_is_no_trust_event_and_no_whole_results(tmp_path):
    provider = ScriptedProvider([call("read_file", {"path": "notas.md"}), text(RUN_ANSWER)])
    events = await run_core(provider, tmp_path)
    assert "trust" not in [e["type"] for e in events]


async def test_no_trust_event_for_a_failed_run_or_an_empty_answer(tmp_path):
    failed = await run_core(ScriptedProvider([[StreamEvent(kind="error", text="boom")]]), tmp_path, trust=True)
    assert "trust" not in [e["type"] for e in failed]
    empty = await run_core(ScriptedProvider([text("¿Quieres que lo detalle?")]), tmp_path, trust=True)
    assert "trust" not in [e["type"] for e in empty]  # nothing to label: a question is not a claim


async def test_the_model_pass_runs_once_lowers_labels_and_never_raises_one(tmp_path):
    verdict = json.dumps({"downgrade": [{"id": "c1", "label": "hypothesis"}, {"id": "c2", "label": "verified"},
                                        {"id": "c3", "label": "hypothesis"}]})
    provider = ScriptedProvider([call("read_file", {"path": "notas.md"}), text(RUN_ANSWER), text(verdict)])
    events = await run_core(provider, tmp_path, trust=True, trust_model_pass=True)
    trust = next(e for e in events if e["type"] == "trust")
    assert [(c["label"], c.get("downgraded", False)) for c in trust["claims"]] == [
        ("hypothesis", True), ("unchecked", False), ("unchecked", False)]  # c2 and c3 were already unchecked
    assert trust["counts"] == {"verified": 0, "hypothesis": 1, "unchecked": 2}
    assert trust["model_pass"] == {"ran": True, "lowered": 1}
    assert len(provider.requests) == 3  # the tool call, the answer, the one extra call
    extra = provider.requests[2]
    assert extra.temperature == 0.0 and "el cliente Norte paga a 60 días" in extra.messages[0].content
    assert "c2 [" not in extra.messages[0].content  # only the labels that could be lowered are put to the model
    assert extra.messages[0].private == ["Según notas.md, «el cliente Norte paga a 60 días»."]  # it quotes a file


async def test_a_model_pass_that_fails_changes_nothing(tmp_path):
    provider = ScriptedProvider([call("read_file", {"path": "notas.md"}), text(RUN_ANSWER), text("not json")])
    trust = next(e for e in await run_core(provider, tmp_path, trust=True, trust_model_pass=True) if e["type"] == "trust")
    assert trust["counts"] == {"verified": 1, "hypothesis": 0, "unchecked": 2} and trust["model_pass"]["lowered"] == 0


async def test_an_answer_that_must_be_json_is_not_labelled(tmp_path):
    schema = {"type": "object", "properties": {"dias": {"type": "integer"}}, "required": ["dias"]}
    provider = ScriptedProvider([text('{"dias": 60}')])
    events = await run_core(provider, tmp_path, trust=True, json_schema=schema)
    assert events[-1]["type"] == "done" and "trust" not in [e["type"] for e in events]
