import { useContext, useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { ArtifactContext, artifactFromCode } from "./Artifact";
import { IconFile } from "./Icons";
import "./ArtifactFiles.css";

export type ArtifactFile = { path: string; ok: boolean; bytes?: number };
export const MAX_PREVIEW_BYTES = 1024 * 1024;
const TEXT_FILE = /\.(txt|md|markdown|csv|tsv|json|jsonl|yaml|yml|toml|xml|log|py|js|jsx|ts|tsx|css|scss|sql|sh|rs|go|java|c|h|cpp)$/i;
const PAGE_FILE = /\.(html?|svg)$/i;

/** Download a workspace file through the existing route; each filename segment stays one URL segment. */
export const fileUrl = (path: string, projectId?: string) =>
  `${projectId ? `/api/projects/${encodeURIComponent(projectId)}/files` : "/api/workspace/files"}/${path.split("/").map(encodeURIComponent).join("/")}`;

function relativePath(path: string): boolean {
  return !!path && !/[\\\u0000-\u001f\u007f]/.test(path) && !path.split("/").some((p) => !p || p === "." || p === "..");
}

/** Decode bounded UTF-8, counting the stream too: Content-Length may be absent or describe a compressed response. */
async function previewText(response: Response): Promise<string> {
  if (Number(response.headers.get("Content-Length")) > MAX_PREVIEW_BYTES) {
    await response.body?.cancel();
    throw new Error("preview-too-large");
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0, text = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_PREVIEW_BYTES) throw new Error("preview-too-large");
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    if (text.includes("\0")) throw new Error("preview-not-text");
    return text;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** Files reported by a tool or checked by Forge. A preview reads only after a click; replay never reads current files.
 * HTML/SVG uses the existing isolated panel. Other text is rendered literally, without interpreting markup. */
export function ArtifactFiles({ files, projectId, replay = false, urlFor }: {
  files: ArtifactFile[]; projectId?: string; replay?: boolean; urlFor?: (path: string) => string; // urlFor: another root, e.g. a Dev folder
}) {
  const urlOf = (path: string) => (urlFor ? urlFor(path) : fileUrl(path, projectId));
  const openArtifact = useContext(ArtifactContext);
  const [preview, setPreview] = useState<{ path: string; loading?: boolean; text?: string; error?: string } | null>(null);
  const active = useRef<{ id: number; controller?: AbortController }>({ id: 0 });
  const scope = JSON.stringify([projectId, replay, files.map((f) => [f.path, f.ok])]);
  useEffect(() => {
    setPreview(null);
    return () => { active.current.id += 1; active.current.controller?.abort(); };
  }, [scope]);

  const show = async (file: ArtifactFile) => {
    if (replay || !file.ok || !relativePath(file.path)) return;
    active.current.controller?.abort();
    const id = ++active.current.id;
    const controller = new AbortController(); active.current.controller = controller;
    setPreview({ path: file.path, loading: true });
    try {
      const response = await fetch(urlOf(file.path), { signal: controller.signal, redirect: "error" });
      if (id !== active.current.id) { await response.body?.cancel(); return; }
      if (!response.ok) { await response.body?.cancel(); throw new Error("preview-unavailable"); }
      const text = await previewText(response);
      if (id !== active.current.id) return;
      if (PAGE_FILE.test(file.path) && openArtifact) {
        openArtifact({ ...artifactFromCode(text, /\.svg$/i.test(file.path) ? "svg" : "html"), filename: file.path.split("/").pop()! });
        setPreview(null);
      } else setPreview({ path: file.path, text });
    } catch (e) {
      if (id !== active.current.id) return;
      setPreview({ path: file.path, error: (e as Error).message === "preview-too-large" ? t.artifactFiles.tooLarge : t.artifactFiles.failed });
    }
  };

  return <section className="artifact-files" aria-label={t.filesCreated}>
    <ul>
      {files.map((file) => {
        const enabled = file.ok && relativePath(file.path) && !replay;
        const current = preview?.path === file.path ? preview : null;
        const canPreview = TEXT_FILE.test(file.path) || PAGE_FILE.test(file.path);
        return <li key={file.path} data-artifact-file={file.path}>
          <div className="artifact-file-row">
            <IconFile size={16} />
            {enabled ? <a href={urlOf(file.path)} download title={`${t.download}: ${file.path}`}>{file.path}</a> : <code>{file.path}</code>}
            {!file.ok && <span className="small bad">{t.fileMissing}</span>}
            {file.ok && file.bytes !== undefined && <span className="small muted">{file.bytes} B</span>}
            {enabled && canPreview && <button type="button" className="btn small" disabled={current?.loading}
              onClick={() => show(file)} aria-label={`${current?.error ? t.artifactFiles.retry : t.preview}: ${file.path}`}>
              {current?.loading ? t.artifactFiles.loading : current?.error ? t.artifactFiles.retry : t.preview}
            </button>}
          </div>
          {current?.error && <p className="small bad" role="alert">{current.error}</p>}
          {current?.text !== undefined && <div className="artifact-file-text">
            <div className="row"><span className="small muted">{t.artifactFiles.plainText}</span>
              <button type="button" className="link-btn small" onClick={() => setPreview(null)}>{t.close}</button></div>
            <pre tabIndex={0} aria-label={`${t.preview}: ${file.path}`}>{current.text}</pre>
          </div>}
        </li>;
      })}
    </ul>
    {!replay && files.some((f) => f.ok) && <p className="artifact-file-hint small muted">{t.artifactFiles.hint}</p>}
  </section>;
}
