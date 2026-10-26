import { t } from "./i18n";
import { fill, money } from "./trust";
import type { ChatEvent, MindsEstimate, MindsSpec, PermissionState, ProtoComparison, ProtoLabel, ProtoResult, ProtoRow, ProtoRun } from "./types";

export const MIN_MINDS = 2;
export const MAX_MINDS = 4;
export type MindPick = { mode: string; provider_id: string }; // "" = as the chat

/** The `parallel_minds` a message sends: null (off: nothing is sent), `n` minds that differ by temperature, or one per
 * pick when the user chose a specialist or a provider for each mind. */
export function mindsSpec(on: boolean, n: number, picks: MindPick[] | null): MindsSpec | null {
  if (!on) return null;
  if (picks) return { picks: picks.slice(0, n).map((p) => ({ ...(p.mode ? { mode: p.mode } : {}), ...(p.provider_id ? { provider_id: p.provider_id } : {}) })) };
  return { n };
}

/** "×3 tiempo y tokens": shown before anything runs. */
export const multiplierText = (n: number) => fill(t.minds.multiplier, { n });

/** What to tell the user about a batch before they send it: the multiplier first, then the cost at their prices (or why
 * there is none), that a multi-step mind makes more calls, and the guard's reason if it would stop the batch. */
export function estimateLines(est: MindsEstimate): string[] {
  const lines = [multiplierText(est.multiplier)];
  if (est.cost !== null) lines.push(fill(t.minds.cost, { cost: money(est.cost) }));
  if (est.unpriced.length) lines.push(fill(t.minds.noPrice, { names: est.unpriced.join(", ") }));
  else if (est.cost === null && est.providers.length && est.providers.every((p) => p.local)) lines.push(t.minds.local);
  if (est.multi_step) lines.push(t.minds.multiStep);
  return lines;
}

/** Why the chosen mind won, in the user's language. */
export const whyText = (why: string | undefined, chosen: number | null | undefined) =>
  fill(t.minds.why[why ?? "none"] ?? "", { i: (chosen ?? 0) + 1 });

// ---------------------------------------------------------------- Parallel Prototypes
export type Phase = "waiting" | "building" | "checking" | "done" | "failed";

/** A run of Parallel Prototypes while it streams: the run's record as it fills in, each approach's phase, and the
 * permission questions the builds and the test runs ask (answered like any other). */
export type ProtoLive = {
  run?: ProtoRun; phase: Record<ProtoLabel, Phase>; steps: Record<ProtoLabel, number>;
  permissions: PermissionState[]; error?: string;
};

export const emptyLive = (): ProtoLive => ({ phase: { a: "waiting", b: "waiting" }, steps: { a: 0, b: 0 }, permissions: [] });

/** Pure reducer for the events of POST /api/forge/prototypes (tested in parallel.test.ts). */
export function applyProtoEvent(live: ProtoLive, ev: ChatEvent): ProtoLive {
  const label = ev.proto as ProtoLabel | undefined;
  switch (ev.type) {
    case "proto_start": {
      const { type: _type, ...run } = ev;
      return { ...live, run: run as ProtoRun };
    }
    case "proto_build":
      return label ? { ...live, phase: { ...live.phase, [label]: "building" } } : live;
    case "subtask_start":
      return label ? { ...live, steps: { ...live.steps, [label]: live.steps[label] + 1 } } : live;
    case "proto_checks":
      return label ? { ...live, phase: { ...live.phase, [label]: "checking" } } : live;
    case "proto_result": {
      if (!label || !live.run) return live;
      const { type: _type, proto: _proto, ...result } = ev;
      return {
        ...live,
        phase: { ...live.phase, [label]: result.status === "failed" ? "failed" : "done" },
        run: { ...live.run, approaches: live.run.approaches.map((a) => (a.label === label ? { ...a, ...(result as Partial<ProtoResult>) } : a)) },
      };
    }
    case "proto_compare":
      return live.run ? { ...live, run: { ...live.run, status: "built", comparison: { rows: ev.rows, leader: ev.leader, basis: ev.basis } } } : live;
    case "permission_request":
      return { ...live, permissions: [...live.permissions, { id: ev.id, tool: ev.tool, risk: ev.risk, arguments: ev.arguments, status: "pending", reason: ev.reason,
        code: ev.code, once: ev.once, domain: ev.domain, isolation: ev.isolation }] };
    case "permission_resolved":
      return { ...live, permissions: live.permissions.map((p) => (p.id === ev.id ? { ...p, status: ev.decision } : p)) };
    case "error":
      return label ? live : { ...live, error: ev.message };
    default:
      return live;
  }
}

const hasComparison = (c: ProtoRun["comparison"]): c is ProtoComparison => Array.isArray((c as ProtoComparison).rows);
export const comparisonOf = (run: ProtoRun): ProtoComparison | null => (hasComparison(run.comparison) ? run.comparison : null);

/** The cells of one approach's column of the comparison table (all from the run's own numbers). */
export function rowCells(row: ProtoRow) {
  return {
    tests: row.tests_ran ? `${row.tests_passed}/${row.tests_total}` : t.proto.notRun,
    checks: `${row.checks_passed}/${row.checks_total}`,
    files: String(row.files_changed),
    lines: `+${row.insertions} −${row.deletions}`,
    time: `${row.seconds.toFixed(1)} s`,
  };
}

/** The suggestion the numbers allow, or that they allow none. */
export function leaderText(c: ProtoComparison): string {
  if (!c.leader) return t.proto.noLeader;
  return fill(t.proto.suggests, { label: c.leader.toUpperCase(), basis: c.basis === "tests" ? t.proto.basisTests : t.proto.basisChecks });
}
