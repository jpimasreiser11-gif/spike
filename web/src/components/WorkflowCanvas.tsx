import { useRef } from "react";
import { t } from "../i18n";
import {
  IN_PORTS, NODE_H, NODE_W, OUT_PORTS, canvasSize, candidates, edgePath, portPoint,
  type Editor, type NodeRun, type Problem, type WfNode,
} from "../workflow";

export const fmt = (template: string, params: Record<string, unknown> = {}) =>
  template.replace(/\{(\w+)\}/g, (whole, key) => (key in params ? String(params[key]) : whole));

/** A short line about what a node does, for its box on the canvas. */
function summary(n: WfNode): string {
  const text = n.type === "input" ? `${t.workflow.kinds[n.kind ?? "text"]}${n.default ? ` · ${n.default}` : ""}`
    : n.type === "specialist" ? `${n.specialist === "auto" ? t.workflow.auto.split(" (")[0] : n.specialist} · ${n.prompt ?? ""}`
    : n.type === "tool" ? n.tool || t.workflow.pickTool
    : n.type === "condition" ? `${t.workflow.ops[n.op ?? "contains"]} ${n.value ?? ""}`
    : n.mode === "file" ? n.path || t.workflow.fields.path : n.title || t.workflow.modes.artifact;
  return text.replace(/\s+/g, " ").slice(0, 30);
}

/**
 * The drawing: nodes as boxes with ports, edges as curves. A node is a button in the tab order and takes the keys of
 * `editorKey`; the mouse drags a node and joins an output port to a node. Nothing here needs the mouse.
 */
export function WorkflowCanvas({ editor, problems, run, onSelect, onMove, onKey, onStartConnect, onFinishConnect, onSelectEdge, selectedEdge, onRemoveEdge }: {
  editor: Editor;
  problems: Record<string, Problem[]>;
  run: Record<string, NodeRun> | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
  onKey: (key: string, shift: boolean) => void;
  onStartConnect: (id: string, port: string) => void;
  onFinishConnect: (id: string) => void;
  onSelectEdge: (id: string | null) => void;
  selectedEdge: string | null;
  onRemoveEdge: (id: string) => void;
}) {
  const { doc, selected, connecting } = editor;
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const size = canvasSize(doc);
  const targets = connecting ? new Set(candidates(doc, connecting.from, connecting.port)) : null;

  const point = (e: React.PointerEvent) => {
    const box = svg.current!.getBoundingClientRect();
    return { x: e.clientX - box.left, y: e.clientY - box.top };
  };
  const down = (e: React.PointerEvent, n: WfNode) => {
    if (connecting) { onFinishConnect(n.id); return; }
    onSelect(n.id);
    const p = point(e);
    drag.current = { id: n.id, dx: p.x - n.x, dy: p.y - n.y };
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  };
  const move = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const p = point(e);
    onMove(drag.current.id, p.x - drag.current.dx, p.y - drag.current.dy);
  };

  return (
    <div className="wf-canvas-wrap">
      <svg ref={svg} className="wf-canvas" width={size.width} height={size.height} role="group" aria-label={t.workflow.canvas} aria-describedby="wf-help"
        onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
        onPointerDown={(e) => { if (e.target === e.currentTarget) { onSelect(null); onSelectEdge(null); } }}>
        <defs>
          <marker id="wf-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="wf-arrow" />
          </marker>
        </defs>
        {doc.edges.map((e) => {
          const from = doc.nodes.find((n) => n.id === e.from)?.name, to = doc.nodes.find((n) => n.id === e.to)?.name;
          const label = fmt(t.workflow.edge, { from, to }) + (e.fromPort !== "out" ? ` (${t.workflow.ports[e.fromPort]})` : "");
          return (
            <g key={e.id} className={`wf-edge ${selectedEdge === e.id ? "selected" : ""}`} role="button" tabIndex={0} aria-label={label}
              aria-pressed={selectedEdge === e.id} onFocus={() => onSelectEdge(e.id)}
              onKeyDown={(ev) => { if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); onRemoveEdge(e.id); } }}
              onClick={() => onSelectEdge(e.id)}>
              <path d={edgePath(doc, e)} className="wf-edge-hit" />
              <path d={edgePath(doc, e)} className="wf-edge-line" markerEnd="url(#wf-arrow)" />
            </g>
          );
        })}
        {doc.nodes.map((n) => {
          const bad = problems[n.id]?.length ?? 0;
          const state = run?.[n.id]?.status;
          const isTarget = targets?.has(n.id);
          const label = `${fmt(t.workflow.nodeLabel, { type: t.workflow.types[n.type], name: n.name })}${state ? `, ${t.workflow.status[state]}` : ""}${bad ? `, ${fmt(t.workflow.problemBadge, { n: bad })}` : ""}`;
          return (
            <g key={n.id} transform={`translate(${n.x},${n.y})`} data-node={n.id} role="button" tabIndex={0} aria-label={label} aria-pressed={selected === n.id}
              className={`wf-node type-${n.type} ${selected === n.id ? "selected" : ""} ${bad ? "invalid" : ""} ${state ? `st-${state}` : ""} ${isTarget ? "target" : ""} ${connecting?.target === n.id ? "chosen" : ""}`}
              onPointerDown={(e) => down(e, n)}
              onFocus={() => { if (selected !== n.id) onSelect(n.id); }}
              onKeyDown={(e) => {
                if (e.key === "Tab" && !connecting) return;
                if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Delete", "Backspace", "Enter", "Escape", "Tab"].includes(e.key) || (!e.ctrlKey && !e.metaKey && !e.altKey && ["c", "t", "f"].includes(e.key))) {
                  e.preventDefault();
                  onKey(e.key, e.shiftKey);
                }
              }}>
              <rect width={NODE_W} height={NODE_H} rx={12} className="wf-box" />
              <text x={12} y={20} className="wf-type">{t.workflow.types[n.type]}</text>
              <text x={12} y={39} className="wf-name">{(n.label || n.name).slice(0, 22)}</text>
              <text x={12} y={55} className="wf-sub">{summary(n)}</text>
              {state && <text x={NODE_W - 10} y={20} textAnchor="end" className={`wf-state st-${state}`}>{t.workflow.status[state]}</text>}
              {bad > 0 && <g aria-hidden><circle cx={NODE_W - 4} cy={-2} r={10} className="wf-bad" /><text x={NODE_W - 4} y={2} textAnchor="middle" className="wf-bad-text">{bad}</text></g>}
              {IN_PORTS[n.type].map((port) => {
                const c = portPoint({ ...n, x: 0, y: 0 }, "in", port);
                return <circle key={port} cx={c.x} cy={c.y} r={7} className={`wf-port in ${isTarget ? "target" : ""}`}
                  onPointerDown={(e) => { if (connecting) { e.stopPropagation(); onFinishConnect(n.id); } }} />;
              })}
              {OUT_PORTS[n.type].map((port) => {
                const c = portPoint({ ...n, x: 0, y: 0 }, "out", port);
                return (
                  <g key={port}>
                    <circle cx={c.x} cy={c.y} r={7} className={`wf-port out ${port}`} role="button" aria-label={`${t.workflow.connectFrom}: ${n.name} (${t.workflow.ports[port]})`}
                      onPointerDown={(e) => { e.stopPropagation(); onSelect(n.id); onStartConnect(n.id, port); }} />
                    {OUT_PORTS[n.type].length > 1 && <text x={c.x + 11} y={c.y - 7} className="wf-port-label">{port === "true" ? "T" : "F"}</text>}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
