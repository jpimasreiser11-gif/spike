import { useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { citationText, fill, money, offerNotes, summaryText, tone } from "../trust";
import type { ClaimState, Escalation as EscalationState, TrustState } from "../types";
import { Markdown } from "./Markdown";

/** One claim: its badge, the rule that gave the label and, when there are citations, what the check of each found. */
function Claim({ c }: { c: ClaimState }) {
  return (
    <li className="claim" data-claim-label={c.label} data-claim-why={c.why}>
      <span className={`badge claim-badge ${c.label}`}>{t.trust.badge[c.label]}</span>
      <div className="claim-body">
        <span className="claim-text">{c.text}</span>
        <span className="muted small"> · {t.trust.why[c.why] ?? c.why}{c.downgraded ? ` · ${t.trust.lowered}` : ""}</span>
        {(c.citations ?? []).map((x, i) => (
          <div key={i} className={`citation small ${x.ok ? "ok-text" : "bad"}`} data-citation={x.status}>
            <span aria-hidden>{x.ok ? "✓" : "✕"}</span> {citationText(x)}
            {x.found !== undefined && x.found < 1 && <span className="muted"> · {t.trust.citation.match} {Math.round(x.found * 100)} %</span>}
            {!x.ok && x.fragment && <div className="muted fragment">{t.trust.citation.sourceSays}: «{x.fragment}»</div>}
          </div>
        ))}
        {(c.citations ?? []).length === 0 && c.label === "verified" && (c.basis ?? []).length > 0 && (
          <div className="muted small">{(c.basis ?? []).map((b) => b.label).filter(Boolean).join(" · ")}</div>
        )}
      </div>
    </li>
  );
}

/** The second opinion: shown for a low-confidence answer. Nothing is sent until the button for a provider is pressed. */
function Escalation({ initial, messageId }: { initial: EscalationState; messageId?: string }) {
  const [esc, setEsc] = useState(initial);
  const [asking, setAsking] = useState<string | null>(null);
  const [error, setError] = useState("");
  const e = t.trust.escalate;
  const ask = async (providerId: string) => {
    if (!messageId) return;
    setAsking(providerId); setError("");
    try {
      setEsc(await api.post<EscalationState>(`/api/messages/${messageId}/escalate`, { provider_id: providerId }));
    } catch (err) {
      setError(`${e.failed}: ${(err as Error).message}`);
    } finally {
      setAsking(null);
    }
  };
  const reasons = esc.reasons.map((r) => (r === "unchecked" ? fill(e.unchecked, { n: esc.unchecked, threshold: esc.threshold }) : e.verifier));
  const answer = esc.answer;
  return (
    <div className="escalation" data-escalation={esc.status} role="group" aria-label={e.title}>
      <div className="escalation-head"><b>{e.title}</b><span className="muted small"> · {reasons.join(" · ")}</span></div>
      {answer ? (
        <div className="second-opinion" data-second-opinion>
          <div className="small"><b>{fill(e.answerFrom, { name: answer.name })}</b>
            <span className="muted"> · {answer.model && `${answer.model} · `}{fill(e.used, { in: answer.tokens_in, out: answer.tokens_out })}
              {answer.estimated && ` (${e.estimatedTokens})`}{answer.cost !== null && ` · ${fill(e.costUsed, { cost: money(answer.cost) })}`}
              {answer.files_withheld > 0 && ` · ${e.withheld}: ${answer.files_withheld}`}</span></div>
          <Markdown text={answer.text} />
        </div>
      ) : (
        <>
          <p className="small muted">{e.hint}</p>
          <p className="small muted">{e.sends}</p>
          {esc.offers.map((o) => (
            <div key={o.provider_id} className="offer" data-offer={o.provider_id}>
              <button className="btn" disabled={asking !== null || !!o.blocked || !messageId}
                title={o.blocked ?? o.model} onClick={() => ask(o.provider_id)}>
                {asking === o.provider_id ? fill(e.asking, { name: o.name }) : fill(e.ask, { name: o.name })}
              </button>
              <span className="small muted">{o.model && `${o.model} · `}{o.paid && `${e.paid} · `}{offerNotes(o).join(" · ")}</span>
              {o.blocked && <div className="small warn-text">{e.blocked}: {o.blocked}</div>}
            </div>
          ))}
        </>
      )}
      {(error || esc.error) && <div className="bad small" role="alert">{error || `${e.failed}: ${esc.error}`}</div>}
    </div>
  );
}

/** Under an answer: the summary chip, the toggle that shows each claim's badge and checks, and the offer of a second
 * opinion when the answer has low confidence. */
export function TrustBar({ trust, messageId, replay }: { trust: TrustState; messageId?: string; replay?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!trust.claims.length) return null;
  return (
    <div className="trust" data-trust>
      <div className="trust-bar">
        <span className={`chip trust-chip ${tone(trust.counts)}`} data-trust-summary tabIndex={0} title={t.trust.summaryHint}
          aria-label={`${t.trust.chip}: ${summaryText(trust.counts)}`}>{summaryText(trust.counts)}</span>
        <button type="button" className="link-btn small" aria-expanded={open} data-trust-toggle onClick={() => setOpen(!open)}>
          {open ? t.trust.hide : t.trust.show}
        </button>
      </div>
      {open && (
        <div className="trust-detail">
          <ul className="claims" aria-label={t.trust.chip}>
            {trust.claims.map((c) => <Claim key={c.id} c={c} />)}
          </ul>
          {trust.skipped ? <p className="muted small">{trust.skipped} {t.trust.skipped}</p> : null}
          {trust.model_pass && <p className="muted small">{trust.model_pass.ran ? fill(t.trust.modelPass, { n: trust.model_pass.lowered ?? 0 }) : t.trust.modelPassFailed}</p>}
        </div>
      )}
      {trust.escalation && !replay && <Escalation initial={trust.escalation} messageId={messageId} />}
    </div>
  );
}
