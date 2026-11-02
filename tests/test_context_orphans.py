"""fit_messages never sends a tool result without the assistant turn that asked for it (Gemini's G11 report)."""

import json

import pytest

from spike.core.context import fit_messages
from spike.core.types import Message, ToolCall
from spike.store.secrets import SecretStore


def counter(text: str) -> int:
    return len(text)


def call(cid: str) -> ToolCall:
    return ToolCall(id=cid, name="read_file", arguments={})


def valid_protocol(messages: list[Message]) -> bool:
    open_calls: set[str] = set()
    for m in messages:
        if m.role == "tool":
            if m.tool_call_id not in open_calls:
                return False
            open_calls.discard(m.tool_call_id)
        else:
            if open_calls:
                return False
            open_calls = {c.id for c in m.tool_calls}
    return True


SYSTEM = Message(role="system", content="s")


def test_one_huge_tool_result_keeps_its_call_and_fits():
    msgs = [SYSTEM, Message(role="user", content="read it"),
            Message(role="assistant", content="", tool_calls=[call("c1")]),
            Message(role="tool", content="x" * 5000, tool_call_id="c1")]
    kept, _ = fit_messages(msgs, 400, counter)
    assert valid_protocol(kept)
    tool = [m for m in kept if m.role == "tool"]
    assert len(tool) == 1 and "truncated" in tool[0].content and len(tool[0].content) < 5000
    assert any(m.tool_calls for m in kept)
    assert msgs[3].content == "x" * 5000                      # the caller's message is not modified


def test_a_turn_with_two_calls_is_kept_or_dropped_whole():
    msgs = [SYSTEM, Message(role="user", content="u"),
            Message(role="assistant", content="", tool_calls=[call("c1"), call("c2")]),
            Message(role="tool", content="a" * 900, tool_call_id="c1"),
            Message(role="tool", content="b" * 900, tool_call_id="c2")]
    kept, _ = fit_messages(msgs, 800, counter)
    assert valid_protocol(kept)
    assert [m.tool_call_id for m in kept if m.role == "tool"] == ["c1", "c2"]


def test_an_older_tool_turn_is_dropped_whole_when_a_newer_message_fills_the_budget():
    msgs = [SYSTEM, Message(role="user", content="u1"),
            Message(role="assistant", content="", tool_calls=[call("c1")]),
            Message(role="tool", content="y" * 300, tool_call_id="c1"),
            Message(role="assistant", content="done"), Message(role="user", content="z" * 200)]
    kept, dropped = fit_messages(msgs, 250, counter)
    assert valid_protocol(kept) and dropped == 3
    assert not any(m.role == "tool" or m.tool_calls for m in kept) and kept[-1].content == "z" * 200


def test_a_leading_orphan_tool_message_never_reaches_the_provider():
    msgs = [SYSTEM, Message(role="tool", content="old", tool_call_id="gone"), Message(role="user", content="hi")]
    kept, dropped = fit_messages(msgs, 1000, counter)
    assert valid_protocol(kept) and dropped == 1


def test_everything_that_fits_is_unchanged():
    msgs = [SYSTEM, Message(role="user", content="u"),
            Message(role="assistant", content="", tool_calls=[call("c1")]),
            Message(role="tool", content="ok", tool_call_id="c1"), Message(role="assistant", content="fin")]
    assert fit_messages(msgs, 10_000, counter) == (msgs, 0)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"123", b'{"a": 1}'])
def test_a_secrets_file_that_is_not_a_dict_of_strings_reads_as_empty(tmp_path, raw):
    path = tmp_path / "secrets.json"
    path.write_bytes(raw)
    store = SecretStore(path, use_keyring=False)
    assert store.get("a") is None
    store.set("b", "v")
    assert store.get("b") == "v"


def test_secrets_are_utf8_whatever_the_locale(tmp_path, monkeypatch):
    path = tmp_path / "secrets.json"
    store = SecretStore(path, use_keyring=False)
    store.set("conector-ñ", "clave-€")
    assert json.loads(path.read_bytes().decode("utf-8")) == {"conector-ñ": "clave-€"}
    assert SecretStore(path, use_keyring=False).get("conector-ñ") == "clave-€"
    calls = []
    real = type(path).read_text

    def spy(self, *a, **k):
        calls.append(k.get("encoding"))
        return real(self, *a, **k)

    monkeypatch.setattr(type(path), "read_text", spy)
    SecretStore(path, use_keyring=False).get("conector-ñ")
    assert calls and all(c == "utf-8" for c in calls)
