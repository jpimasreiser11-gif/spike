import { useState } from "react";
import { t } from "../i18n";
import { multiplierText, whyText } from "../parallel";
import { fill, summaryText, tone } from "../trust";
import type { MindState, MindsState } from "../types";
import { IconChevron } from "./Icons";
import { Markdown } from "./Markdown";
import { TrustBar } from "./Trust";

/** What distinguishes a mind from the others: its temperature, or the specialist and provider the user picked for it. */
function MindMeta({ mind }: { mind: MindState }) {
  const bits = [
    mind.temperature !== undefined ? fill(t.minds.temperature, { t: mind.temperature }) : "",
    ...(mind.mode ? [mind.mode] : []), ...(mind.provider_id ? [mind.provider_id] : []),
    ...(mind.elapsed !== undefined ? [fill(t.minds.seconds, { s: mind.elapsed.toFixed(1) })] : []),
  ].filter(Boolean);
  return bits.length ? <span className="muted small"> · {bits.join(" · ")}</span> : null;
}

/** One mind: its labels always visible; its answer behind the line for the minds that were not chosen (the chosen
 * mind's answer is the one above). */
function MindItem({ mind, chosen, live }: { mind: MindState; chosen: boolean; live: boolean }) {
  const [open, setOpen] = useState(false);
  const status = mind.run.status;
  const labels = mind.counts && mind.ok ? summaryText(mind.counts) || t.minds.noClaims : "";
  const state = status === "running" ? t.minds.running : status === "idle" ? t.minds.waiting : status === "error" ? t.minds.failed : "";
  const title = (
    <>
      <b>{t.minds.mind} {mind.index + 1}</b>
      {chosen && <span className="badge ok" data-mind-chosen> {t.minds.chosen}</span>}
      {labels && mind.counts && <span className={`chip trust-chip ${tone(mind.counts)}`} data-mind-labels>{labels}</span>}
      {mind.verifier_failed && <span className="badge warn"> {t.minds.checkerFailed}</span>}
      {state && <span className="muted small" data-mind-state={status}> {state}</span>}
      <MindMeta mind={mind} />
    </>
  );
  if (chosen) return <li className="trace-item mind chosen" data-mind={mind.index + 1}><div className="trace-head static">{title}</div></li>;
  return (
    <li className={`trace-item mind ${live && status === "running" ? "live" : ""}`} data-mind={mind.index + 1}>
      <button className="trace-head" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconChevron size={14} open={open} />
        <span className="trace-title">{title}</span>
      </button>
      {open && (
        <div className="trace-body">
          {mind.run.error && <p className="bad small">{mind.run.error}</p>}
          <Markdown text={mind.run.text || "…"} />
          {mind.run.trust && !live && <TrustBar trust={mind.run.trust} replay />}
        </div>
      )}
    </li>
  );
}

/** Parallel Minds under an answer: how many minds there were (×N), why this one was chosen, and the others collapsed
 * with their claim labels. */
export function MindsPanel({ minds, live }: { minds: MindsState; live: boolean }) {
  return (
    <div className="minds" data-minds role="group" aria-label={t.minds.title}>
      <div className="minds-head">
        <b>{t.minds.title}</b>
        <span className="chip" data-minds-multiplier>{multiplierText(minds.n)}</span>
      </div>
      {!live && minds.why && <p className="small muted" data-minds-why>{whyText(minds.why, minds.chosen)}</p>}
      <ul className="minds-list">
        {minds.minds.map((m) => <MindItem key={m.index} mind={m} chosen={m.index === minds.chosen} live={live} />)}
      </ul>
    </div>
  );
}
