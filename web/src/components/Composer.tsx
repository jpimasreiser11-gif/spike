import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import type { ProviderInfo, Specialist } from "../types";
import { IconSend, IconStop } from "./Icons";

export function Composer({ onSend, onStop, busy, mode, setMode, providerId, setProviderId, specialists, providers, followUp, autoFocus }: {
  onSend: (text: string, schema?: object) => void;
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
}) {
  const [text, setText] = useState("");
  const [format, setFormat] = useState<"text" | "json" | "schema">("text");
  const [schemaText, setSchemaText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
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

  const submit = () => {
    const value = text.trim();
    if (!value || busy || schemaProblem) return;
    onSend(value, schema);
    setText("");
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
        <select className="select" value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Specialist" title={t.autoHint}>
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
        <select className="select" value={format} onChange={(e) => setFormat(e.target.value as typeof format)} aria-label={t.answerFormat} title={t.answerFormatHint}>
          <option value="text">{t.answerFormat}: {t.formatText}</option>
          <option value="json">{t.answerFormat}: JSON</option>
          <option value="schema">{t.answerFormat}: {t.formatSchema}</option>
        </select>
        <div className="spacer" />
        {busy ? (
          <button className="send-btn stop" onClick={onStop} aria-label={t.stop} title={t.stop}>
            <IconStop />
          </button>
        ) : (
          <button className="send-btn" onClick={submit} disabled={!text.trim() || Boolean(schemaProblem)} aria-label={t.send} title={t.send}>
            <IconSend />
          </button>
        )}
      </div>
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
