import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, streamGet } from "../api";
import { t } from "../i18n";
import type { PermissionState, ProviderInfo, QuestionState } from "../types";
import {
  IN_PORTS, NODE_TYPES, OUT_PORTS, addNode, applyRunEvent, candidates, connect, editorKey, emptyRun, moveNode, newDoc, nodeOf, patchNode,
  problemsByNode, removeEdge, removeNode, startEditor, viewOfRecord,
  type Editor, type NodeType, type Problem, type RunView, type WfDoc, type WfNode,
} from "../workflow";
import { ArtifactContext } from "./Artifact";
import { Permission, Question, fileUrl } from "./AssistantMessage";
import { IconStop } from "./Icons";
import { WorkflowCanvas, fmt } from "./WorkflowCanvas";
import "./WorkflowBuilder.css";

type ToolInfo = { name: string; description: string; risk: string; policy: string; parameters: { properties?: Record<string, { type?: string; description?: string }>; required?: string[] } };
type Catalog = { specialists: { id: string; name: string }[]; tools: ToolInfo[]; tools_enabled: boolean };
type Listed = { id: string; name: string; revision?: number; broken?: boolean };
type RunListed = { id: string; status: string; started: number; elapsed_s: number | null };
const W = t.workflow;

/** What a failed request says: the problems the server found in the workflow, or its error code in the user's language. */
export function failure(e: unknown): { text: string; problems: Problem[] } {
  const message = (e as Error).message ?? String(e);
  try {
    const detail = JSON.parse(message);
    if (Array.isArray(detail?.problems)) return { text: "", problems: detail.problems };
  } catch { /* a plain code */ }
  return { text: W.errors[message] ?? message, problems: [] };
}

export const problemText = (p: Problem) => (W.problems[p.code] ? fmt(W.problems[p.code], { ...p.params, nodes: Array.isArray(p.params.nodes) ? (p.params.nodes as string[]).join(" → ") : "" }) : p.message);

const slug = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "workflow";
const htmlOf = (content: string, format: string) => (format === "html" ? content
  : `<pre style="white-space:pre-wrap;font:14px/1.5 system-ui,sans-serif;margin:0;padding:16px">${content.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</pre>`);

/** The portable form of a workflow: what is exported and what an import reads. */
export const portable = (doc: WfDoc): WfDoc => {
  const { format, version, name, nodes, edges } = doc;
  return { format, version, name, nodes, edges };
};

export function WorkflowBuilder({ projectId, providers = [], onClose }: { projectId?: string; providers?: ProviderInfo[]; onClose: () => void }) {
  const openArtifact = useContext(ArtifactContext);
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const [catalog, setCatalog] = useState<Catalog>({ specialists: [], tools: [], tools_enabled: true });
  const [listed, setListed] = useState<Listed[]>([]);
  const [editor, setEditor] = useState<Editor>(() => startEditor(newDoc("")));
  const [dirty, setDirty] = useState(false);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [info, setInfo] = useState("");
  const [error, setError] = useState("");
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [providerId, setProviderId] = useState("");
  const [run, setRun] = useState<RunView | null>(null);
  const [runs, setRuns] = useState<RunListed[]>([]);
  const [permissions, setPermissions] = useState<PermissionState[]>([]);
  const [questions, setQuestions] = useState<QuestionState[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [connectTo, setConnectTo] = useState({ port: "", target: "" });
  const abort = useRef<AbortController | null>(null);
  const side = useRef<HTMLElement>(null);
  const { doc } = editor;
  const byNode = problemsByNode(problems);

  const edit = useCallback((next: Editor) => { setEditor(next); setDirty(true); }, []);
  const change = (nextDoc: WfDoc) => edit({ ...editor, doc: nextDoc });

  const refreshList = useCallback(() => api.get<Listed[]>(`/api/workflows${query}`).then(setListed).catch((e) => setError(failure(e).text)), [query]);
  const refreshRuns = useCallback((wid: string) => api.get<RunListed[]>(`/api/workflows/${wid}/runs${query}`).then(setRuns).catch(() => setRuns([])), [query]);

  useEffect(() => {
    api.get<Catalog>(`/api/workflows/catalog${query}`).then(setCatalog).catch((e) => setError(failure(e).text));
    refreshList();
    if (projectId) api.get<{ path: string }[]>(`/api/projects/${projectId}/files`).then((f) => setFiles(f.map((x) => x.path).filter((p) => !p.startsWith("workflows/")))).catch(() => setFiles([]));
    return () => abort.current?.abort();
  }, [query, projectId, refreshList]);

  const say = (message: string, bad = false) => { setInfo(bad ? "" : message); setError(bad ? message : ""); };

  // ------------------------------------------------------------------ the document
  const discard = () => !dirty || doc.nodes.length === 0 || window.confirm(W.discardAsk);
  const open = async (wid: string) => {
    if (!discard()) return;
    abort.current?.abort();
    try {
      const loaded = await api.get<WfDoc>(`/api/workflows/${wid}${query}`);
      setEditor(startEditor(loaded)); setDirty(false); setProblems([]); setRun(null); setPermissions([]); setQuestions([]); setSelectedEdge(null);
      setInputs(Object.fromEntries(loaded.nodes.filter((n) => n.type === "input").map((n) => [n.name, n.default ?? ""])));
      say(""); refreshRuns(wid);
    } catch (e) { say(failure(e).text, true); }
  };
  const create = (force = false) => {
    if (!force && !discard()) return;
    abort.current?.abort();
    setEditor(startEditor(newDoc(W.untitled))); setDirty(true); setProblems([]); setRun(null); setRuns([]); say(""); setInputs({});
  };
  const save = async () => {
    try {
      const saved = doc.id
        ? await api.put<WfDoc>(`/api/workflows/${doc.id}${query}`, { workflow: portable(doc), base_revision: doc.revision })
        : await api.post<WfDoc>(`/api/workflows${query}`, { workflow: portable(doc) });
      setEditor({ ...editor, doc: saved }); setDirty(false); setProblems([]);
      say(fmt(W.saved, { n: saved.revision ?? 1 })); refreshList(); refreshRuns(saved.id!);
    } catch (e) {
      const f = failure(e);
      setProblems(f.problems);
      say(f.text || (f.problems.length ? `${W.problemsTitle}: ${f.problems.length}` : ""), true);
    }
  };
  const validate = async () => {
    try {
      const r = await api.post<{ ok: boolean; problems: Problem[] }>(`/api/workflows/validate${query}`, { workflow: portable(doc) });
      setProblems(r.problems);
      if (r.ok) say(W.valid); else say(`${W.problemsTitle}: ${r.problems.length}`, true);
    } catch (e) { say(failure(e).text, true); }
  };
  const remove = async () => {
    if (!doc.id || !window.confirm(W.deleteAsk)) return;
    try { await api.del(`/api/workflows/${doc.id}${query}`); create(true); refreshList(); } catch (e) { say(failure(e).text, true); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(portable(doc), null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url; a.download = `${slug(doc.name)}.spike-workflow.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const importFile = async (file: File) => {
    let parsed: WfDoc;
    try { parsed = JSON.parse(await file.text()); if (parsed.format !== "spike-workflow") throw new Error(); } catch { say(W.importFailed, true); return; }
    try {
      const saved = await api.post<WfDoc>(`/api/workflows/import${query}`, { workflow: parsed });
      refreshList(); await open(saved.id!);
    } catch (e) { // it cannot be saved as it is (a tool this computer lacks, say): open it unsaved, with what is wrong
      const f = failure(e);
      setEditor(startEditor(portable({ ...newDoc(""), ...parsed }))); setDirty(true); setProblems(f.problems); setRun(null);
      say(f.text || `${W.problemsTitle}: ${f.problems.length}`, true);
    }
  };

  // ------------------------------------------------------------------ editing
  const addOf = (type: NodeType) => { const r = addNode(doc, type); edit({ ...editor, doc: r.doc, selected: r.id, notice: null }); setSelectedEdge(null); };
  const onKey = (key: string, shift: boolean) => {
    if (key === "Enter" && !editor.connecting) { side.current?.querySelector<HTMLElement>("input, select, textarea")?.focus(); return; }
    const next = editorKey(editor, key, shift);
    if (next !== editor) edit(next);
    // a deleted node takes the focus with it: give it to the first node left, so the keyboard keeps working
    if (next.selected === null && editor.selected !== null && next.doc.nodes.length < editor.doc.nodes.length)
      setTimeout(() => document.querySelector<SVGElement>(".wf-canvas [data-node]")?.focus(), 0);
  };
  const finishConnect = (id: string) => {
    if (!editor.connecting) return;
    const joined = connect(doc, editor.connecting.from, editor.connecting.port, id);
    edit(joined.error ? { ...editor, connecting: null, notice: { code: joined.error } }
      : { ...editor, doc: joined.doc, connecting: null, notice: { code: "connected" } });
  };
  const node = editor.selected ? nodeOf(doc, editor.selected) : undefined;
  const set = (patch: Partial<WfNode>) => node && change(patchNode(doc, node.id, patch));
  const notice = editor.notice ? fmt(W.notices[editor.notice.code] ?? editor.notice.code, editor.notice.params) : "";

  // ------------------------------------------------------------------ running
  const follow = useCallback(async (wid: string, rid: string, base: WfDoc) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    let view = emptyRun(base, rid);
    setRun(view);
    try {
      await streamGet(`/api/workflows/${wid}/runs/${rid}/events${query}`, (ev) => {
        view = applyRunEvent(view, ev);
        setRun(view);
        if (ev.type === "permission_request") setPermissions((p) => [...p, { id: ev.id, tool: ev.tool, risk: ev.risk, arguments: ev.arguments ?? {}, status: "pending", reason: ev.reason, code: ev.code, once: ev.once, domain: ev.domain, isolation: ev.isolation }]);
        if (ev.type === "permission_resolved") setPermissions((p) => p.map((x) => (x.id === ev.id ? { ...x, status: ev.decision } : x)));
        if (ev.type === "question") setQuestions((q) => [...q, { id: ev.id, question: ev.question, options: ev.options ?? [], status: "pending" }]);
        if (ev.type === "answered") setQuestions((q) => q.map((x) => (x.id === ev.id ? { ...x, answer: ev.answer, status: ev.answer == null ? "unanswered" : "answered" } : x)));
        if (ev.type === "run_end") {
          setPermissions((p) => p.filter((x) => x.status !== "pending" && x.status !== "sending"));
          setQuestions((q) => q.map((x) => (x.status === "pending" ? { ...x, status: "unanswered" } : x)));
        }
      }, controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") say(failure(e).text, true);
    } finally { refreshRuns(wid); }
  }, [query, refreshRuns]);

  const start = async () => {
    if (!doc.id || dirty) { say(W.saveFirst, true); return; }
    try {
      const r = await api.post<{ id: string }>(`/api/workflows/${doc.id}/runs${query}`, { inputs, provider_id: providerId || null });
      say(""); setPermissions([]); setQuestions([]);
      follow(doc.id, r.id, doc);
    } catch (e) {
      const f = failure(e);
      setProblems(f.problems);
      say(f.text || f.problems.map(problemText).join(" "), true);
    }
  };
  const stop = async () => {
    if (!doc.id || !run) return;
    try { await api.post(`/api/workflows/${doc.id}/runs/${run.id}/stop${query}`, {}); say(W.stopped); } catch (e) { say(failure(e).text, true); }
  };
  const viewRun = async (rid: string) => {
    if (!doc.id) return;
    try {
      const record = await api.get<Record<string, unknown>>(`/api/workflows/${doc.id}/runs/${rid}${query}`);
      if (record.live) { follow(doc.id, rid, doc); return; }
      abort.current?.abort(); setPermissions([]); setQuestions([]);
      setRun(viewOfRecord(doc, record));
    } catch (e) { say(failure(e).text, true); }
  };
  const decided = (id: string, status: PermissionState["status"]) => setPermissions((p) => p.map((x) => (x.id === id ? { ...x, status } : x)));
  const running = !!run?.live;
  const inputNodes = doc.nodes.filter((n) => n.type === "input");
  const tool = node?.type === "tool" ? catalog.tools.find((x) => x.name === node.tool) : undefined;
  const out = node ? OUT_PORTS[node.type] : [];
  const port = connectTo.port || out[0] || "";
  const targets = node && port ? candidates(doc, node.id, port) : [];
  const nodeRun = node ? run?.nodes[node.id] : undefined;

  return (
    <section className="forge creator workflow" aria-label={W.title}>
      <div className="forge-head">
        <h1>{W.title}</h1>
        <div className="spacer" />
        <button className="btn" onClick={onClose}>{W.back}</button>
      </div>
      <p className="muted">{W.intro}</p>

      <div className="wf-bar" role="toolbar" aria-label={W.title}>
        <label className="field inline"><span>{W.list}</span>
          <select value={doc.id ?? ""} onChange={(e) => (e.target.value ? open(e.target.value) : create())} aria-label={W.list}>
            <option value="">{doc.id ? W.newFlow : dirty || doc.name ? doc.name || W.untitled : W.none}</option>
            {listed.map((w) => <option key={w.id} value={w.id}>{w.broken ? `${w.id} (!)` : `${w.name} · v${w.revision}`}</option>)}
          </select>
        </label>
        <button className="btn" onClick={() => create()}>{W.newFlow}</button>
        <label className="field inline"><span>{W.name}</span>
          <input value={doc.name} placeholder={W.untitled} onChange={(e) => change({ ...doc, name: e.target.value })} maxLength={80} />
        </label>
        {doc.revision && <span className="muted small">{W.version} {doc.revision}</span>}
        {dirty && <span className="warn-text small">{W.unsaved}</span>}
        <div className="spacer" />
        <button className="btn" onClick={validate}>{W.validate}</button>
        <button className="btn primary" onClick={save} disabled={!doc.name.trim() || doc.nodes.length === 0}>{W.save}</button>
        <button className="btn" onClick={download} disabled={doc.nodes.length === 0}>{W.export}</button>
        <label className="btn file-btn">{W.importJson}<input type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} /></label>
        {doc.id && <button className="btn danger" onClick={remove}>{W.delete}</button>}
      </div>

      <div className="wf-add" role="group" aria-label={W.add}>
        <span className="muted small">{W.add}:</span>
        {NODE_TYPES.map((type) => (
          <button key={type} className={`btn small wf-add-${type}`} onClick={() => addOf(type)} title={W.typeHints[type]}>+ {W.types[type]}</button>
        ))}
      </div>

      {error && <div className="error-box" role="alert">{error}</div>}
      {info && <div className="wf-info" role="status">{info}</div>}

      <div className="wf-layout">
        <div className="wf-main">
          {problems.length > 0 && (
            <div className="wf-problems" role="region" aria-label={W.problemsTitle}>
              <b>{W.problemsTitle}</b>
              <ul>
                {problems.map((p, i) => (
                  <li key={i}>
                    {p.node && nodeOf(doc, p.node) ? <button className="linklike" onClick={() => setEditor({ ...editor, selected: p.node })}>{nodeOf(doc, p.node)!.name}</button> : null}{" "}
                    <span data-code={p.code}>{problemText(p)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <WorkflowCanvas editor={editor} problems={byNode} run={run?.nodes ?? null} selectedEdge={selectedEdge}
            onSelect={(id) => { setEditor((e) => ({ ...e, selected: id })); setConnectTo({ port: "", target: "" }); }}
            onMove={(id, x, y) => edit({ ...editor, doc: moveNode(doc, id, x, y) })} onKey={onKey}
            onStartConnect={(id, p) => edit({ ...editor, selected: id, connecting: { from: id, port: p, target: null }, notice: { code: "pick" } })}
            onFinishConnect={finishConnect} onSelectEdge={setSelectedEdge}
            onRemoveEdge={(id) => { change(removeEdge(doc, id)); setSelectedEdge(null); }} />
          <p className="muted small" id="wf-help">{W.canvasHelp}</p>
          <div className="wf-live" role="status" aria-live="polite">{notice}</div>
        </div>

        <aside className="wf-side" ref={side} aria-label={W.properties}>
          <h2>{W.properties}</h2>
          {!node ? <p className="muted">{W.noSelection}</p> : (
            <div className="form">
              <label className="field"><span>{W.fields.name}</span>
                <input value={node.name} onChange={(e) => set({ name: e.target.value })} maxLength={40} /></label>
              <label className="field"><span>{W.fields.label}</span>
                <input value={node.label ?? ""} onChange={(e) => set({ label: e.target.value })} maxLength={80} /></label>
              {node.type === "input" && (<>
                <label className="field"><span>{W.fields.kind}</span>
                  <select value={node.kind} onChange={(e) => set({ kind: e.target.value as WfNode["kind"] })}>
                    {Object.entries(W.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                <label className="field"><span>{W.fields.default}</span>
                  <input value={node.default ?? ""} onChange={(e) => set({ default: e.target.value })} list="wf-files" /></label>
                {node.kind === "file" && <p className="muted small">{W.fileHint}</p>}
              </>)}
              {node.type === "specialist" && (<>
                <label className="field"><span>{W.fields.specialist}</span>
                  <select value={node.specialist} onChange={(e) => set({ specialist: e.target.value })}>
                    <option value="auto">{W.auto}</option>
                    {catalog.specialists.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
                <label className="field"><span>{W.fields.prompt}</span>
                  <textarea rows={6} value={node.prompt ?? ""} onChange={(e) => set({ prompt: e.target.value })} /></label>
                <p className="muted small">{W.varsHint}</p>
              </>)}
              {node.type === "tool" && (<>
                <label className="field"><span>{W.fields.tool}</span>
                  <select value={node.tool} onChange={(e) => set({ tool: e.target.value, arguments: {} })}>
                    <option value="">{W.pickTool}</option>
                    {node.tool && !tool && <option value={node.tool}>{node.tool} (?)</option>}
                    {catalog.tools.map((x) => <option key={x.name} value={x.name}>{x.name} · {x.risk}</option>)}</select></label>
                {tool && <p className="muted small">{tool.description || W.noTool}</p>}
                {tool && Object.entries(tool.parameters.properties ?? {}).map(([key, spec]) => (
                  <label className="field" key={key}><span>{key}{tool.parameters.required?.includes(key) ? " *" : ""} <small>{spec.type}</small></span>
                    <textarea rows={key === "content" || key === "code" ? 4 : 1} value={String(node.arguments?.[key] ?? "")} title={spec.description}
                      onChange={(e) => set({ arguments: { ...node.arguments, [key]: e.target.value } })} /></label>
                ))}
                <p className="muted small">{W.varsHint}</p>
              </>)}
              {node.type === "condition" && (<>
                <label className="field"><span>{W.fields.op}</span>
                  <select value={node.op} onChange={(e) => set({ op: e.target.value as WfNode["op"] })}>
                    {Object.entries(W.ops).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                {node.op === "number" && (
                  <label className="field"><span>{W.fields.compare}</span>
                    <select value={node.compare} onChange={(e) => set({ compare: e.target.value })}>
                      {["<", "<=", ">", ">=", "==", "!="].map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
                )}
                <label className="field"><span>{W.fields.value}</span>
                  <input value={node.value ?? ""} onChange={(e) => set({ value: e.target.value })} /></label>
                {node.op !== "number" && (
                  <label className="field inline"><input type="checkbox" checked={!!node.case_sensitive} onChange={(e) => set({ case_sensitive: e.target.checked })} /><span>{W.fields.caseSensitive}</span></label>
                )}
              </>)}
              {node.type === "output" && (<>
                <label className="field"><span>{W.fields.mode}</span>
                  <select value={node.mode} onChange={(e) => set({ mode: e.target.value as WfNode["mode"] })}>
                    {Object.entries(W.modes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                {node.mode === "file" ? (
                  <label className="field"><span>{W.fields.path}</span>
                    <input value={node.path ?? ""} onChange={(e) => set({ path: e.target.value })} placeholder={W.outputPathPlaceholder} /></label>
                ) : (<>
                  <label className="field"><span>{W.fields.title}</span>
                    <input value={node.title ?? ""} onChange={(e) => set({ title: e.target.value })} /></label>
                  <label className="field"><span>{W.fields.format}</span>
                    <select value={node.format} onChange={(e) => set({ format: e.target.value as WfNode["format"] })}>
                      {Object.entries(W.formats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                </>)}
                <label className="field"><span>{W.fields.content}</span>
                  <textarea rows={4} value={node.content ?? ""} onChange={(e) => set({ content: e.target.value })} /></label>
                <p className="muted small">{W.varsHint}</p>
              </>)}

              <h3>{W.connections}</h3>
              <ul className="wf-edges">
                {doc.edges.filter((e) => e.from === node.id || e.to === node.id).map((e) => (
                  <li key={e.id}>
                    <span>{nodeOf(doc, e.from)?.name} {e.fromPort !== "out" ? `(${W.ports[e.fromPort]})` : ""} → {nodeOf(doc, e.to)?.name}</span>
                    <button className="btn small" onClick={() => change(removeEdge(doc, e.id))}>{W.disconnect}</button>
                  </li>
                ))}
                {!doc.edges.some((e) => e.from === node.id || e.to === node.id) && <li className="muted">{W.noEdges}</li>}
              </ul>
              {out.length > 0 && IN_PORTS[node.type] !== undefined && (
                <div className="row">
                  {out.length > 1 && (
                    <label className="field"><span>{W.connectFrom}</span>
                      <select value={port} onChange={(e) => setConnectTo({ port: e.target.value, target: "" })}>
                        {out.map((p) => <option key={p} value={p}>{W.ports[p]}</option>)}</select></label>
                  )}
                  <label className="field"><span>{W.connectTo}</span>
                    <select value={connectTo.target} onChange={(e) => setConnectTo({ port, target: e.target.value })}>
                      <option value="">{W.chooseNode}</option>
                      {targets.map((id) => <option key={id} value={id}>{nodeOf(doc, id)?.name}</option>)}</select></label>
                  <button className="btn" disabled={!connectTo.target} onClick={() => {
                    const joined = connect(doc, node.id, port, connectTo.target);
                    edit(joined.error ? { ...editor, notice: { code: joined.error } } : { ...editor, doc: joined.doc, notice: { code: "connected" } });
                    setConnectTo({ port: "", target: "" });
                  }}>{W.connect}</button>
                </div>
              )}
              <button className="btn danger" onClick={() => edit({ ...editor, doc: removeNode(doc, node.id), selected: null, notice: { code: "deleted", params: { name: node.name } } })}>{W.deleteNode}</button>

              {nodeRun && nodeRun.status !== "pending" && (
                <div className="wf-result" aria-label={W.runPanel}>
                  <h3>{W.runPanel} · {W.status[nodeRun.status]}</h3>
                  {nodeRun.elapsed_s != null && <p className="small muted">{nodeRun.elapsed_s} {W.seconds}</p>}
                  {nodeRun.branch && <p className="small">{W.branch}: {W.ports[nodeRun.branch]}</p>}
                  {nodeRun.skip && <p className="small muted">{W.skip[nodeRun.skip] ?? nodeRun.skip}</p>}
                  {nodeRun.error && <div className="error-box small-pre">{nodeRun.error}</div>}
                  {nodeRun.private && <p className="small warn-text">{W.privateNote}</p>}
                  {nodeRun.output && <pre className="wf-output">{nodeRun.output}</pre>}
                  {nodeRun.file && <p className="small">{W.savedFile}: <a href={fileUrl(nodeRun.file, projectId)} target="_blank" rel="noreferrer">{nodeRun.file}</a></p>}
                  {nodeRun.artifact && openArtifact && (
                    <button className="btn" onClick={() => openArtifact({ title: nodeRun.artifact!.title, html: htmlOf(nodeRun.artifact!.content, nodeRun.artifact!.format), filename: `${slug(nodeRun.artifact!.title)}.html` })}>{W.openArtifact}</button>
                  )}
                </div>
              )}
            </div>
          )}
          <datalist id="wf-files">{files.map((f) => <option key={f} value={f} />)}</datalist>
        </aside>
      </div>

      <div className="wf-run" role="region" aria-label={W.runPanel}>
        <h2>{W.runPanel}</h2>
        <div className="row end">
          {inputNodes.length === 0 && <span className="muted">{W.noInputs}</span>}
          {inputNodes.map((n) => (
            <label className="field" key={n.id}><span>{n.name} <small>({W.kinds[n.kind ?? "text"]})</small></span>
              <input value={inputs[n.name] ?? ""} onChange={(e) => setInputs({ ...inputs, [n.name]: e.target.value })}
                inputMode={n.kind === "number" ? "decimal" : undefined} list={n.kind === "file" ? "wf-files" : undefined}
                placeholder={n.kind === "file" ? W.filePlaceholder : n.default} /></label>
          ))}
          <label className="field"><span>{W.provider}</span>
            <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
              <option value="">{W.defaultProvider}</option>
              {providers.map((p) => <option key={p.id} value={p.id}>{p.name}{p.local ? ` · ${W.local}` : ""}</option>)}</select></label>
          <div className="spacer" />
          {running
            ? <button className="btn danger" onClick={stop}><IconStop size={14} /> {W.stop}</button>
            : <button className="btn primary" onClick={start} disabled={!doc.id || dirty || doc.nodes.length === 0} title={!doc.id || dirty ? W.saveFirst : undefined}>{W.run}</button>}
        </div>

        {permissions.map((p) => <Permission key={p.id} p={p} onDecided={decided} />)}
        {questions.map((q) => <Question key={q.id} q={q} />)}

        {run && (
          <div className="wf-log" aria-label={W.log}>
            <h3>{run.live ? W.live : W.status[run.status] ?? run.status}{run.elapsed_s != null && <span className="muted small"> · {W.total} {run.elapsed_s} {W.seconds}</span>}</h3>
            {doc.nodes.map((n) => {
              const r = run.nodes[n.id];
              if (!r || r.status === "pending") return null;
              return (
                <details key={n.id} className={`wf-log-node st-${r.status}`} open={r.status === "running" || r.status === "failed" || r.status === "denied"}>
                  <summary><b>{n.name}</b> <span className={`wf-chip st-${r.status}`}>{W.status[r.status]}</span>
                    {r.elapsed_s != null && <span className="muted small"> {r.elapsed_s} {W.seconds}</span>}
                    {r.skip && <span className="muted small"> · {W.skip[r.skip] ?? r.skip}</span>}</summary>
                  {r.log.map((l, i) => <div key={i} className={`wf-log-line ${l.kind}`}><span className="muted small">{W.logKinds[l.kind] ?? l.kind}</span> <span>{l.text}</span></div>)}
                  {r.error && <div className="error-box small-pre">{r.error}</div>}
                  {r.output && r.log.length === 0 && <pre className="wf-output">{r.output.slice(0, 2000)}</pre>}
                </details>
              );
            })}
          </div>
        )}

        <h3>{W.history}</h3>
        {runs.length === 0 ? <p className="muted small">{W.noRuns}</p> : (
          <ul className="wf-history">
            {runs.map((r) => (
              <li key={r.id}>
                <span className={`wf-chip st-${r.status === "completed" ? "ok" : r.status === "cancelled" ? "cancelled" : r.status === "running" ? "running" : "failed"}`}>{W.status[r.status] ?? r.status}</span>
                <span className="muted small"> {new Date(r.started * 1000).toLocaleString()}{r.elapsed_s != null ? ` · ${r.elapsed_s} ${W.seconds}` : ""}</span>
                <button className="btn small" onClick={() => viewRun(r.id)}>{W.openRun}</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
