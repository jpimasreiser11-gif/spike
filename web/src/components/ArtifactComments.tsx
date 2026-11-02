import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";

type Comment = { id: string; line: number; text: string; parent: string | null };

export function ArtifactComments({ content, title }: { content: string; title: string }) {
  const [version, setVersion] = useState("");
  const [comments, setComments] = useState<Comment[]>([]);
  const [line, setLine] = useState(1);
  const [draft, setDraft] = useState("");
  const [parent, setParent] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(false);
  // Register only when the user opens this panel, not every time an artifact is previewed.
  useEffect(() => {
    let live = true;
    api.post<{ id: string }>("/api/artifact-versions", { content, title }).then(async (v) => {
      const rows = await api.get<Comment[]>(`/api/artifact-versions/${v.id}/comments`);
      if (live) { setVersion(v.id); setComments(rows); }
    }).catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [content, title]);
  return <section className="artifact-comments" aria-label={t.artifactComments}>
    <p>{t.commentsHint}</p>
    {error && <p role="alert">{error}</p>}
    {comments.filter((c) => !c.parent).map((c) => <article key={c.id}>
      <b>{t.commentLine} {c.line}</b><p>{c.text}</p>
      {comments.filter((r) => r.parent === c.id).map((r) => <blockquote key={r.id}>{r.text}</blockquote>)}
      <button className="btn" onClick={() => { setParent(c.id); setLine(c.line); }}>{t.replyComment}</button>
      <button className="btn" onClick={() => {
        window.dispatchEvent(new CustomEvent("spike-comment-context", { detail: c.id })); setSelected(true);
      }}>{t.useComments}</button>
    </article>)}
    {selected && <p role="status">{t.commentsSelected}</p>}
    <form onSubmit={async (e) => {
      e.preventDefault();
      try {
        await api.post(`/api/artifact-versions/${version}/comments`, { line, text: draft, parent });
        setComments(await api.get(`/api/artifact-versions/${version}/comments`)); setDraft(""); setParent(null);
      } catch (err) { setError((err as Error).message); }
    }}>
      <label>{t.commentLine}<input type="number" min={1} max={content.split(/\n/).length} value={line} disabled={!!parent} onChange={(e) => setLine(Number(e.target.value))} /></label>
      <label>{t.commentText}<textarea value={draft} onChange={(e) => setDraft(e.target.value)} /></label>
      {parent && <button type="button" className="btn" onClick={() => setParent(null)}>{t.cancel}</button>}
      <button className="btn" disabled={!version || !draft.trim()}>{t.saveComment}</button>
    </form>
  </section>;
}
