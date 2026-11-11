import type { ChatEvent, Criterion, RunState } from "./types";

/** O2: one task (a Forge or multi-step answer, or a Dev session) in four parts: the plan, every action with the
 * permission it got, the files it changed and what it delivered. Rebuilt only from the events SPIKE already keeps with
 * each answer, so a task reopens after a restart exactly as it ended and nothing runs again. Unit-tested in
 * taskSpace.test.ts. */

export type StepStatus = "waiting" | "running" | "done" | "failed" | "stopped";
export type TaskStep = { id: string; name: string; instruction: string; status: StepStatus; round?: number };

/** auto: the tool was allowed by the settings; refused: the settings or the review blocked it before anyone was asked;
 * unanswered: the run ended while the card waited, so the call never ran. */
export type Permission = "auto" | "pending" | "allow_once" | "allow_always" | "deny" | "refused" | "unanswered";
export type ActionStatus = "running" | "ok" | "failed" | "stopped";
export type TaskAction = {
  key: string; id: string; tool: string; specialist?: string; detail: string; permission: Permission; status: ActionStatus;
  file?: string; checkpoint?: string; undone?: boolean;
};
export type TaskFile = { path: string; tool: string; checkpoint?: string; undone: boolean };
export type TaskStatus = RunState["status"];
export type Deliverable = { path: string; ok: boolean };
export type TaskView = {
  status: TaskStatus; steps: TaskStep[]; actions: TaskAction[]; files: TaskFile[];
  deliverables: Deliverable[]; criteria: Criterion[]; verified?: boolean;
};

const ACTIVE = new Set<TaskStatus>(["idle", "planning", "running", "verifying", "synthesizing"]);
// tool results that mean the call never ran because the settings or the review stopped it (spike/agent/loop.py)
const REFUSED = [/^error: refused:/, /^error: the user has disabled/, /needs the user's approval/];
const DETAIL_KEYS = ["path", "command", "url", "query", "file", "name", "target"];

function clip(value: unknown, max = 90): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** The argument that says what a call is about: a path, a command, an address… */
export function actionDetail(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  for (const key of DETAIL_KEYS) if (typeof args[key] === "string" && args[key]) return clip(args[key]);
  const first = Object.values(args).find((v) => typeof v === "string" && v.trim());
  return first ? clip(first) : "";
}

/** How the run ended according to its own events, or `fallback` (a stored answer's status) when they do not say. */
function statusOf(events: ChatEvent[], fallback?: TaskStatus): TaskStatus {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev.mind !== undefined) continue;
    if (ev.type === "done") return ev.error ? "error" : "done";
    if (ev.type === "error") return "error";
  }
  return fallback ?? (events.length ? "running" : "idle");
}

/** The task of one run. `run` (the live or stored answer) gives the status when the events stop early and the undo
 * state of each change, which the server updates after the run. */
export function taskFromEvents(events: ChatEvent[] = [], run?: Pick<RunState, "status" | "tools" | "forge">, turn = 0): TaskView {
  const own = events.filter((ev) => ev.mind === undefined || ev.type === "permission_request" || ev.type === "permission_resolved");
  const status = run && !ACTIVE.has(run.status) ? run.status : statusOf(own, run?.status);
  const finished = !ACTIVE.has(status);

  const planned: TaskStep[] = [];
  const extra: TaskStep[] = [];
  const stepOf = new Map<string, TaskStep>(); // subtask id -> its step
  const actions: TaskAction[] = [];
  const byCall = new Map<string, TaskAction>(); // the latest action of a call id (ids can repeat across steps)
  const byRequest = new Map<string, TaskAction>();
  let report = run?.forge?.report;

  own.forEach((ev, i) => {
    switch (ev.type) {
      case "plan":
        planned.splice(0, planned.length, ...(ev.subtasks ?? []).map((s: { id: string; specialist: string; instruction: string }) =>
          ({ id: s.id, name: s.specialist, instruction: s.instruction ?? "", status: "waiting" as StepStatus })));
        break;
      case "subtask_start": {
        const key = String(ev.task ?? ev.subtask);
        let step = planned.find((s) => s.id === key) ?? extra.find((s) => s.id === key);
        if (!step) extra.push(step = { id: key, name: ev.specialist, instruction: ev.instruction ?? "", status: "waiting" });
        Object.assign(step, { name: ev.name || step.name, status: "running", round: ev.round });
        stepOf.set(String(ev.subtask), step);
        break;
      }
      case "subtask_end": {
        const step = stepOf.get(String(ev.subtask));
        if (step) step.status = ev.ok === false ? "failed" : "done";
        break;
      }
      case "tool_call": {
        const action: TaskAction = { key: `${turn}:${i}`, id: String(ev.id), tool: String(ev.name ?? ""), specialist: ev.specialist,
          detail: actionDetail(ev.arguments), permission: "auto", status: "running" };
        actions.push(action);
        byCall.set(action.id, action);
        break;
      }
      case "permission_request": {
        const action = byCall.get(String(ev.call_id));
        if (action) { action.permission = "pending"; byRequest.set(String(ev.id), action); }
        break;
      }
      case "permission_resolved": {
        const action = byRequest.get(String(ev.id));
        if (action && ["allow_once", "allow_always", "deny"].includes(ev.decision)) action.permission = ev.decision;
        break;
      }
      case "tool_result": {
        const action = byCall.get(String(ev.id));
        if (!action || action.status !== "running") break;
        action.status = ev.ok ? "ok" : "failed";
        if (!ev.ok && action.permission === "auto" && REFUSED.some((re) => re.test(String(ev.content ?? "")))) action.permission = "refused";
        if (ev.file) action.file = ev.file;
        if (ev.checkpoint) action.checkpoint = ev.checkpoint;
        if (ev.undone) action.undone = true;
        break;
      }
      case "forge_report": {
        const { type: _type, ...rest } = ev;
        report = rest as NonNullable<RunState["forge"]>["report"];
        break;
      }
    }
  });

  for (const action of actions) {
    if (finished && action.status === "running") action.status = "stopped";
    if (finished && action.permission === "pending") action.permission = "unanswered";
    const stored = run?.tools.find((tool) => tool.id === action.id && tool.checkpoint && tool.checkpoint === action.checkpoint);
    if (stored?.undone) action.undone = true;
  }
  const steps = [...planned, ...extra];
  if (finished) for (const step of steps) if (step.status === "running") step.status = "stopped";

  const files: TaskFile[] = [];
  for (const action of actions) {
    if (action.status !== "ok" || !action.checkpoint) continue;
    const path = action.file || action.detail;
    if (path) files.push({ path, tool: action.tool, checkpoint: action.checkpoint, undone: !!action.undone });
  }
  const deliverables = (report?.deliverables ?? []).map((d) => ({ path: d.path, ok: d.ok }));
  return { status, steps, actions, files, deliverables, criteria: report?.criteria ?? [], verified: report?.verified };
}

/** A Dev session: its turns one after another. The plan is the latest turn's; actions, files and deliverables add up. */
export function mergeTasks(views: TaskView[]): TaskView {
  const last = views[views.length - 1];
  if (!last) return { status: "idle", steps: [], actions: [], files: [], deliverables: [], criteria: [] };
  const deliverables = new Map<string, Deliverable>();
  for (const v of views) for (const d of v.deliverables) deliverables.set(d.path, d);
  return {
    status: last.status, steps: last.steps, criteria: last.criteria, verified: last.verified,
    actions: views.flatMap((v) => v.actions), files: views.flatMap((v) => v.files), deliverables: [...deliverables.values()],
  };
}

/** The status a stored answer ended with (its meta, as the chat and Dev sessions save it). */
export function storedStatus(meta: Record<string, any> | undefined): TaskStatus {
  return meta?.error ? "error" : meta?.stopped || meta?.cancelled ? "stopped" : "done";
}

/** Whether an answer is worth a task space: it planned steps or used tools. */
export function hasTask(run: Pick<RunState, "plan" | "tools" | "order" | "events">): boolean {
  return !!run.events?.length && (run.tools.length > 0 || !!run.plan || run.order.length > 1);
}
