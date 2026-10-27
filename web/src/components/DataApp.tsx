import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";

type Review = { token: string; changes: { row: number; column: number; before: string; after: string }[] };

/** The artifact can request a review, never approve it. Only this trusted host sends approval to the API. */
export function DataAppFrame({ id, title, srcDoc }: { id: string; title: string; srcDoc: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const C = t.dataApp;
  useEffect(() => {
    let active = true;
    const receive = async (event: MessageEvent) => {
      if (!frame.current?.contentWindow || event.source !== frame.current.contentWindow || saved || pending.current ||
          event.data?.type !== "spike-data-edits" || !Array.isArray(event.data.edits) || !event.data.edits.length) return;
      pending.current = true; setBusy(true); setReview(null); setError("");
      try {
        const result = await api.post<Review>(`/api/creator/data-app/${id}/preview`, { edits: event.data.edits });
        if (active) setReview(result);
      } catch { if (active) setError(C.failed); }
      finally { pending.current = false; if (active) setBusy(false); }
    };
    window.addEventListener("message", receive);
    return () => { active = false; window.removeEventListener("message", receive); };
  }, [id, saved, C.failed]);
  const approve = async () => {
    if (!review || pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      await api.post(`/api/creator/data-app/${id}/approve`, { token: review.token, approved: true });
      setSaved(true); setReview(null);
    } catch { setError(C.failed); }
    finally { pending.current = false; setBusy(false); }
  };
  return <>
    <div className="form" aria-live="polite">
      <p>{C.hint}</p>
      {busy && <p>{C.busy}</p>}
      {saved && <p>{C.saved}</p>}
      {error && <p role="alert">{error}</p>}
      {review && <section aria-label={C.review}>
        <h3>{C.review}</h3>
        <ul>{review.changes.map(c => <li key={`${c.row}:${c.column}`}>
          {C.row} {c.row + 1}, {C.column} {c.column + 1}: {c.before} → {c.after}
        </li>)}</ul>
        <button className="btn" disabled={busy} onClick={() => setReview(null)}>{C.cancel}</button>
        <button className="btn primary" disabled={busy || !review.changes.length} onClick={approve}>{C.approve}</button>
      </section>}
    </div>
    <iframe ref={frame} className="artifact-frame" title={title} sandbox="allow-scripts" srcDoc={srcDoc} referrerPolicy="no-referrer" />
  </>;
}
