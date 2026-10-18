import { createContext, useMemo, useState } from "react";
import { t } from "../i18n";
import { IconClose, IconDownload } from "./Icons";

export type ArtifactDoc = { title: string; html: string; filename: string };

/** Opens a page in the artifact panel; provided by App. */
export const ArtifactContext = createContext<((doc: ArtifactDoc) => void) | null>(null);

/** An artifact may only use what it carries inline: it can reach no server, SPIKE's API included. */
export const ARTIFACT_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
  "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'";

/** The page goes after a head that carries the policy, so the policy applies before any of its markup is parsed. */
export function artifactDocument(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${ARTIFACT_CSP}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>${html}</body></html>`;
}

export function artifactFromCode(code: string, lang: string): ArtifactDoc {
  const title = /<title>([^<]{1,80})<\/title>/i.exec(code)?.[1]?.trim() || /<h1[^>]*>([^<]{1,80})<\/h1>/i.exec(code)?.[1]?.trim() || t.artifact;
  const slug = title.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "artifact";
  return { title, html: code, filename: `${slug}.${lang === "svg" ? "svg" : "html"}` };
}

export function ArtifactPanel({ doc, onClose }: { doc: ArtifactDoc; onClose: () => void }) {
  const [view, setView] = useState<"preview" | "code">("preview");
  const srcDoc = useMemo(() => artifactDocument(doc.html), [doc.html]);
  const download = () => {
    const type = doc.filename.endsWith(".svg") ? "image/svg+xml" : "text/html";
    const url = URL.createObjectURL(new Blob([doc.html], { type }));
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <aside className="artifact-panel" aria-label={t.artifact}>
      <header className="artifact-head">
        <div className="artifact-title">
          <b>{doc.title}</b>
          <span className="muted small">{t.artifactIsolated}</span>
        </div>
        <div className="seg" role="tablist">
          <button role="tab" aria-selected={view === "preview"} className={view === "preview" ? "on" : ""} onClick={() => setView("preview")}>{t.preview}</button>
          <button role="tab" aria-selected={view === "code"} className={view === "code" ? "on" : ""} onClick={() => setView("code")}>{t.code}</button>
        </div>
        <button className="icon-btn" onClick={download} aria-label={t.download} title={t.download}><IconDownload size={17} /></button>
        <button className="icon-btn" onClick={onClose} aria-label={t.close} title={t.close}><IconClose size={17} /></button>
      </header>
      {view === "preview" ? (
        // allow-scripts without allow-same-origin: the page gets an opaque origin, so it cannot read SPIKE's
        // storage or cookies, call its API with them, or touch this window; no forms, popups or top navigation.
        <iframe key={srcDoc} className="artifact-frame" title={doc.title} sandbox="allow-scripts" srcDoc={srcDoc} referrerPolicy="no-referrer" />
      ) : (
        <pre className="artifact-code"><code>{doc.html}</code></pre>
      )}
    </aside>
  );
}
