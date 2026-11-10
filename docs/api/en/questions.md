# API reference: `/api/questions`

Language: [Español](../es/questions.md) | **English** · [API index](README.md)

### `POST /api/questions/{question_id}`

The user's answer to a question a specialist asked with `ask_user`; the paused run goes on with it.

Handler: `spike/server/app.py` → `answer_question`

**Parameters**

| Name | In | Type | Required | Default |
|---|---|---|---|---|
| `question_id` | path | string | yes |  |

**Body** (`application/json`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `answer` | string | yes |  |  |

**Response**: `200` — object

**Errors**

| Code | Message |
|---|---|
| `404` | no pending question with this id |
| `422` | the request does not match the schema (FastAPI validation) |

**Example**

```bash
curl -s -X POST 'http://127.0.0.1:8740/api/questions/<question_id>' \
  -H 'Content-Type: application/json' \
  -d '{"answer": "string"}'
```
