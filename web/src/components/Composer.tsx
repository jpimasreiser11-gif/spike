import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { MAX_MINDS, MIN_MINDS, type MindPick, estimateLines, mindsSpec } from "../parallel";
import type { DesignSystemInfo, MindsEstimate, MindsSpec, ProviderInfo, Specialist } from "../types";
import { IconSend, IconStop } from "./Icons";

export function Composer({ onSend, onStop, busy, mode, setMode, providerId, setProviderId, specialists, providers, followUp, autoFocus,
  designs = [], design = "", setDesign, projectDesign, projectId, conversationId }: {
  onSend: (text: string, schema?: object, minds?: MindsSpec) => void;
  onStop: () => void;
  busy: boolean;
  mode: string;
  setMode: (m: string) => void;
  providerId: string | null;
  setProviderId: (p: string | null) => void;
  specialists: Specialist[];
  providers: ProviderInfo[];
  followUp: boolean;
  autoFocus?: boolean;
  designs?: DesignSystemInfo[];
  design?: string; // "" = the project's (or none), "none", or a design system id
  setDesign?: (d: string) => void;
  projectDesign?: string; // name of the project's design system
  projectId?: string; // for the cost estimate of Parallel Minds
  conversationId?: string | null;
}) {
  const [text, setText] = useState("");
  const [format, setFormat] = useState<"text" | "json" | "schema">("text");
  const [schemaText, setSchemaText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  // Parallel Minds: per message and off by default; it asks again after each send
  const [mindsOn, setMindsOn] = useState(false);
  const [mindsN, setMindsN] = useState(3);
  const [custom, setCustom] = useState(false);
  const [picks, setPicks] = useState<MindPick[]>(() => Array.from({ length: MAX_MINDS }, () => ({ mode: "", provider_id: "" })));
  const [estimate, setEstimate] = useState<MindsEstimate | null>(null);
  const [estimateError, setEstimateError] = useState("");
  let schema: object | undefined;
  let schemaProblem = "";
  if (format === "json") schema = { type: "object" };
  if (format === "schema") {
    try {
      const parsed = JSON.parse(schemaText);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) schema = parsed;
      else schemaProblem = t.schemaNotObject;
    } catch {
      schemaProblem = schemaText.trim() ? t.schemaNotJson : t.schemaEmpty;
    }
  }

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 320) + "px";
  }, [text]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const minds = mindsSpec(mindsOn && format === "text", mindsN, custom ? picks : null);
  const mindsKey = JSON.stringify(minds);
  useEffect(() => { // what the batch would cost, asked of the server (it calls no model) once the user stops typing
    if (!minds) { setEstimate(null); setEstimateError(""); return; }
    let current = true;
    const timer = setTimeout(() => {
      api.post<MindsEstimate>("/api/minds/estimate", { ...minds, message: text, mode, provider_id: providerId, project_id: projectId ?? null,
        conversation_id: conversationId ?? null })
        .then((e) => { if (current) { setEstimate(e); setEstimateError(""); } })
        .catch((e) => { if (current) { setEstimate(null); setEstimateError(String((e as Error).message)); } });
    }, 300);
    return () => { current = false; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mindsKey, text, mode, providerId, projectId, conversationId]);
  const blocked = estimate?.blocked ?? null;

  useEffect(() => { // a message an MCP App wrote (`ui/message`): put in the box for the user to read and send
    const onCompose = (e: Event) => {
      const value = (e as CustomEvent<string>).detail;
      if (typeof value === "string") { setText(value); ref.current?.focus(); }
    };
    window.addEventListener("spike:compose", onCompose);
    return () => window.removeEventListener("spike:compose", onCompose);
  }, []);

  const submit = () => {
    const value = text.trim();
    if (!value || busy || schemaProblem || (minds && blocked)) return;
    onSend(value, schema, minds ?? undefined);
    setText("");
    setMindsOn(false);
  };

  return (
    <div className="composer">
      <label className="sr-only" htmlFor="composer-input">{t.placeholder}</label>
      <textarea
        id="composer-input"
        ref={ref}
        value={text}
        rows={1}
        placeholder={followUp ? t.placeholderFollow : t.placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          } else if (e.key === "Escape" && busy) {
            onStop();
          }
        }}
      />
      <div className="composer-bar">
        <select className="select" value={mode} onChange={(e) => setMode(e.target.value)} aria-label={t.specialistSelect} title={t.autoHint}>
          <option value="auto">✦ {t.auto}</option>
          {specialists.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <select className="select" value={providerId ?? ""} onChange={(e) => setProviderId(e.target.value || null)} aria-label={t.provider}>
          <option value="">{t.provider}: {t.defaultProvider}</option>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>{p.name}{p.paid ? " $" : ""}</option>
          ))}
        </select>
        {setDesign && designs.length > 0 && (
          <select className="select" value={design} onChange={(e) => setDesign(e.target.value)} aria-label={t.design} title={t.designHint}>
            <option value="">{t.design}: {projectDesign ? `${t.designProject} (${projectDesign})` : t.designNone}</option>
            {projectDesign && <option value="none">{t.design}: {t.designNone}</option>}
            {designs.map((d) => <option key={d.id} value={d.id}>{t.design}: {d.name}</option>)}
          </select>
        )}
        <select className="select" value={format} onChange={(e) => setFormat(e.target.value as typeof format)} aria-label={t.answerFormat} title={t.answerFormatHint}>
          <option value="text">{t.answerFormat}: {t.formatText}</option>
          <option value="json">{t.answerFormat}: JSON</option>
          <option value="schema">{t.answerFormat}: {t.formatSchema}</option>
        </select>
        <button type="button" className={`btn small minds-toggle ${minds ? "on" : ""}`} aria-pressed={mindsOn && format === "text"} data-minds-toggle
          disabled={format !== "text"} title={format !== "text" ? t.minds.incompatible : t.minds.hint} onClick={() => setMindsOn(!mindsOn)}>
          {t.minds.label}
        </button>
        <div className="spacer" />
        {busy ? (
          <button className="send-btn stop" onClick={onStop} aria-label={t.stop} title={t.stop}>
            <IconStop />
          </button>
        ) : (
          <button className="send-btn" onClick={submit} disabled={!text.trim() || Boolean(schemaProblem) || Boolean(minds && blocked)} aria-label={t.send} title={t.send}>
            <IconSend />
          </button>
        )}
      </div>
      {minds && (
        <div className="minds-box" data-minds-box role="group" aria-label={t.minds.label}>
          <div className="row">
            <label className="field inline"><span>{t.minds.count}</span>
              <select value={mindsN} onChange={(e) => setMindsN(Number(e.target.value))} aria-label={t.minds.count}>
                {Array.from({ length: MAX_MINDS - MIN_MINDS + 1 }, (_, i) => MIN_MINDS + i).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className="check small"><input type="checkbox" checked={custom} onChange={(e) => setCustom(e.target.checked)} /> {t.minds.custom}</label>
          </div>
          {custom && picks.slice(0, mindsN).map((p, i) => (
            <div className="row minds-pick" key={i}>
              <span className="small">{t.minds.mind} {i + 1}</span>
              <select value={p.mode} aria-label={`${t.minds.mind} ${i + 1}: ${t.minds.specialist}`}
                onChange={(e) => setPicks(picks.map((x, j) => (j === i ? { ...x, mode: e.target.value } : x)))}>
                <option value="">{t.minds.specialist}: {t.minds.same}</option>
                {specialists.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <select value={p.provider_id} aria-label={`${t.minds.mind} ${i + 1}: ${t.minds.provider}`}
                onChange={(e) => setPicks(picks.map((x, j) => (j === i ? { ...x, provider_id: e.target.value } : x)))}>
                <option value="">{t.minds.provider}: {t.minds.same}</option>
                {providers.map((pr) => <option key={pr.id} value={pr.id}>{pr.name}{pr.paid ? " $" : ""}</option>)}
              </select>
            </div>
          ))}
          <div className="minds-estimate small" data-minds-estimate aria-live="polite">
            <b data-minds-multiplier>{estimateLines(estimate ?? { n: mindsN, multiplier: mindsN, multi_step: false, cost: null, unpriced: [], blocked: null, providers: [] })[0]}</b>
            {estimate ? estimateLines(estimate).slice(1).map((line) => <span key={line} className="muted"> · {line}</span>)
              : !estimateError && <span className="muted"> · {t.minds.estimating}</span>}
            {estimate?.providers.map((p) => (
              <span key={p.provider_id} className="muted" data-minds-provider={p.provider_id}> · {p.name}: {p.calls} {t.minds.calls}</span>
            ))}
            {(blocked || estimateError) && <div className="warn-text" role="alert">{t.minds.blocked}: {blocked || estimateError}</div>}
          </div>
        </div>
      )}
      {format === "schema" && (
        <div className="schema-box">
          <textarea value={schemaText} onChange={(e) => setSchemaText(e.target.value)} rows={4} spellCheck={false}
            aria-label={t.formatSchema} placeholder={'{"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}'} />
          {schemaProblem && <span className="small warn-text">{schemaProblem}</span>}
        </div>
      )}
    </div>
  );
}
