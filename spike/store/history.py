"""Local FTS5 index of titles and message bodies; never metadata, files or model calls.

A stable integer mapping survives VACUUM on the source tables' text primary keys. Contentful FTS allows deletion
without retaining a copy of the deleted source row. Triggers cover imports, edits, retries and cascading deletes.
"""

from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
import uuid

DDL = (
    "CREATE TABLE history_map (id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL "
    "REFERENCES conversations(id) ON DELETE CASCADE, message_id TEXT UNIQUE "
    "REFERENCES messages(id) ON DELETE CASCADE)",
    "CREATE UNIQUE INDEX history_title ON history_map(conversation_id) WHERE message_id IS NULL",
    "CREATE INDEX history_conversation ON history_map(conversation_id)",
    "CREATE VIRTUAL TABLE history_fts USING fts5(text, tokenize='unicode61 remove_diacritics 2')",
    "CREATE TRIGGER history_map_deleted AFTER DELETE ON history_map BEGIN "
    "DELETE FROM history_fts WHERE rowid=old.id; END",
    "CREATE TRIGGER history_title_added AFTER INSERT ON conversations BEGIN "
    "INSERT INTO history_map(conversation_id) VALUES(new.id); "
    "INSERT INTO history_fts(rowid,text) VALUES(last_insert_rowid(),new.title); END",
    "CREATE TRIGGER history_title_edited AFTER UPDATE OF title ON conversations BEGIN "
    "UPDATE history_fts SET text=new.title WHERE rowid=(SELECT id FROM history_map "
    "WHERE conversation_id=new.id AND message_id IS NULL); END",
    "CREATE TRIGGER history_message_added AFTER INSERT ON messages BEGIN "
    "INSERT INTO history_map(conversation_id,message_id) VALUES(new.conversation_id,new.id); "
    "INSERT INTO history_fts(rowid,text) VALUES(last_insert_rowid(),new.content); END",
    "CREATE TRIGGER history_message_edited AFTER UPDATE OF content ON messages BEGIN "
    "UPDATE history_fts SET text=new.content WHERE rowid=(SELECT id FROM history_map WHERE message_id=new.id); END",
)


def initialize(conn: sqlite3.Connection) -> None:
    """Backfill once, atomically; serialize competing app starts before checking the schema marker."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_map'").fetchone():
            for statement in DDL:
                conn.execute(statement)
            conn.execute('INSERT INTO history_map(conversation_id) SELECT id FROM conversations')
            conn.execute('INSERT INTO history_map(conversation_id,message_id) SELECT conversation_id,id FROM messages')
            conn.execute('INSERT INTO history_fts(rowid,text) SELECT h.id,COALESCE(m.content,c.title) '
                         'FROM history_map h JOIN conversations c ON c.id=h.conversation_id '
                         'LEFT JOIN messages m ON m.id=h.message_id')
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _segments(raw: str, start: str, end: str) -> list[dict]:
    """Return plain text parts, never HTML. Random sentinels cannot be supplied by a stored message."""
    parts, matched, remaining = [], False, 1200
    for piece in re.split(f'({re.escape(start)}|{re.escape(end)})', raw):
        if piece in (start, end):
            matched = piece == start
        elif piece and remaining:
            parts.append({'text': piece[:remaining], 'matched': matched})
            remaining -= min(len(piece), remaining)
    if remaining == 0:
        parts.append({'text': '…', 'matched': False})
    return parts


def search(conn: sqlite3.Connection, *, query: str, scope: str = 'all', project_id: str | None = None,
           match: str = 'words', role: str = 'all', after: float = 0, limit: int = 20, offset: int = 0) -> dict:
    terms = re.findall(r'[^\W_]+', unicodedata.normalize('NFC', query), re.UNICODE)
    if not 1 <= len(query) <= 200 or not 1 <= len(terms) <= 12:
        raise ValueError('history_query')
    if (scope not in {'all', 'workspace', 'project'} or (scope == 'project') != bool(project_id)
            or match not in {'words', 'phrase'} or role not in {'all', 'user', 'assistant'}
            or not math.isfinite(after) or after < 0 or not 1 <= limit <= 50 or not 0 <= offset <= 1000):
        raise ValueError('history_filter')
    expression = ('"' + ' '.join(terms) + '"' if match == 'phrase'
                  else ' AND '.join(f'"{term}"' for term in terms))
    token = uuid.uuid4().hex
    start, end = f'[{token}S]', f'[{token}E]'
    conditions, params = ['history_fts MATCH ?'], [start, end, expression]
    if scope == 'workspace':
        conditions.append('c.project_id IS NULL')
    elif scope == 'project':
        conditions.append('c.project_id=?')
        params.append(project_id)
    if role != 'all':
        conditions.append('m.role=?')
        params.append(role)
    conditions.append('COALESCE(m.created,c.created)>=?')
    params.extend([after, limit + 1, offset])
    rows = conn.execute(
        'SELECT h.id,c.id AS conversation_id,h.message_id,c.title,c.project_id,p.name AS project_name, '
        "COALESCE(m.role,'title') AS role,COALESCE(m.created,c.created) AS created, "
        "snippet(history_fts,0,?,?,'…',32) AS excerpt FROM history_fts "
        'JOIN history_map h ON h.id=history_fts.rowid JOIN conversations c ON c.id=h.conversation_id '
        'LEFT JOIN messages m ON m.id=h.message_id LEFT JOIN projects p ON p.id=c.project_id WHERE '
        + ' AND '.join(conditions) + ' ORDER BY rank,created DESC,h.id LIMIT ? OFFSET ?', params,
    ).fetchall()
    more = len(rows) > limit and offset + limit <= 1000
    results = []
    for row in rows[:limit]:
        result = dict(row)
        result['segments'] = _segments(result.pop('excerpt'), start, end)
        results.append(result)
    return {'results': results, 'has_more': more, 'next_offset': offset + limit if more else None}
