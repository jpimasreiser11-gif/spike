import { fill } from "./explorer";
import { t } from "./i18n";
import type { ViewQuestion, ViewStep } from "./types";

/** A step of a script file (the JSON kept on this computer), as far as the panel needs to read it. */
export type ScriptStep = {
  action: ViewStep["action"]; url?: string; key?: string; text?: string; values?: string[]; secret?: boolean; submit?: boolean; submits?: boolean;
  element?: string; target?: { by: string; role?: string; name?: string; value?: string; selector?: string };
};
export type ScriptFile = { name: string; steps: ScriptStep[] };

/** What a step acts on, in a few words: the name Playwright gave the element, its selector, or the model's own description. */
export function targetName(step: ScriptStep): string {
  const target = step.target;
  if (!target || target.by === "none") return step.element ?? "";
  if (target.by === "role") return target.name || target.role || "";
  if (target.by === "css") return target.selector ?? "";
  return target.value ?? "";
}

/** The row the panel shows for a step of a saved script (the server describes recorded and replayed steps the same way). */
export function stepRow(step: ScriptStep, n: number): ViewStep {
  const row: ViewStep = { n, action: step.action, name: targetName(step).slice(0, 120) };
  if (step.action === "navigate") row.url = step.url;
  if (step.action === "press") row.key = step.key;
  if (step.action === "type") { if (step.secret) row.secret = true; else row.text = (step.text ?? "").slice(0, 200); }
  if (step.action === "select") row.values = step.values;
  if (step.submits || step.submit) row.submits = true;
  return row;
}

/** One line for a step: `Escribir «Nombre»: Ana`, `Abrir https://…`, `Tecla Enter`. A secret step shows no text. */
export function stepLabel(row: ViewStep): string {
  const v = t.viewRecorder;
  const action = v.actions[row.action] ?? row.action;
  const what = row.action === "navigate" ? row.url ?? "" : row.action === "press" ? row.key ?? "" : row.name ? `«${row.name}»` : "";
  const extra = row.action === "type" ? (row.secret ? ` (${v.asksText})` : row.text ? `: ${row.text}` : "")
    : row.action === "select" ? `: ${(row.values ?? []).join(", ")}` : "";
  return `${action} ${what}${extra}`.trim();
}

/** What the replay asks, in the user's language (the server only sends a code, and a reason in English as a fallback). */
export function questionText(q: ViewQuestion): string {
  const text = t.viewRecorder.questions[q.code];
  return text ? fill(text, { domain: q.domain ?? "" }) : q.reason || q.code;
}

export const optionLabel = (option: string) => t.viewRecorder.options[option] ?? option;

/** `hover: 2, evaluate: 1`: the tools whose calls a script cannot hold, for the note under a recording. */
export const ignoredList = (ignored: Record<string, number>) =>
  Object.entries(ignored).map(([tool, n]) => `${tool.replace(/^browser_/, "")}: ${n}`).join(", ");

export const replayActive = (state: string) => state === "running" || state === "waiting";
