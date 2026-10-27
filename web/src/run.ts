import { projectError } from "./i18n";
import type { ChatEvent, ForgeReport, MindState, MindsState, RunState, StoredMessage, TrustState, VerifyState } from "./types";

export const emptyRun = (): RunState => ({
  status: "idle",
  subtasks: {},
  order: [],
  tools: [],
  permissions: [],
  text: "",
  reasoning: "",
});

// What a mind's run asks of the whole answer, not of that mind: a permission or a question is answered once.
const SHARED = new Set(["permission_request", "permission_resolved", "question", "answered", "privacy", "context_trimmed"]);

/** An event of one mind (Parallel Minds) goes to that mind's own run, so its text and steps never mix with another's. */
function applyMindEvent(state: RunState, ev: ChatEvent): RunState {
  const { mind, ...rest } = ev;
  if (SHARED.has(ev.type)) return applyEvent(state, rest as ChatEvent);
  const minds = state.minds;
  if (!minds) return state;
  const update = (fn: (m: MindState) => MindState): RunState => ({
    ...state,
    minds: { ...minds, minds: minds.minds.map((m) => (m.index === mind ? fn(m) : m)) },
  });
  switch (ev.type) {
    case "mind_start":
      return update((m) => ({ ...m, run: { ...m.run, status: "running" } }));
    case "mind_result":
      return update((m) => ({
        ...m, ok: ev.ok, counts: ev.counts, verifier_failed: ev.verifier_failed, elapsed: ev.elapsed_s, specialists: ev.specialists, route: ev.route,
        run: { ...m.run, text: ev.text || m.run.text, error: ev.error ?? m.run.error, status: ev.ok ? "done" : "error", trust: ev.trust ?? m.run.trust },
      }));
    default:
      return update((m) => ({ ...m, run: applyEvent(m.run, rest as ChatEvent) }));
  }
}

/** Pure reducer turning orchestrator events into a renderable run. Unit-tested in run.test.ts. */
export function applyEvent(state: RunState, ev: ChatEvent): RunState {
  if (ev.mind !== undefined) return applyMindEvent(state, ev);
  switch (ev.type) {
    case "minds_start":
      return { ...state, status: "running", minds: { n: ev.n, minds: ev.minds.map((m: MindState) => ({ ...m, run: { ...emptyRun(), status: "idle" } })) } };
    case "minds_pick": {
      const minds = state.minds;
      if (!minds) return state;
      const picked: MindsState = { ...minds, chosen: ev.chosen, ranking: ev.ranking, why: ev.why };
      const chosen = minds.minds.find((m) => m.index === ev.chosen);
      if (!chosen) return { ...state, minds: picked };
      const r = chosen.run; // the chosen mind's run becomes the answer's own, as the server stores it
      return { ...state, minds: picked, text: r.text, reasoning: r.reasoning, route: r.route, plan: r.plan, subtasks: r.subtasks, order: r.order,
        tools: r.tools, verify: r.verify, forge: r.forge, skills: r.skills ?? state.skills, contract: r.contract ?? state.contract };
    }
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
            role: ev.role,
            round: ev.round,
            feedback: ev.feedback,
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
    case "verify_start":
      return { ...state, status: "verifying" };
    case "verify": {
      const { type: _type, ...v } = ev;
      return { ...state, status: "running", verify: [...(state.verify ?? []), v as VerifyState] };
    }
    case "forge_report": {
      const { type: _type, ...report } = ev;
      return { ...state, forge: { ...state.forge, report: report as ForgeReport } };
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
    case "tool_result": {
      const i = state.tools.findIndex((t) => t.id === ev.id && t.result === undefined); // ids can repeat across turns
      if (i < 0) return state;
      const tools = state.tools.slice();
      tools[i] = { ...tools[i], result: ev.content, ok: ev.ok, file: ev.file, checkpoint: ev.checkpoint, undone: ev.undone, ui: ev.ui };
      return { ...state, tools };
    }
    case "permission_request":
      return {
        ...state,
        permissions: [
          ...state.permissions,
          { id: ev.id, tool: ev.tool, risk: ev.risk, arguments: ev.arguments, status: "pending", reason: ev.reason, code: ev.code, once: ev.once, domain: ev.domain, isolation: ev.isolation },
        ],
      };
    case "permission_resolved":
      return {
        ...state,
        permissions: state.permissions.map((p) => (p.id === ev.id ? { ...p, status: ev.decision } : p)),
      };
    case "design":
      return { ...state, design: { id: ev.id, name: ev.name } };
    case "skill": {
      const names = (ev.names as string[]).filter((n) => !(state.skills ?? []).includes(n));
      return names.length ? { ...state, skills: [...(state.skills ?? []), ...names] } : state;
    }
    case "memory":
      return { ...state, memory: { rules: ev.rules, semantic: ev.semantic, notes: ev.notes, glossary: ev.glossary } };
    case "contract":
      return { ...state, contract: { valid: ev.valid, attempts: ev.attempts, errors: ev.errors ?? [] } };
    case "question":
      return { ...state, questions: [...(state.questions ?? []), { id: ev.id, question: ev.question, options: ev.options ?? [], status: "pending" }] };
    case "answered":
      return {
        ...state,
        questions: (state.questions ?? []).map((q) => (q.id === ev.id ? { ...q, answer: ev.answer, status: ev.answer == null ? "unanswered" : "answered" } : q)),
      };
    case "memory_saved":
      return { ...state, learn: { ...state.learn, saved: ev.saved } };
    case "correction":
      return { ...state, learn: { ...state.learn, correction: { text: ev.text, status: "proposed" } } };
    case "privacy":
      return { ...state, privacy: { ...state.privacy, [ev.provider]: Math.max(state.privacy?.[ev.provider] ?? 0, ev.withheld) } };
    case "context_trimmed":
      return { ...state, trimmed: ev.dropped };
    case "trust": {
      const { type: _type, ...trust } = ev;
      return { ...state, trust: trust as TrustState };
    }
    case "error":
      return { ...state, status: "error", error: projectError(ev.message) };
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

/** The minds of a stored answer: each with its text and labels; a mind with no result was cut off by a stop. */
function mindsFromStored(m: Record<string, any>): MindsState {
  return {
    n: m.n, chosen: m.chosen ?? null, ranking: m.ranking, why: m.why,
    minds: (m.minds ?? []).map((d: any): MindState => ({
      index: d.index, mode: d.mode, provider_id: d.provider_id, temperature: d.temperature, ok: d.ok, counts: d.counts,
      verifier_failed: d.verifier_failed, elapsed: d.elapsed_s, specialists: d.specialists, route: d.route,
      run: { ...emptyRun(), status: d.ok === undefined ? "stopped" : d.ok ? "done" : "error", text: d.text ?? "", error: d.error ?? undefined, trust: d.trust },
    })),
  };
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
  if (meta.design) run.design = meta.design;
  if (meta.memory) {
    run.memory = { rules: meta.memory.rules, semantic: meta.memory.semantic, notes: meta.memory.notes, glossary: meta.memory.glossary };
  }
  if (meta.privacy) run.privacy = meta.privacy;
  if (meta.events?.length) run.events = meta.events;
  if (meta.learn) run.learn = meta.learn;
  if (meta.contract) run.contract = meta.contract;
  if (meta.verify?.length) run.verify = meta.verify;
  if (meta.forge?.report) run.forge = { report: meta.forge.report };
  if (meta.trust) run.trust = meta.trust;
  if (meta.minds) run.minds = mindsFromStored(meta.minds);
  if (meta.desktop) run.desktop = meta.desktop;
  if (meta.questions?.length) {
    run.questions = meta.questions.map((q: any) => ({ ...q, options: q.options ?? [], status: q.answer == null ? "unanswered" : "answered" }));
  }
  for (const [id, st] of Object.entries<any>(meta.subtasks || {})) {
    const planned = meta.plan?.subtasks?.find((t: any) => t.id === (st.task ?? id));
    run.order.push(id);
    run.subtasks[id] = {
      id,
      specialist: st.specialist,
      name: meta.route?.specialists?.find((s: any) => s.id === st.specialist)?.name ?? st.specialist,
      instruction: planned?.instruction ?? "",
      text: st.text,
      done: true,
      ok: true,
      role: st.role ?? planned?.role,
      round: st.round,
    };
  }
  for (const ev of meta.tools || []) {
    if (ev.type === "tool_call") run.tools.push({ id: ev.id, name: ev.name, arguments: ev.arguments, specialist: ev.specialist });
    if (ev.type === "tool_result") {
      const t = run.tools.find((x) => x.id === ev.id && x.result === undefined); // ids can repeat across turns
      if (t) Object.assign(t, { result: ev.content, ok: ev.ok, file: ev.file, checkpoint: ev.checkpoint, undone: ev.undone, ui: ev.ui });
    }
  }
  return run;
}

/** The run rebuilt from its first `n` events, for the step-by-step view. */
export function runAt(events: ChatEvent[], n: number): RunState {
  return events.slice(0, n).reduce(applyEvent, emptyRun());
}

/** Append an event to a run's recording, merging consecutive text pieces as the server does. */
export function recordEvent(events: ChatEvent[] = [], ev: ChatEvent, t: number): ChatEvent[] {
  const last = events[events.length - 1];
  if ((ev.type === "delta" || ev.type === "reasoning") && last?.type === ev.type && last.subtask === ev.subtask && last.mind === ev.mind) {
    return [...events.slice(0, -1), { ...last, text: last.text + ev.text }];
  }
  return [...events, { ...ev, t }];
}

type TeamStep = { kind: "sub"; id: string } | { kind: "verify"; v: VerifyState };

/** The team's steps in the order they ran: each checker pass after the round it checked. */
export function teamSteps(run: RunState): TeamStep[] {
  const steps: TeamStep[] = [];
  const passes = [...(run.verify ?? [])];
  for (const id of run.order) {
    const round = run.subtasks[id]?.round ?? 1;
    while (passes.length && passes[0].round < round) steps.push({ kind: "verify", v: passes.shift() as VerifyState });
    steps.push({ kind: "sub", id });
  }
  return [...steps, ...passes.map((v) => ({ kind: "verify" as const, v }))];
}
