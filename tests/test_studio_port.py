"""Studio contracts retained in the existing API and proof implementation, without network or real weights."""

import io
import json
import zipfile

import pytest

from spike.server.openai_api import Completion, complete, stream


async def outputs(*items):
    for item in items:
        yield item


@pytest.mark.parametrize("usage", [None, {"timings": {}}, {"prompt_tokens": 10},
                                   {"prompt_tokens": True, "completion_tokens": 2},
                                   {"prompt_tokens": -1, "completion_tokens": 2}])
async def test_api_does_not_invent_usage(usage):
    req = Completion(model="spike-core", messages=[], include_usage=True)
    events = [("text", "hola"), *([("usage", usage)] if usage is not None else [])]
    body = json.loads((await complete(req, outputs(*events))).body)
    assert body["usage"] is None
    response = stream(req, outputs(*events))
    chunks = [json.loads(b[6:]) async for b in response.body_iterator if b != b"data: [DONE]\n\n"]
    assert chunks[-1]["usage"] is None


async def test_api_retains_actual_zero_and_aggregates_backend_counts():
    req = Completion(model="spike-core", messages=[], include_usage=True)
    events = [("usage", {"input_tokens": 10, "output_tokens": 0}),
              ("usage", {"prompt_tokens": 2, "completion_tokens": 3})]
    expected = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    assert json.loads((await complete(req, outputs(*events))).body)["usage"] == expected
    chunks = [json.loads(b[6:]) async for b in stream(req, outputs(*events)).body_iterator
              if b != b"data: [DONE]\n\n"]
    assert chunks[-1]["usage"] == expected


def test_proof_labels_model_claims_as_unverified():
    from spike.proof import build_proof

    conv = {"id": "c", "title": "Check", "created": 1}
    messages = [{"role": "assistant", "content": "Everything independently verified!", "created": 1, "meta": {}}]
    with zipfile.ZipFile(io.BytesIO(build_proof(conv, messages, [], [], [], {}))) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["verification"] == {"status": "not_independently_verified"}
