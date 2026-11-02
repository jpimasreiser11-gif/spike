import "./ProofDownload.css";
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { IconDownload } from "./Icons";

/** The owner chooses complete sections; chat events can themselves contain private text and filenames. */
export function ProofDownload({ conversationId }: { conversationId: string }) {
  const [selected, setSelected] = useState<string[]>(["environment"]);
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  const sections = [["chat", t.proofChat], ["calls", t.proofCalls], ["files", t.proofFiles],
    ["providers", t.proofProviders], ["settings", t.proofSettings], ["environment", t.proofEnvironment]];
  const include = sections.map(([key]) => key).filter(key => selected.includes(key)).join(",");

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      const el = detailsRef.current;
      if (el?.open && event.target instanceof Node && !el.contains(event.target)) {
        el.open = false;
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  return <details
    ref={detailsRef}
    className="proof-download"
    onKeyDown={event => {
      if (event.key === "Escape" && detailsRef.current?.open) {
        event.preventDefault();
        event.stopPropagation();
        detailsRef.current.open = false;
        summaryRef.current?.focus();
      }
    }}>
    <summary ref={summaryRef} className="icon-btn" title={t.proofHint} aria-label={t.proofChoose}><IconDownload /></summary>
    <fieldset>
      <legend>{t.proofChoose}</legend>
      <p>{t.proofSelectionHint}</p>
      {sections.map(([key, label]) => <label className="row" key={key}>
        <input type="checkbox" value={key} checked={selected.includes(key)} onChange={event =>
          setSelected(current => event.target.checked ? [...current, key] : current.filter(value => value !== key))} />
        {label}
      </label>)}
      <a className="btn" href={`/api/conversations/${encodeURIComponent(conversationId)}/proof?include=${encodeURIComponent(include)}`}
        download>{t.proof}</a>
    </fieldset>
  </details>;
}
