import { DESKTOP_STRINGS, actionLabel, decisionText, recordAction } from "../desktop";
import type { DesktopRecord } from "../desktop";
import { lang } from "../i18n";

const D = DESKTOP_STRINGS[lang];

// ------------------------------------------------------------------ in a chat
/** A stored desktop task in its chat: how it went and every action with what the user decided (never images). */
export function DesktopRecordView({ record }: { record: DesktopRecord }) {
  return (
    <div className="dsk-record card" data-testid="desktop-record">
      <div className="card-head">
        <b>{D.summary(record.steps, D.reasons[record.reason] ?? record.reason)}</b>
        <span className="muted small">{record.provider}{record.model ? ` · ${record.model}` : ""}</span>
      </div>
      {record.actions.length > 0 && (
        <ol className="dsk-actions small">
          {record.actions.map((a, i) => (
            <li key={i} className={a.ok ? "" : "bad"}>
              {actionLabel(recordAction(a), D)} — {decisionText(a.decision, D)} · {a.ok ? D.resultOk : D.resultFailed}
              {a.sensitive ? ` · ${D.sensitive[a.sensitive] ?? a.sensitive}` : ""}
            </li>
          ))}
        </ol>
      )}
      {record.error && <div className="error-box" role="alert">{record.error}</div>}
      <small className="muted">
        {(record.usage.input + record.usage.output).toLocaleString()} {D.tokens} · {record.screenshots === "kept" ? D.shotsKept : D.shotsNot}
      </small>
    </div>
  );
}
