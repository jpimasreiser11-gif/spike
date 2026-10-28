# Local conversation search

Open **Buscar conversaciones / Search conversations** in the sidebar, or press **Cmd+K / Ctrl+K** when a task is not
running and no other dialog is open. Enter up to 12 words (200 characters) and submit. Opening the dialog does not make
a search or a model call. The initial scope is the current project, or chats outside projects. Choose all projects to
find a decision elsewhere. Results include old chats outside the sidebar's 200-chat listing.

Filters: all words or an adjacent phrase in order, project, sender, and the last 7/30/90 days. The date is the message's
creation time (the conversation's creation time for a title), not its last edit. Case and accents are ignored by the
Unicode tokenizer. Punctuation separates words; this is not literal substring, fuzzy or semantic search. Query operators
are treated as words, never executed as FTS syntax. Results show a bounded highlighted excerpt and open the actual
message in its project. Deleted results show an error and can be searched again. The dialog supports Escape, keyboard
focus containment/restoration and narrow layouts, with Spanish and English strings.

## Storage and API

`POST /api/history/search` accepts JSON, so the query does not go into the URL/access-log path. Example:

```json
{"query":"SQLite memoria","scope":"all","match":"words","role":"assistant","after":0,"limit":20,"offset":0}
```

`scope` is `all`, `workspace` (outside projects), or `project` with `project_id`. A project ID is invalid outside project
scope. `role` is `all` (titles and messages), `user` or `assistant`; `match` is `words` or `phrase`. `after` is a finite,
nonnegative Unix timestamp. `limit` is 1–50 and `offset` is 0–1000. Results are ordered by FTS rank, date and stable ID;
`has_more` and `next_offset` support pages without an expensive total count. Narrow filters for larger result sets.
Concurrent edits may change ordering between pages. The UI keeps its time cutoff fixed while loading more.

Responses use `Cache-Control: no-store`. Each result carries conversation/message IDs, current project/title metadata,
role, date and plain `{text, matched}` segments. React escapes those segments; no excerpt is rendered as HTML.

The first store opening transactionally backfills a local SQLite FTS5 index of persisted conversation titles and message
bodies. Stable integer mapping IDs avoid relying on source tables' hidden rowids across VACUUM. SQL triggers maintain
inserts, title/content edits, retries and cascading deletes, including imports and conversation branches. No separate
indexer or dependency is installed. FTS5 is already used by SPIKE's document memory.

The contentful search index duplicates searchable text inside the same database, increasing disk use. Deletion removes
entries from search results; it does **not** promise forensic erasure of SQLite pages, WAL, exports or backups. Temporary
chats remain in the separate in-memory store and the API never searches them. Files, document memory, tool metadata and
provider configuration are not searched. Existing local-server access protections still apply: this is a personal
workspace feature, not a multiuser authorization boundary.

## Validation

- `tests/test_history.py`: legacy migration, reopen/VACUUM, Unicode/phrases, input limits, filters, deletion/edit/retry,
  plain bounded excerpts, pagination and old conversations beyond the sidebar limit.
- `tests/test_history_server.py`: persistent-only API, no model calls, request validation, branches and project import.
- `web/src/history.test.tsx`: explicit submission, stale responses, safe text, filters, errors and pagination.
- `web/e2e/smoke.mjs` with `tests/e2e/serve_scripted.py`: real Chromium navigation, project switch, exact message focus,
  modal keyboard handling and mobile layout. Providers and data are scripted; no real weights or paid calls are used.

Implementation references: [SQLite FTS5](https://www.sqlite.org/fts5.html) and
[the native dialog element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog).
