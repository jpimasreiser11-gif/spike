import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { lang } from "../i18n";
import type { McpAppUi } from "../types";

const A = lang === "es"
  ? {
      app: "App", isolated: "aislada: no ve SPIKE ni tus archivos", loading: "Cargando la vista…", unavailable: "La vista no está disponible",
      connects: "Se conecta a", blocked: "SPIKE bloqueó", wantsTool: "La app quiere usar", wantsLink: "La app quiere abrir este enlace:",
      allow: "Permitir", deny: "Denegar", open: "Abrir", cancel: "Cancelar", close: "Cerrar", composed: "La app escribió un mensaje en el cuadro de texto: revísalo antes de enviarlo.",
      context: "La app añadirá lo que muestra a tu próximo mensaje.", replay: "Vista de app (no se ejecuta al repasar)",
    }
  : {
      app: "App", isolated: "isolated: it cannot see SPIKE or your files", loading: "Loading the view…", unavailable: "The view is not available",
      connects: "Connects to", blocked: "SPIKE blocked", wantsTool: "The app wants to use", wantsLink: "The app wants to open this link:",
      allow: "Allow", deny: "Deny", open: "Open", cancel: "Cancel", close: "Close", composed: "The app wrote a message in the text box: read it before sending.",
      context: "The app will add what it shows to your next message.", replay: "App view (not run in replay)",
    };

export const PROTOCOL = "2026-01-26";
const MAX_MESSAGE = 1_000_000;
const INLINE_MAX = 720;

type Page = { uri: string; html: string; csp: Record<string, string[]>; dropped: string[]; policy: string; prefers_border: boolean | null; sha256: string };
type Rpc = { id?: string | number; method?: string; params?: Record<string, unknown>; result?: unknown; error?: unknown };
type Ask = { kind: "tool"; name: string; args: unknown } | { kind: "link"; url: string };
type Prompt = Ask & { decide: (ok: boolean) => void };

/** The view's document: SPIKE's policy in a head of its own, so it applies before any of the server's markup. */
export function appDocument(html: string, policy: string): string {
  const csp = policy.replace(/[&"<>]/g, (c) => ({ "&": "&amp;", '"': "&quot;", "<": "&lt;", ">": "&gt;" })[c]!);
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>${html}</body></html>`;
}

/** A JSON-RPC 2.0 message from a view, or null for anything malformed (which is dropped). */
export function readMessage(data: unknown): Rpc | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const m = data as Record<string, unknown>;
  if (m.jsonrpc !== "2.0") return null;
  if (m.method !== undefined && (typeof m.method !== "string" || !/^[a-z][A-Za-z0-9/_-]{0,80}$/.test(m.method))) return null;
  if (m.id !== undefined && !((typeof m.id === "number" && Number.isFinite(m.id)) || (typeof m.id === "string" && m.id.length <= 64))) return null;
  if (m.params !== undefined && (typeof m.params !== "object" || m.params === null || Array.isArray(m.params))) return null;
  if (m.method === undefined && m.id === undefined) return null;
  try {
    if (JSON.stringify(m).length > MAX_MESSAGE) return null;
  } catch {
    return null;
  }
  return m as Rpc;
}

/** Text a view gave with `ui/update-model-context`: its text blocks, then its structured content as JSON. */
export function contextText(params: Record<string, unknown> | undefined): string {
  const blocks = Array.isArray(params?.content) ? params!.content as { type?: string; text?: string }[] : [];
  const parts = blocks.filter((b) => b && b.type === "text" && typeof b.text === "string").map((b) => b.text!);
  if (params?.structuredContent && typeof params.structuredContent === "object") parts.push(JSON.stringify(params.structuredContent));
  return parts.join("\n").slice(0, 4000);
}

function hostVariables(): Record<string, string> {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    "--color-background-primary": v("--surface"), "--color-background-secondary": v("--surface-2"), "--color-text-primary": v("--text"),
    "--color-text-secondary": v("--text-2"), "--color-text-tertiary": v("--text-3"), "--color-border-primary": v("--border"),
    "--color-text-danger": v("--danger"), "--color-text-warning": v("--warn"), "--color-ring-primary": v("--accent"),
    "--font-sans": getComputedStyle(document.body).fontFamily, "--border-radius-md": "9px", "--border-radius-lg": "12px",
  };
}

/** An MCP App (SEP-1865) next to a tool's result: the server's page in an opaque-origin sandbox, talking to SPIKE
 * only through the JSON-RPC messages below. Calls to the server go through SPIKE's API, which keeps them to this
 * connector, applies the tool's policy and logs them; links, chat messages and context need the user. */
export function McpAppView({ ui, args, readOnly }: { ui: McpAppUi; args: Record<string, unknown>; readOnly?: boolean }) {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [height, setHeight] = useState(160);
  const [mode, setMode] = useState<"inline" | "fullscreen">("inline");
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [notice, setNotice] = useState("");
  const frame = useRef<HTMLIFrameElement>(null);
  const ready = useRef(false);
  const modes = useRef<string[]>([]);
  const current = useRef({ ui, args, mode }); // read by the message handler, which lives as long as the page
  current.current = { ui, args, mode };
  const base = `/api/connectors/${encodeURIComponent(ui.connector)}/view`;

  useEffect(() => {
    if (readOnly) return;
    api.get<Page>(`${base}?uri=${encodeURIComponent(ui.uri)}`).then(setPage).catch((e) => setError((e as Error).message));
  }, [base, ui.uri, readOnly]);

  useEffect(() => {
    if (!page) return;
    const post = (msg: object) => frame.current?.contentWindow?.postMessage({ jsonrpc: "2.0", ...msg }, "*"); // an opaque origin has no name
    const event = (kind: string, detail: string) => api.post(`${base}/event`, { view: ui.uri, event: kind, detail: detail.slice(0, 4000) }).catch(() => {});
    const ask = (p: Ask) => new Promise<boolean>((resolve) => setPrompt({ ...p, decide: (ok: boolean) => { setPrompt(null); resolve(ok); } }));

    const handle = async (m: Rpc): Promise<unknown> => {
      const p = m.params ?? {};
      const { mode } = current.current;
      switch (m.method) {
        case "ui/initialize": {
          const caps = (p.appCapabilities ?? {}) as { availableDisplayModes?: string[] };
          modes.current = Array.isArray(caps.availableDisplayModes) ? caps.availableDisplayModes : [];
          return {
            protocolVersion: PROTOCOL, hostInfo: { name: "SPIKE", version: "0.1.0" },
            hostCapabilities: { openLinks: {}, serverTools: {}, serverResources: {}, logging: {}, sandbox: { permissions: {}, csp: page.csp } },
            hostContext: {
              toolInfo: { tool: { name: ui.tool } }, theme: document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light",
              styles: { variables: hostVariables() }, displayMode: mode, availableDisplayModes: ["inline", "fullscreen"],
              containerDimensions: { maxHeight: INLINE_MAX }, locale: navigator.language, timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              userAgent: "SPIKE", platform: "web",
            },
          };
        }
        case "ping":
          return {};
        case "tools/call": {
          const body = { view: ui.uri, name: String(p.name ?? ""), arguments: (p.arguments ?? {}) as object };
          let answer = await api.post<{ result?: unknown; needs_approval?: boolean }>(`${base}/call`, body);
          if (answer.needs_approval) { // the tool's policy is "ask": only the user's click lets it run
            if (!(await ask({ kind: "tool", name: body.name, args: body.arguments }))) {
              event("refused", `tools/call ${body.name}`);
              throw new Error("the user denied this call");
            }
            answer = await api.post(`${base}/call`, { ...body, approved: true });
          }
          return answer.result;
        }
        case "resources/read":
          return await api.post(`${base}/read`, { view: ui.uri, uri: String(p.uri ?? "") });
        case "ui/open-link": {
          const url = String(p.url ?? "");
          if (!/^https?:\/\/[^\s]+$/i.test(url)) throw new Error("Invalid URL");
          if (!(await ask({ kind: "link", url }))) throw new Error("Link opening denied by user");
          event("open-link", url);
          window.open(url, "_blank", "noopener,noreferrer");
          return {};
        }
        case "ui/message": {
          const content = p.content as { type?: string; text?: string } | undefined;
          const text = content?.type === "text" && typeof content.text === "string" ? content.text.slice(0, 20_000) : "";
          if (!text) throw new Error("Invalid message format");
          event("message", text);
          window.dispatchEvent(new CustomEvent("spike:compose", { detail: text })); // the user still sends it
          setNotice(A.composed);
          return {};
        }
        case "ui/update-model-context": {
          const text = contextText(p);
          event("model-context", text);
          window.dispatchEvent(new CustomEvent("spike:view-context", { detail: { view: ui.uri, name: ui.connector_name, text } }));
          setNotice(text ? A.context : "");
          return {};
        }
        case "ui/request-display-mode": {
          const want = String(p.mode ?? "");
          const next = (want === "inline" || want === "fullscreen") && modes.current.includes(want) ? want : mode;
          if (next !== mode) {
            setMode(next as "inline" | "fullscreen");
            event("display-mode", next);
            post({ method: "ui/notifications/host-context-changed", params: { displayMode: next } });
          }
          return { mode: next };
        }
        default:
          throw Object.assign(new Error(`SPIKE does not support '${m.method}'`), { code: -32601 });
      }
    };

    const onMessage = (e: MessageEvent) => {
      if (!frame.current || e.source !== frame.current.contentWindow) return; // only this view's frame
      const m = readMessage(e.data);
      if (!m || !m.method) return; // malformed, or an answer to a request of ours
      if (m.id === undefined) {
        if (m.method === "ui/notifications/initialized" && !ready.current) {
          ready.current = true;
          post({ method: "ui/notifications/tool-input", params: { arguments: current.current.args } });
          if (ui.result) post({ method: "ui/notifications/tool-result", params: ui.result });
        } else if (m.method === "ui/notifications/size-changed") {
          const h = Number((m.params ?? {}).height);
          if (Number.isFinite(h)) setHeight(Math.max(60, Math.min(INLINE_MAX, Math.ceil(h))));
        } else if (m.method === "notifications/message") {
          console.info("[mcp-app]", ui.connector, (m.params ?? {}).data);
        }
        return;
      }
      handle(m).then(
        (result) => post({ id: m.id, result }),
        (err: Error & { code?: number }) => post({ id: m.id, error: { code: err.code ?? -32000, message: err.message.slice(0, 500) } }),
      );
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (ready.current) post({ id: "teardown", method: "ui/resource-teardown", params: { reason: "closed" } });
    };
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  if (readOnly) return <div className="mcp-app small muted">{A.replay} · {ui.connector_name}</div>;
  const domains = Object.values(page?.csp ?? {}).flat();
  return (
    <div className={`mcp-app ${mode === "fullscreen" ? "fullscreen" : ""}`} role="group" aria-label={`${A.app} ${ui.connector_name}`}>
      <div className="mcp-app-head">
        <b>{A.app} · {ui.connector_name}</b>
        <span className="muted small" title={page ? `sha256 ${page.sha256}` : ""}>{ui.uri} · {A.isolated}</span>
        {mode === "fullscreen" && <button className="btn small" onClick={() => setMode("inline")}>{A.close}</button>}
      </div>
      {domains.length > 0 && <div className="small warn-text">{A.connects}: {domains.join(", ")}</div>}
      {page && page.dropped.length > 0 && <div className="small muted">{A.blocked}: {page.dropped.join(", ")}</div>}
      {error ? <div className="small bad">{A.unavailable}: {error}</div> : !page ? <div className="small muted">{A.loading}</div> : (
        // allow-scripts only: an opaque origin, so the page cannot read SPIKE's storage or cookies, call its API
        // (its CSP also blocks it) or touch this window; no forms, popups, top navigation or device permissions
        <iframe ref={frame} className={`mcp-app-frame ${page.prefers_border === false ? "borderless" : ""}`} title={`${ui.connector_name}: ${ui.uri}`}
          sandbox="allow-scripts" srcDoc={appDocument(page.html, page.policy)} referrerPolicy="no-referrer"
          style={mode === "inline" ? { height } : undefined} />
      )}
      {prompt && (
        <div className="permission" role="alertdialog">
          {prompt.kind === "tool" ? (<>
            <div className="permission-title">{A.wantsTool} <code>{prompt.name}</code> ({ui.connector_name})</div>
            <pre className="permission-args">{JSON.stringify(prompt.args, null, 2)}</pre>
          </>) : (<>
            <div className="permission-title">{A.wantsLink}</div>
            <code className="small">{prompt.url}</code>
          </>)}
          <div className="permission-actions">
            <button className="btn primary" onClick={() => prompt.decide(true)}>{prompt.kind === "tool" ? A.allow : A.open}</button>
            <button className="btn danger" onClick={() => prompt.decide(false)}>{prompt.kind === "tool" ? A.deny : A.cancel}</button>
          </div>
        </div>
      )}
      {notice && <div className="small muted">{notice}</div>}
    </div>
  );
}
