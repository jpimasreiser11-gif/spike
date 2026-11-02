"""Research exports, bounded source extraction and exact quote provenance; no model or network."""

import copy
import json

import pytest

from spike.research import ResearchError, load_sources, notebook, validate_analysis
from tests.helpers_research import pdf_bytes


def evidence(source="s1", quote="The result is positive."):
    return {"source_id": source, "page": 1, "quote": quote, "claim": "A result"}


def pair():
    return {
        "left": evidence(),
        "right": evidence("s2", "The result is negative."),
        "reason": "Different results",
    }


@pytest.fixture
def sources(tmp_path):
    (tmp_path / "a.txt").write_text("The result is positive.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("The result is negative.", encoding="utf-8")
    return load_sources(tmp_path, ["a.txt", "b.txt"])


def test_quotes_are_exact_and_bound_to_document_page_hash_and_offset(sources):
    result = validate_analysis({"pairs": [pair()]}, "contradictions", sources)
    assert result["status"] == "candidates"
    for side in ("left", "right"):
        ref = result["pairs"][0][side]
        source = next(s for s in sources if s["id"] == ref["source_id"])
        assert source["pages"][ref["page"] - 1][ref["start"] : ref["end"]] == ref["quote"]
        assert ref["sha256"] == source["sha256"]


@pytest.mark.parametrize("mutation", ["invented", "case", "page", "source", "same", "empty", "type", "extra"])
def test_invalid_or_misattributed_quotes_are_rejected(sources, mutation):
    data = {"pairs": [pair()]}
    left = data["pairs"][0]["left"]
    if mutation == "invented":
        left["quote"] = "A conclusion not in the file"
    elif mutation == "case":
        left["quote"] = left["quote"].lower()
    elif mutation == "page":
        left["page"] = True
    elif mutation == "source":
        left["source_id"] = "s2"
    elif mutation == "same":
        data["pairs"][0]["right"] = copy.deepcopy(left)
    elif mutation == "empty":
        left["quote"] = " "
    elif mutation == "type":
        data["pairs"] = "bad"
    elif mutation == "extra":
        data["pairs"][0]["right"]["start"] = 900
    with pytest.raises(ResearchError):
        validate_analysis(data, "contradictions", sources)


def test_pdf_extraction_and_sections(tmp_path):
    (tmp_path / "paper.pdf").write_bytes(pdf_bytes())
    sources = load_sources(tmp_path, ["paper.pdf"])
    result = validate_analysis(
        {"methods": [evidence(quote="compare two seeds")], "equations": [], "tables": []}, "paper", sources
    )
    assert result["status"] == "draft"
    assert result["methods"][0]["path"] == "paper.pdf"
    assert sources[0]["sha256"] and len(sources[0]["pages"]) == 1


@pytest.mark.parametrize(
    "bad",
    [
        "../escape.txt",
        "/tmp/escape.txt",
        "a/../../escape.txt",
        "C:\\escape.txt",
        "a/./b.txt",
        "folder/",
        "a.json",
    ],
)
def test_unsafe_paths_or_formats_fail(tmp_path, bad):
    with pytest.raises(ResearchError):
        load_sources(tmp_path, [bad])


def test_symlinks_empty_scan_and_size_limits(tmp_path, monkeypatch):
    import spike.research as module

    (tmp_path / "target.txt").write_text("private", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ResearchError):
        load_sources(tmp_path, ["link.txt"])
    (tmp_path / "blank.pdf").write_bytes(pdf_bytes(""))
    with pytest.raises(ResearchError, match="no_text"):
        load_sources(tmp_path, ["blank.pdf"])
    monkeypatch.setattr(module, "MAX_BYTES", 2)
    with pytest.raises(ResearchError, match="too_large"):
        load_sources(tmp_path, ["target.txt"])


def test_text_limit_and_duplicate_sources(tmp_path, monkeypatch):
    import spike.research as module

    (tmp_path / "a.txt").write_text("abcdefgh", encoding="utf-8")
    with pytest.raises(ResearchError):
        load_sources(tmp_path, ["a.txt", "a.txt"])
    monkeypatch.setattr(module, "MAX_TEXT", 4)
    with pytest.raises(ResearchError, match="too_large"):
        load_sources(tmp_path, ["a.txt"])


def test_notebook_preserves_proposals_and_matches_recorded_outputs_only_by_id():
    messages = [
        {
            "id": "m1",
            "role": "assistant",
            "content": "Example\n```python\nprint(99)\n```\n```js\nalert(1)\n```",
            "meta": {
                "tools": [
                    {"type": "tool_call", "name": "python", "id": "c1", "arguments": {"code": "print(3)"}},
                    {"type": "tool_result", "name": "python", "id": "c1", "ok": True, "content": "3"},
                    {
                        "type": "tool_result",
                        "name": "python",
                        "id": "other",
                        "content": "<script>bad</script>",
                    },
                ]
            },
        }
    ]
    data = json.loads(json.dumps(notebook({"id": "chat"}, messages)))
    assert data["nbformat"] == 4 and data["nbformat_minor"] == 5
    cells = data["cells"]
    assert len({c["id"] for c in cells}) == len(cells)
    codes = [c for c in cells if c["cell_type"] == "code"]
    assert [c["source"].strip() for c in codes] == ["print(99)", "print(3)"]
    assert all(c["execution_count"] is None for c in codes)
    assert codes[0]["outputs"] == []
    assert "3" in codes[1]["outputs"][0]["text"]
    assert codes[1]["metadata"]["spike"]["call_id"] == "c1"
    assert all(o["output_type"] == "stream" for c in codes for o in c["outputs"])
    assert any(c["cell_type"] == "raw" and "<script>bad" in c["source"] for c in cells)


def test_ambiguous_tool_ids_are_never_linked_and_outputs_stay_in_their_message():
    call = {"type": "tool_call", "name": "python", "id": "c", "arguments": {"code": "print(1)"}}
    result = {"type": "tool_result", "name": "python", "id": "c", "content": "1"}
    data = notebook(
        {"id": "c"},
        [
            {"id": "a", "role": "assistant", "content": "", "meta": {"tools": [call, call]}},
            {"id": "b", "role": "assistant", "content": "", "meta": {"tools": [result]}},
        ],
    )
    assert not any(c.get("outputs") for c in data["cells"])
    assert any(c["cell_type"] == "raw" and "1" in c["source"] for c in data["cells"])


def test_data_python_and_other_tools_keep_plain_outputs_without_cross_linking():
    events = [
        {"type": "tool_result", "id": "earlier", "name": "python", "content": "before call"},
        {"type": "tool_call", "id": "earlier", "name": "python", "arguments": {"code": "print('later')"}},
        {"type": "tool_call", "id": "d", "name": "data_python", "arguments": {"code": "print(5)"}},
        {"type": "tool_result", "id": "d", "name": "data_python", "content": "5", "ok": True},
        {"type": "tool_result", "id": "d", "name": "read_file", "content": "<script>private</script>"},
    ]
    nb = notebook({"id": "c"}, [{"id": "m", "role": "assistant", "content": "", "meta": {"tools": events}}])
    codes = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert codes[0]["outputs"] == [] and codes[1]["outputs"][0]["text"].endswith("5")
    raw = [c for c in nb["cells"] if c["cell_type"] == "raw"]
    assert len(raw) == 2 and all(c["metadata"]["format"] == "text/plain" for c in raw)


def test_pdf_page_limit_and_encryption_are_explicit(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    import spike.research as module
    (tmp_path / "paper.pdf").write_bytes(pdf_bytes())
    monkeypatch.setattr(module, "MAX_PAGES", 0)
    with pytest.raises(ResearchError, match="too_large"):
        load_sources(tmp_path, ["paper.pdf"])
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("test-password")
    writer.write(tmp_path / "locked.pdf")
    with pytest.raises(ResearchError, match="encrypted_pdf"):
        load_sources(tmp_path, ["locked.pdf"])
