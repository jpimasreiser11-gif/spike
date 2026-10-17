import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { DesignSystemInfo } from "../types";
import { artifactDocument } from "./Artifact";
import { IconTrash, IconUpload } from "./Icons";

const D = lang === "es"
  ? {
      intro: "Un sistema de diseño es un DESIGN.md (estilo, colores, tipografía, componentes) y sus tokens CSS. Elígelo en el chat o en un proyecto y las páginas, presentaciones y documentos que haga SPIKE lo siguen.",
      importDesign: "Importar DESIGN.md o .zip", importHint: "Sirve un DESIGN.md suelto o un .zip con DESIGN.md y tokens.css (como los paquetes de open-design o awesome-design-md). Los tokens no pueden cargar nada de internet.",
      bundled: "incluido", user: "tuyo", preview: "Vista previa", hide: "Ocultar", remove: "Eliminar", imported: "Importado", noTokens: "sin tokens.css",
      credit: "Los sistemas incluidos, salvo SPIKE, vienen de open-design (Apache-2.0); no se incluye ninguno que imite la marca de una empresa.",
    }
  : {
      intro: "A design system is a DESIGN.md (style, colours, type, components) and its CSS tokens. Pick one in the chat or in a project and the pages, slides and documents SPIKE makes follow it.",
      importDesign: "Import DESIGN.md or .zip", importHint: "A single DESIGN.md, or a .zip with DESIGN.md and tokens.css (like open-design or awesome-design-md packages). Tokens cannot load anything from the internet.",
      bundled: "built-in", user: "yours", preview: "Preview", hide: "Hide", remove: "Remove", imported: "Imported", noTokens: "no tokens.css",
      credit: "Built-in systems other than SPIKE come from open-design (Apache-2.0); none that imitates a company's brand is included.",
    };

function Preview({ id }: { id: string }) {
  const [html, setHtml] = useState("");
  useEffect(() => { api.get<{ html: string }>(`/api/design-systems/${id}/preview`).then((r) => setHtml(r.html)); }, [id]);
  const srcDoc = useMemo(() => (html ? artifactDocument(html) : ""), [html]);
  // the same isolation as the artifact panel: scripts in an opaque origin, nothing loaded from anywhere
  return srcDoc ? <iframe className="design-frame" title={id} sandbox="allow-scripts" srcDoc={srcDoc} referrerPolicy="no-referrer" /> : null;
}

/** Settings › Design: the design systems SPIKE knows, their colours and a sample page; import and remove yours. */
export function DesignSystems({ onChange }: { onChange?: () => void }) {
  const [systems, setSystems] = useState<DesignSystemInfo[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const load = () => api.get<DesignSystemInfo[]>("/api/design-systems").then(setSystems).catch((e) => setErr(String(e.message)));
  useEffect(() => { load(); }, []);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setErr(""); setMsg("");
    try {
      const r = await api.upload<{ imported: DesignSystemInfo[] }>("POST", "/api/design-systems/import", file);
      setMsg(`${D.imported}: ${r.imported.map((d) => d.name).join(", ")}`);
      onChange?.();
    } catch (e) { setErr(String((e as Error).message)); }
    if (input.current) input.current.value = "";
    load();
  };

  const remove = async (id: string) => {
    await api.del(`/api/design-systems/${id}`);
    onChange?.();
    load();
  };

  return (
    <div className="form">
      <p className="small muted">{D.intro}</p>
      <div className="row">
        <button className="btn" onClick={() => input.current?.click()}><IconUpload size={14} /> {D.importDesign}</button>
        <input ref={input} type="file" accept=".md,.zip,text/markdown" hidden data-testid="design-import" onChange={(e) => upload(e.target.files?.[0])} />
      </div>
      <small className="muted">{D.importHint}</small>
      {msg && <div className="flash-box">{msg}</div>}
      {err && <div className="error-box" role="alert">{err}</div>}
      {systems.map((d) => (
        <div key={d.id} className="card design-card" data-design={d.id}>
          <div className="card-head">
            <b>{d.name}</b>
            <span className="badge">{d.source === "user" ? D.user : D.bundled}</span>
            {d.category && <span className="badge">{d.category}</span>}
            {!d.has_tokens && <span className="badge">{D.noTokens}</span>}
            <div className="spacer" />
            <button className="btn small" onClick={() => setOpen(open === d.id ? null : d.id)}>{open === d.id ? D.hide : D.preview}</button>
            {d.source === "user" && <button className="icon-btn" aria-label={`${D.remove}: ${d.name}`} onClick={() => remove(d.id)}><IconTrash size={14} /></button>}
          </div>
          {d.description && <p className="small">{d.description}</p>}
          <div className="swatches" aria-hidden="true">
            {d.colors.map((c) => <span key={c.name} className="swatch" style={{ background: c.value }} title={`${c.name} ${c.value}`} />)}
          </div>
          {open === d.id && <Preview id={d.id} />}
        </div>
      ))}
      <small className="muted">{D.credit}</small>
    </div>
  );
}
