import { useContext, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { PermissionState, RunState, Specialist } from "../types";
import { ArtifactContext, artifactFromCode } from "./Artifact";
import { IconChevron, IconCopy, IconFile, IconTool } from "./Icons";
import { Markdown } from "./Markdown";
import { SpecMark } from "./SpecMark";

function Collapsible({ title, children, defaultOpen = false, live = false }: {
  title: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  live?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`trace-item ${live ? "live" : ""}`}>
      <button className="trace-head" onClick={() => setOpen(!open)} aria-expanded={open} type="button">
        <IconChevron size={14} open={open} />
        <span className="trace-title">{title}</span>
      </button>
      {open && <div className="trace-body">{children}</div>}
    </div>
  );
}

function Permission({ p, onDecided }: { p: PermissionState; onDecided: (id: string, d: PermissionState["status"]) => void }) {
  const decide = async (decision: "allow_once" | "allow_always" | "deny") => {
    onDecided(p.id, "sending");
    try {
      await api.post(`/api/permissions/${p.id}`, { decision });
    } catch {
      onDecided(p.id, "pending");
    }
  };
  if (p.status !== "pending" && p.status !== "sending") {
    return (
      <div className="permission done">
        <IconTool size={14} /> <code>{p.tool}</code> · {p.status === "deny" ? t.denied : t.allowed}
      </div>
    );
  }
  return (
    <div className="permission" role="alertdialog" aria-label={`${p.tool} ${t.permissionAsk}`}>
      <div className="permission-title">
        <IconTool size={16} /> SPIKE {t.permissionAsk}: <code>{p.tool}</code>
        <span className={`risk risk-${p.risk}`}>{p.risk}</span>
      </div>
      <pre className="permission-args">{JSON.stringify(p.arguments, null, 2)}</pre>
      <div className="permission-actions">
        <button className="btn primary" disabled={p.status === "sending"} onClick={() => decide("allow_once")}>{t.allowOnce}</button>
        <button className="btn" disabled={p.status === "sending"} onClick={() => decide("allow_always")}>{t.allowAlways}</button>
        <button className="btn danger" disabled={p.status === "sending"} onClick={() => decide("deny")}>{t.deny}</button>
      </div>
    </div>
  );
}

/** Download URL of a file a tool wrote: in the project's folder, or in the workspace. */
export const fileUrl = (path: string, projectId?: string) =>
  `${projectId ? `/api/projects/${projectId}/files` : "/api/workspace/files"}/${path.split("/").map(encodeURIComponent).join("/")}`;

function Files({ files, projectId }: { files: string[]; projectId?: string }) {
  const openArtifact = useContext(ArtifactContext);
  const preview = async (path: string) => {
    const r = await fetch(fileUrl(path, projectId));
    if (r.ok && openArtifact) openArtifact({ ...artifactFromCode(await r.text(), path.endsWith(".svg") ? "svg" : "html"), filename: path.split("/").pop() || path });
  };
  return (
    <div className="file-chips" aria-label={t.filesCreated}>
      {files.map((path) => (
        <span key={path} className="file-chip">
          <IconFile size={15} />
          <a href={fileUrl(path, projectId)} download title={path}>{path.split("/").pop()}</a>
          {/\.(html?|svg)$/i.test(path) && <button type="button" className="link-btn" onClick={() => preview(path)}>{t.preview}</button>}
        </span>
      ))}
    </div>
  );
}

export function AssistantMessage({ run, specialists, onPermission, projectId }: {
  run: RunState;
  specialists: Specialist[];
  onPermission?: (id: string, status: PermissionState["status"]) => void;
  projectId?: string;
}) {
  const [copied, setCopied] = useState(false);
  const live = run.status === "running" || run.status === "planning" || run.status === "synthesizing";
  const routeSpecs = run.route?.specialists ?? [];
  const sensitive = routeSpecs.some((r) => specialists.find((s) => s.id === r.id)?.sensitive);
  const pending = run.permissions.filter((p) => p.status === "pending" || p.status === "sending");
  const files = [...new Set(run.tools.filter((x) => x.ok && x.file).map((x) => x.file as string))];

  return (
    <div className="msg assistant">
      {routeSpecs.length > 0 && (
        <div className="route">
          {routeSpecs.map((s) => (
            <span key={s.id} className={`chip spec-${s.id}`} title={`${s.provider} · ${s.model || ""}${s.adapter ? ` · ${t.adapter}: ${s.adapter}` : ""}${s.profile_only ? ` · ${t.promptProfile}` : ""}`}>
              <SpecMark id={s.id} />
              {s.name}
              {s.profile_only && <span className="chip-note">β</span>}
            </span>
          ))}
          {(run.skills ?? []).map((name) => (
            <span key={name} className="chip skill-chip" title={t.skill}>✦ {name}</span>
          ))}
          {run.route?.method && run.route.method !== "user" && (
            <span className="route-meta">{run.route.mode} · {run.route.method}</span>
          )}
        </div>
      )}

      {(run.order.length > 0 || run.tools.length > 0 || run.reasoning) && (
        <div className="trace">
          {run.reasoning && (
            <Collapsible title={t.reasoning} live={live && !run.text}>
              <div className="reasoning">{run.reasoning}</div>
            </Collapsible>
          )}
          {run.order.map((id) => {
            const st = run.subtasks[id];
            return (
              <Collapsible key={id} live={!st.done} title={<><b>{st.name}</b> <span className="muted">{st.instruction.slice(0, 90)}</span>{st.done && st.elapsed !== undefined && <span className="muted"> · {st.elapsed.toFixed(1)}s</span>}</>}>
                <Markdown text={st.text || "…"} />
              </Collapsible>
            );
          })}
          {run.tools.map((tool) => (
            <Collapsible key={tool.id} live={tool.result === undefined} title={<><IconTool size={13} /> <code>{tool.name}</code>{tool.ok === false && <span className="bad"> ✕</span>}</>}>
              <div className="tool-io">
                <div className="label">{t.tool}</div>
                <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
                {tool.result !== undefined && (<><div className="label">{t.result}</div><pre>{tool.result}</pre></>)}
              </div>
            </Collapsible>
          ))}
        </div>
      )}

      {run.permissions.map((p) => (
        <Permission key={p.id} p={p} onDecided={(id, s) => onPermission?.(id, s)} />
      ))}

      {run.trimmed ? <div className="notice">{run.trimmed} {t.contextTrimmed}</div> : null}

      {run.text ? (
        <Markdown text={run.text} />
      ) : live && pending.length === 0 ? (
        <div className="typing" aria-live="polite">
          <span className="dot" /><span className="dot" /><span className="dot" />
          <span className="muted">{run.status === "planning" ? t.planning : run.status === "synthesizing" ? t.synthesizing : t.thinking}</span>
        </div>
      ) : null}

      {files.length > 0 && <Files files={files} projectId={projectId} />}

      {run.error && <div className="error-box" role="alert">{t.error}: {run.error}</div>}
      {run.status === "stopped" && <div className="notice">{t.stopped}</div>}

      {!live && run.text && (
        <div className="msg-actions">
          <button className="icon-btn" onClick={() => { navigator.clipboard?.writeText(run.text); setCopied(true); setTimeout(() => setCopied(false), 1500); }} title={t.copy} aria-label={t.copy}>
            <IconCopy size={15} />
          </button>
          {copied && <span className="muted small">{t.copied}</span>}
          {run.elapsed !== undefined && <span className="muted small">{run.elapsed.toFixed(1)} s</span>}
          {sensitive && <span className="muted small disclaimer">{t.disclaimerSensitive}</span>}
        </div>
      )}
    </div>
  );
}
