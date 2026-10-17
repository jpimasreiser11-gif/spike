import type { ChatEvent, RunState, StoredMessage } from "./types";

export const emptyRun = (): RunState => ({
  status: "idle",
  subtasks: {},
  order: [],
  tools: [],
  permissions: [],
  text: "",
  reasoning: "",
});

/** Pure reducer turning orchestrator events into a renderable run. Unit-tested in run.test.ts. */
export function applyEvent(state: RunState, ev: ChatEvent): RunState {
  switch (ev.type) {
    case "status":
      return { ...state, status: ev.message === "planning" ? "planning" : state.status };
    case "route":
      return {
        ...state,
        status: "running",
        route: { mode: ev.mode, method: ev.method, confidence: ev.confidence, specialists: ev.specialists },
      };
    case "plan":
      return { ...state, plan: { method: ev.method, note: ev.note, subtasks: ev.subtasks } };
    case "subtask_start":
      return {
        ...state,
        order: [...state.order, ev.subtask],
        subtasks: {
          ...state.subtasks,
          [ev.subtask]: {
            id: ev.subtask,
            specialist: ev.specialist,
            name: ev.name,
            instruction: ev.instruction,
            text: "",
            done: false,
          },
        },
      };
    case "subtask_end": {
      const st = state.subtasks[ev.subtask];
      if (!st) return state;
      return {
        ...state,
        subtasks: { ...state.subtasks, [ev.subtask]: { ...st, done: true, ok: ev.ok, elapsed: ev.elapsed_s } },
      };
    }
    case "synthesis_start":
      return { ...state, status: "synthesizing" };
    case "delta": {
      if (ev.subtask) {
        const st = state.subtasks[ev.subtask];
        if (!st) return state;
        return { ...state, subtasks: { ...state.subtasks, [ev.subtask]: { ...st, text: st.text + ev.text } } };
      }
      return { ...state, text: state.text + ev.text };
    }
    case "reasoning":
      return ev.subtask ? state : { ...state, reasoning: state.reasoning + ev.text };
    case "tool_call":
      return {
        ...state,
        tools: [...state.tools, { id: ev.id, name: ev.name, arguments: ev.arguments, specialist: ev.specialist }],
      };
    case "tool_result":
      return {
        ...state,
        tools: state.tools.map((t) => (t.id === ev.id ? { ...t, result: ev.content, ok: ev.ok, file: ev.file } : t)),
      };
    case "permission_request":
      return {
        ...state,
        permissions: [
          ...state.permissions,
          { id: ev.id, tool: ev.tool, risk: ev.risk, arguments: ev.arguments, status: "pending" },
        ],
      };
    case "permission_resolved":
      return {
        ...state,
        permissions: state.permissions.map((p) => (p.id === ev.id ? { ...p, status: ev.decision } : p)),
      };
    case "skill": {
      const names = (ev.names as string[]).filter((n) => !(state.skills ?? []).includes(n));
      return names.length ? { ...state, skills: [...(state.skills ?? []), ...names] } : state;
    }
    case "context_trimmed":
      return { ...state, trimmed: ev.dropped };
    case "error":
      return { ...state, status: "error", error: ev.message };
    case "done":
      return {
        ...state,
        status: state.status === "error" || ev.error ? "error" : "done",
        error: state.error ?? ev.error ?? undefined,
        elapsed: ev.elapsed_s,
      };
    default:
      return state;
  }
}

/** Rebuild a finished run from a stored assistant message (meta saved by the server). */
export function runFromStored(m: StoredMessage): RunState {
  const meta = m.meta || {};
  const run = emptyRun();
  run.status = meta.error ? "error" : meta.cancelled ? "stopped" : "done";
  run.error = meta.error ?? undefined;
  run.text = m.content;
  run.elapsed = meta.elapsed_s;
  if (meta.route) run.route = meta.route;
  if (meta.plan) run.plan = meta.plan;
  if (meta.skills?.length) run.skills = meta.skills;
  for (const [id, st] of Object.entries<any>(meta.subtasks || {})) {
    const planned = meta.plan?.subtasks?.find((t: any) => t.id === id);
    run.order.push(id);
    run.subtasks[id] = {
      id,
      specialist: st.specialist,
      name: meta.route?.specialists?.find((s: any) => s.id === st.specialist)?.name ?? st.specialist,
      instruction: planned?.instruction ?? "",
      text: st.text,
      done: true,
      ok: true,
    };
  }
  for (const ev of meta.tools || []) {
    if (ev.type === "tool_call") run.tools.push({ id: ev.id, name: ev.name, arguments: ev.arguments, specialist: ev.specialist });
    if (ev.type === "tool_result") {
      const t = run.tools.find((x) => x.id === ev.id);
      if (t) Object.assign(t, { result: ev.content, ok: ev.ok, file: ev.file });
    }
  }
  return run;
}
