"""Visual workflows (A22): the document, its checks, templates, conditions and the versioned storage in the project."""

import json
import os
import time

import pytest

from spike.workflows import model, store
from spike.workflows.model import Environment, WorkflowError, clean, validate
from spike.workflows.store import WorkflowConflict, WorkflowInvalid, WorkflowNotFound, WorkflowStore
from tests.helpers_workflows import ENV, branching, chain, doc, edge, node


def codes(d, env=ENV) -> list[tuple[str, str | None]]:
    return [(p.code, p.node) for p in validate(clean(d), env)]


# ---------------------------------------------------------------- the checks before a save or a run
def test_a_sound_workflow_passes_and_a_condition_may_join_its_branches():
    assert codes(chain()) == []
    assert codes(branching()) == []


def test_a_cycle_is_refused_and_names_the_nodes():
    d = doc([node("a", "specialist", prompt="x"), node("b", "specialist", prompt="y")], [edge("a", "b"), edge("b", "a")])
    problems = validate(clean(d), ENV)
    assert [p.code for p in problems] == ["cycle"]
    assert set(problems[0].params["nodes"]) == {"a", "b"} and "a" in problems[0].message and "b" in problems[0].message
    loop = doc([node("a", "specialist", prompt="x")], [edge("a", "a")])
    assert [p.code for p in validate(clean(loop), ENV)] == ["edge_self"]
    assert model.find_cycle(clean(chain())) == []


def test_unknown_specialists_and_tools_and_tools_that_need_someone_to_answer():
    d = doc([node("s", "specialist", specialist="astrology", prompt="x"), node("t", "tool", tool="rm_rf"),
             node("q", "tool", tool="ask_user", arguments={"question": "?"})], [])
    assert codes(d) == [("specialist_unknown", "s"), ("tool_unknown", "t"), ("tool_unavailable", "q")]
    assert codes(doc([node("s", "specialist", specialist="finance", prompt="x"),
                      node("a", "specialist", specialist="auto", prompt="x")], [])) == []


def test_every_variable_must_name_an_input_or_a_node_upstream():
    def one(prompt, extra=(), edges=()):
        return codes(doc([node("in", "input", name="topic", default="x"), node("a", "specialist", name="a", prompt=prompt),
                          node("b", "specialist", name="b", prompt="y"), *extra], [edge("in", "a"), *edges]))

    assert one("{{topic}} {{ topic }}") == []
    assert one("{{nope}}") == [("var_unknown", "a")]
    assert one("{{b}}") == [("var_upstream", "a")]  # b exists but is not upstream of a
    assert one("{{b}}", edges=[edge("b", "a")]) == []
    assert one("{{a b}}") == [("var_syntax", "a")]
    assert one(r"literal \{{ braces }} and {{topic}}") == []
    assert codes(doc([node("a", "specialist", prompt="{{input}}")], [])) == [("var_input", "a")]
    assert codes(doc([node("i", "input", name="i", default="1"), node("a", "specialist", name="a", prompt="{{a}}")],
                     [edge("i", "a")])) == [("var_upstream", "a")]  # a node is not upstream of itself


def test_tool_arguments_are_checked_for_presence_names_and_constant_types():
    def tool(args):
        return codes(doc([node("t", "tool", tool="echo", arguments=args)], []))

    assert tool({"text": "hi"}) == []
    assert tool({}) == [("arg_missing", "t")]
    assert tool({"text": "  "}) == [("arg_missing", "t")]
    assert tool({"text": "hi", "colour": "red"}) == [("arg_unknown", "t")]
    assert tool({"text": "hi", "times": "abc"}) == [("arg_type", "t")]
    assert tool({"text": "hi", "times": 2.5}) == [("arg_type", "t")]
    assert tool({"text": "hi", "times": "3"}) == []  # a number written as text is converted when the node runs
    assert tool({"text": "hi", "times": "{{input}}"}) == [("var_input", "t")]  # a template is checked when it runs


def test_edges_join_an_output_to_an_input_of_a_compatible_type():
    a, b = node("a", "specialist", prompt="x"), node("b", "specialist", prompt="y")
    out = node("o", "output", content="z")
    src = node("i", "input", name="i", default="1")
    assert [p.code for p in validate(clean(doc([a, out], [edge("o", "a")])), ENV)] == ["edge_port"]  # output has no outputs
    assert [p.code for p in validate(clean(doc([a, src], [edge("a", "i")])), ENV)] == ["edge_port"]  # input takes none
    assert [p.code for p in validate(clean(doc([a, b], [{**edge("a", "b"), "fromPort": "true"}])), ENV)] == ["edge_port"]
    assert [p.code for p in validate(clean(doc([a, b], [{**edge("a", "b"), "toPort": "x"}])), ENV)] == ["edge_port"]
    assert [p.code for p in validate(clean(doc([a, b], [edge("a", "b"), {**edge("a", "b"), "id": "again"}])), ENV)] == [
        "edge_duplicate"]
    assert [p.code for p in validate(clean(doc([a], [edge("a", "ghost")])), ENV)] == ["edge_node"]
    file_in = node("f", "input", name="f", kind="file", default="notes.txt")
    cond = node("c", "condition", op="contains", value="x")
    assert [p.code for p in validate(clean(doc([file_in, cond], [edge("f", "c")])), ENV)] == ["edge_type"]
    num = node("m", "input", name="m", kind="number", default="3")
    assert codes(doc([num, cond], [edge("m", "c")])) == []
    assert [p.code for p in validate(clean(doc([a, b, cond], [edge("a", "c"), edge("b", "c")])), ENV)] == [
        "edge_condition_inputs"]
    assert [p.code for p in validate(clean(doc([cond], [])), ENV)] == ["edge_condition_inputs"]


def test_port_types_follow_the_input_kind_through_a_condition():
    d = clean(doc([node("n", "input", name="n", kind="number", default="1"), node("c", "condition", op="contains",
                                                                                 value="1"),
                   node("a", "specialist", prompt="p")], [edge("n", "c"), edge("c", "a", "true")]))
    assert [model.port_type(d, i) for i in ("n", "c", "a")] == ["number", "number", "text"]


def test_condition_and_output_settings_are_checked():
    def cond(**f):
        return codes(doc([node("i", "input", name="i", default="x"), node("c", "condition", **f)], [edge("i", "c")]))

    assert cond(op="contains", value="ok") == []
    assert cond(op="contains", value=" ") == [("condition_value", "c")]
    assert cond(op="starts", value="ok") == [("condition_op", "c")]
    assert cond(op="regex", value="^ok\\d+$") == []
    assert cond(op="regex", value="(") == [("condition_regex", "c")]
    assert cond(op="regex", value="(a+)+$") == [("condition_regex", "c")]  # exponential backtracking
    assert cond(op="regex", value="a" * 400) == [("condition_regex", "c")]
    assert cond(op="number", compare="<=", value="3.5") == []
    assert cond(op="number", compare="<=", value="many") == [("condition_number", "c")]
    assert cond(op="number", compare="=>", value="3") == [("condition_compare", "c")]

    def out(**f):
        return codes(doc([node("o", "output", **f)], []))

    assert out(mode="file", path="informes/{{x}}.md", content="c") == [("var_unknown", "o")]
    assert out(mode="file", path="informes/a.md", content="c") == []
    assert out(mode="file", path="", content="c") == [("output_path", "o")]
    assert out(mode="file", path="../a.md", content="c") == [("output_path", "o")]
    assert out(mode="file", path="/etc/passwd", content="c") == [("output_path", "o")]
    assert out(mode="file", path="C:/x.md", content="c") == [("output_path", "o")]
    assert out(mode="file", path="workflows/wf-1/0002.json", content="c") == [("output_path", "o")]
    assert out(mode="artifact", content="  ") == [("output_content", "o")]
    assert out(mode="artifact", content="") == [("var_input", "o")]  # empty content means {{input}}
    assert out(mode="artifact", format="pdf", content="c") == [("output_format", "o")]
    assert out(mode="screen", content="c") == [("output_mode", "o")]


def test_names_ids_and_inputs_are_checked():
    two = doc([node("a", "input", name="x", default="1"), node("b", "input", name="x", default="1")], [])
    assert [p.code for p in validate(clean(two), ENV)] == []  # clean renames the second: names stay unique
    assert clean(two)["nodes"][1]["name"] == "x_"
    assert codes(doc([node("a", "input", name="input", default="1")], [])) == [("node_name", "a")]
    assert codes(doc([node("a", "input", name="1abc", default="1")], [])) == [("node_name", "a")]
    assert codes(doc([node("a", "input", name="ok", default="1"), node("a", "input", name="ok2", default="1")], [])) == [
        ("node_id", "a")]
    assert codes(doc([node("a b", "input", name="ok", default="1")], [])) == [("node_id", "a b")]
    assert codes(doc([node("a", "robot")], [])) == [("node_type", "a")]
    assert codes(doc([node("a", "input", name="n", kind="number", default="abc")], [])) == [("input_default", "a")]
    assert codes(doc([node("a", "input", name="f", kind="file", default="../x")], [])) == [("input_default", "a")]
    assert codes(doc([node("a", "input", name="n", kind="blob")], [])) == [("input_kind", "a")]
    assert codes(doc([], [])) == [("no_nodes", None)]


def test_clean_keeps_known_fields_and_refuses_what_is_not_a_workflow():
    raw = doc([node("a", "specialist", prompt="p", extra="dropped", x=99999, y="up")], [])
    cleaned = clean(raw)
    assert "extra" not in cleaned["nodes"][0] and cleaned["nodes"][0]["x"] == 10_000 and cleaned["nodes"][0]["y"] == 0
    assert cleaned["nodes"][0]["specialist"] == "auto"
    for bad in (None, [], {}, {"format": "spike-workflow", "version": 2, "nodes": []},
                {"format": "spike-project", "version": 1}, {**raw, "nodes": "x"}):
        with pytest.raises(WorkflowError):
            clean(bad)
    with pytest.raises(WorkflowError, match="at most"):
        clean({**raw, "nodes": [node(f"n{i}", "input", default="1") for i in range(model.MAX_NODES + 1)]})
    deep = clean(doc([node("t", "tool", tool="echo", arguments={"a": [[[[[[["deep"]]]]]]]})], []))
    assert deep["nodes"][0]["arguments"] == {"a": [[[[""]]]]}  # nesting stops after a few levels


# ---------------------------------------------------------------- templates, conditions, order
def test_templates_fill_variables_keep_escapes_and_report_what_they_use():
    assert model.references("{{a}} and {{ b }} and {{a}}") == ["a", "b"]
    assert model.render("Hola {{who}}, {{ n }}", {"who": "Ana", "n": "3"}) == "Hola Ana, 3"
    assert model.render(r"keep \{{who}} but {{who}}", {"who": "Ana"}) == "keep {{who}} but Ana"
    assert model.render("{{a}}}", {"a": "x"}) == "x}"
    with pytest.raises(KeyError):
        model.render("{{missing}}", {})
    assert model.render_value({"k": ["{{a}}", 2, {"d": "{{a}}!"}]}, {"a": "x"}) == {"k": ["x", 2, {"d": "x!"}]}
    node_ = clean(doc([node("t", "tool", tool="echo", arguments={"text": "{{a}}", "n": {"x": ["{{b}}"]}})], []))["nodes"][0]
    assert model.used_names(node_) == ["a", "b"]


def test_conditions_contains_regex_and_number_comparisons():
    def test(subject, **f):
        return model.evaluate({"op": "contains", "compare": ">", "case_sensitive": False, **f}, subject, f["value"])

    assert test("Todo OK aquí", op="contains", value="ok") is True
    assert test("Todo OK aquí", op="contains", value="ok", case_sensitive=True) is False
    assert test("order 66", op="regex", value=r"order \d+") is True
    assert test("ORDER x", op="regex", value=r"order \d+") is False
    assert test("12", op="number", value="10") is True
    assert test("10", op="number", value="10", compare=">=") is True
    assert test("10", op="number", value="10", compare="!=") is False
    assert test("1,5", op="number", value="1.2") is True  # a decimal comma
    assert test("Total: 42 EUR", op="number", value="40") is True  # the first number in a text
    with pytest.raises(ValueError, match="no number"):
        test("no digits", op="number", value="1")
    assert model.show_number(5.0) == "5" and model.show_number(2.5) == "2.5"


def test_levels_use_the_planner_order_and_a_diamond_joins_after_both_sides():
    d = clean(branching())
    assert model.levels(d) == [["n"], ["c"], ["big", "small"], ["end"]]
    assert model.levels(clean(chain())) == [["in"], ["ask"], ["say"], ["out"]]
    assert model.ancestors(d, "end") == {"n", "c", "big", "small"}


def test_inputs_use_defaults_and_report_what_is_missing_or_wrong():
    d = clean(doc([node("a", "input", name="text", default="hola"), node("b", "input", name="n", kind="number"),
                   node("c", "input", name="doc", kind="file")], []))
    values, problems = model.bind_inputs(d, {"n": "2,50", "doc": " notes.txt "}, lambda p: None)
    assert values == {"text": "hola", "n": "2.5", "doc": "notes.txt"} and problems == []
    values, problems = model.bind_inputs(d, {"text": "x", "n": "abc"}, lambda p: "the file does not exist")
    assert [(p.code, p.node) for p in problems] == [("input_number", "b"), ("input_missing", "c")]
    values, problems = model.bind_inputs(d, {"n": 3, "doc": "gone.txt"}, lambda p: "the file does not exist")
    assert [(p.code, p.node) for p in problems] == [("input_file", "c")] and values["n"] == "3"


# ---------------------------------------------------------------- storage
@pytest.fixture
def folder(tmp_path):
    return tmp_path / "files"


def test_saving_writes_versions_and_the_newest_is_the_workflow(folder):
    ws = WorkflowStore(folder)
    first = ws.save(chain(), ENV)
    assert first["revision"] == 1 and first["id"].startswith("wf-")
    assert (folder / "workflows" / first["id"] / "0001.json").is_file()
    changed = {**chain(), "name": "Informe — año 2"}
    second = ws.save(changed, ENV, first["id"], base_revision=1)
    assert second["revision"] == 2 and ws.get(first["id"])["name"] == "Informe — año 2"
    assert ws.get(first["id"], 1)["name"] == "Test"
    assert [v["revision"] for v in ws.versions(first["id"])] == [2, 1]
    assert [w["id"] for w in ws.list()] == [first["id"]] and ws.list()[0]["revision"] == 2
    raw = (folder / "workflows" / first["id"] / "0002.json").read_bytes()
    assert "año".encode() in raw and json.loads(raw)["revision"] == 2  # UTF-8 on every platform
    with pytest.raises(WorkflowConflict):
        ws.save(chain(), ENV, first["id"], base_revision=1)
    with pytest.raises(WorkflowNotFound):
        ws.get(first["id"], 7)
    with pytest.raises(WorkflowNotFound):
        ws.get("../escape")


def test_an_invalid_workflow_is_not_saved_and_the_error_lists_every_problem(folder):
    ws = WorkflowStore(folder)
    bad = doc([node("a", "specialist", prompt="{{nope}}"), node("t", "tool", tool="ghost")], [])
    with pytest.raises(WorkflowInvalid) as caught:
        ws.save(bad, ENV)
    assert {p.code for p in caught.value.problems} == {"var_unknown", "tool_unknown"}
    assert ws.list() == [] and not (folder / "workflows").exists()
    with pytest.raises(WorkflowInvalid):
        ws.save({**chain(), "name": "  "}, ENV)


def test_export_and_import_round_trip_keeps_the_workflow_and_gives_it_a_new_id(folder, tmp_path):
    ws = WorkflowStore(folder)
    saved = ws.save(branching(), ENV)
    exported = json.loads(json.dumps(WorkflowStore.export(ws.get(saved["id"]))))
    assert {"id", "revision", "saved"}.isdisjoint(exported)
    other = WorkflowStore(tmp_path / "another")
    copy = other.save(exported, ENV)
    assert copy["id"] != saved["id"] and copy["revision"] == 1
    a, b = ws.get(saved["id"]), other.get(copy["id"])
    assert (a["name"], a["nodes"], a["edges"]) == (b["name"], b["nodes"], b["edges"])
    with pytest.raises(WorkflowInvalid):  # a tool this computer does not have
        other.save(exported, Environment(specialists={"core"}, tools={}, unavailable=()))


def test_old_versions_are_pruned_and_a_broken_or_linked_file_is_reported_not_trusted(folder, monkeypatch):
    monkeypatch.setattr(store, "MAX_VERSIONS", 3)
    ws = WorkflowStore(folder)
    wid = ws.save(chain(), ENV)["id"]
    for _ in range(4):
        ws.save(chain(), ENV, wid)
    assert [v["revision"] for v in ws.versions(wid)] == [5, 4, 3]
    (folder / "workflows" / wid / "0006.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkflowError):
        ws.get(wid)
    assert ws.list() == [{"id": wid, "name": wid, "broken": True}]
    (folder / "workflows" / "wf-big").mkdir()
    (folder / "workflows" / "wf-big" / "0001.json").write_text(" " * (store.MAX_BYTES + 1), encoding="utf-8")
    with pytest.raises(WorkflowError):
        ws.get("wf-big")
    if hasattr(os, "symlink"):
        target = folder / "elsewhere"
        target.mkdir()
        try:
            os.symlink(target, folder / "workflows" / "wf-link")
        except OSError:
            return  # no symbolic links on this system
        with pytest.raises(WorkflowError):
            ws.get("wf-link")


def test_run_records_are_stored_listed_newest_first_and_pruned(folder, monkeypatch):
    monkeypatch.setattr(store, "MAX_RUNS", 2)
    ws = WorkflowStore(folder)
    wid = ws.save(chain(), ENV)["id"]
    ids = []
    for i in range(3):
        rid = f"{1_700_000_000_000 + i:013d}-abcdef"
        ids.append(rid)
        ws.save_run(wid, {"id": rid, "status": "completed", "nodes": {"in": {"status": "ok"}}, "started": time.time()})
    assert [r["id"] for r in ws.list_runs(wid)] == [ids[2], ids[1]]
    assert ws.get_run(wid, ids[2])["status"] == "completed"
    with pytest.raises(WorkflowNotFound):
        ws.get_run(wid, ids[0])
    with pytest.raises(WorkflowNotFound):
        ws.get_run(wid, "../../x")
    with pytest.raises(WorkflowError):
        ws.save_run(wid, {"id": "../../evil"})
    ws.delete(wid)
    assert not (folder / "workflows" / wid).exists()
