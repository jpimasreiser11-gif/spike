import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";

/** One anonymised failure from the local log (G43): where, the error's type and the frames; never its message. */
export type ErrorEntry = { time: number; kind: string; where: string; type: string; errno?: string; frames: string[]; version: string };

const E = t.errorLog;

/** Settings > Errors: the latest failures recorded on this computer, a "copy as issue" text and a clear button.
 * The text is copied to the clipboard by the browser; nothing is sent. */
export function ErrorLog() {
  const [entries, setEntries] = useState<ErrorEntry[] | null>(null);
  const [path, setPath] = useState("");
  const [note, setNote] = useState("");
  const [manual, setManual] = useState("");  // the issue text, shown when the clipboard is refused
  const load = () => api.get<{ entries: ErrorEntry[]; path: string }>("/api/errors")
    .then((r) => { setEntries(r.entries); setPath(r.path); })
    .catch(() => setNote(E.loadError));
  useEffect(() => { load(); }, []);

  const copy = async () => {
    setManual("");
    let text = "";
    try {
      text = (await api.get<{ text: string }>("/api/errors/report")).text;
      await navigator.clipboard.writeText(text);
      setNote(E.copied);
    } catch {
      setNote(text ? E.copyFailed : E.loadError);
      setManual(text);
    }
  };
  const clear = async () => {
    await api.del("/api/errors");
    setManual("");
    setNote(E.cleared);
    await load();
  };

  return (
    <div className="form">
      <p className="small muted">{E.intro}</p>
      <div className="row">
        <b className="grow">{E.title}</b>
        <button className="btn small" onClick={load}>{E.refresh}</button>
        <button className="btn small" onClick={copy} disabled={!entries?.length}>{E.copy}</button>
        <button className="btn small danger" onClick={clear} disabled={!entries?.length}>{E.clear}</button>
      </div>
      {path && <small className="muted">{E.file}: <code>{path}</code></small>}
      {note && <p className="small" role="status">{note}</p>}
      {manual && <textarea className="error-log-text" readOnly rows={8} value={manual} aria-label={E.copy} />}
      {entries && entries.length === 0 ? <p className="small muted">{E.empty}</p> : (
        <ul className="error-log" aria-label={E.title}>
          {(entries ?? []).map((e, i) => (
            <li key={`${e.time}-${i}`} className="card small">
              <div className="row">
                <span className="grow"><b>{E.kinds[e.kind] ?? e.kind}</b> · <code>{e.where}</code></span>
                <span className="muted">{new Date(e.time * 1000).toLocaleString()}</span>
              </div>
              <div>{E.error}: <code>{e.type}{e.errno ? ` [${e.errno}]` : ""}</code> · <span className="muted">SPIKE {e.version}</span></div>
              {e.frames.length > 0 && (
                <details>
                  <summary>{E.frames}</summary>
                  <pre className="error-log-frames">{e.frames.join("\n")}</pre>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
