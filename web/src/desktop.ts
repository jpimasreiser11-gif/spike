// Desktop actions (A19): what the screen of a task shows, as pure functions (the strings in both languages, the
// reducer for a task's events, the crop of the screenshot a card shows). Unit-tested in desktop.test.ts.
import type { CSSProperties } from "react";

export type Region = { x: number; y: number; w: number; h: number; image_w: number; image_h: number; points: { x: number; y: number }[] };
export type ActionInfo = {
  name: string; x?: number; y?: number; from_x?: number; from_y?: number; text?: string; chars?: number; key?: string;
  modifiers?: string; direction?: string; amount?: number; repeat?: number; seconds?: number;
};
export type Sensitive = { kind: string; reason: string };
export type Decision = "waiting" | "approve" | "batch" | "auto" | "deny" | "stop" | "timeout";
export type Card = {
  id: string; step: number; action: ActionInfo; region: Region | null; shot: number; masked: boolean; auto: boolean;
  note: string; sensitive: Sensitive | null; decision: Decision; n?: number; left?: number; result?: "ok" | "failed"; message?: string;
};
export type Step = { id: string; step: number; action: ActionInfo; ok: boolean; message?: string };
export type Item = { kind: "text"; text: string } | { kind: "card"; card: Card } | { kind: "step"; step: Step };
export type Done = {
  reason: string; steps: number; text: string; error: string | null; usage: { input: number; output: number; calls: number };
  cost: number | null; shots: string[];
};
export type DesktopRun = {
  phase: "idle" | "starting" | "running" | "done";
  goal: string; task?: string; conversation?: string; provider?: string; model?: string; maxSteps?: number; tool?: string;
  shot?: { w: number; h: number }; // the size of the screenshots the model sees
  items: Item[]; done?: Done; error?: string;
};
export type Estimate = {
  max_steps: number; calls: number; tokens_in: number; tokens_out: number; screenshot_tokens: number; overhead_tokens: number;
  cost: number | null; priced: boolean; provider: string; model: string; tool: string;
};
/** One action in the record kept with the chat (the same fields as a card's action, with what was decided). */
export type RecordAction = Omit<ActionInfo, "name"> & { step: number; action: string; decision: string; ok: boolean; result?: string; sensitive?: string };
export type DesktopRecord = {
  task: string; goal: string; provider: string; model: string; tool: string | null; max_steps: number; steps: number;
  reason: string; error: string | null; final: string; actions: RecordAction[]; screenshots: string; shots: string[];
  usage: { input: number; output: number; calls: number };
};
export type DesktopStatus = {
  settings: { enabled: boolean; provider_id: string; max_steps: number; tool: string };
  driver: { available: boolean; backend: string; reason: string; code: string; needs: string; supports: string[]; notes: string[] };
  providers: { id: string; name: string; model: string; ok: boolean; code: string; reason: string }[];
  hard_max_steps: number; running: boolean; task: string | null;
};

export const MAX_BATCH = 5;
export const batchChoices = (): number[] => Array.from({ length: MAX_BATCH - 1 }, (_, i) => i + 2);

export const emptyDesktopRun = (goal = ""): DesktopRun => ({ phase: "idle", goal, items: [] });

const actionOf = (a: ActionInfo | undefined): ActionInfo => a ?? { name: "?" };

/** The reducer for a task's Server-Sent Events. */
export function applyDesktopEvent(run: DesktopRun, ev: { type: string; [key: string]: any }): DesktopRun {
  switch (ev.type) {
    case "desktop_conversation":
      return { ...run, conversation: ev.id };
    case "desktop_start":
      return {
        ...run, phase: "running", task: ev.task, provider: ev.provider, model: ev.model, maxSteps: ev.max_steps, tool: ev.tool,
        shot: ev.screen ? { w: ev.screen.shot_width, h: ev.screen.shot_height } : undefined,
      };
    case "desktop_text":
      return { ...run, items: [...run.items, { kind: "text", text: ev.text }] };
    case "desktop_action": {
      const card: Card = {
        id: ev.id, step: ev.step, action: actionOf(ev.action), region: ev.region ?? null, shot: ev.shot, masked: Boolean(ev.masked),
        auto: Boolean(ev.auto), note: ev.note ?? "", sensitive: ev.sensitive ?? null, decision: ev.auto ? "auto" : "waiting",
      };
      return { ...run, items: [...run.items, { kind: "card", card }] };
    }
    case "desktop_resolved":
      return mapCard(run, ev.id, (c) => ({ ...c, decision: ev.decision as Decision, n: ev.n, left: ev.left }));
    case "desktop_result":
      return mapCard(run, ev.id, (c) => ({ ...c, result: ev.ok ? "ok" : "failed", message: ev.ok ? undefined : ev.message }));
    case "desktop_step":
      return { ...run, items: [...run.items, { kind: "step", step: { id: ev.id, step: ev.step, action: actionOf(ev.action), ok: Boolean(ev.ok), message: ev.message } }] };
    case "desktop_error":
      return { ...run, error: ev.message };
    case "desktop_done":
      return {
        ...run, phase: "done", error: run.error ?? ev.error ?? undefined,
        done: { reason: ev.reason, steps: ev.steps, text: ev.text ?? "", error: ev.error ?? null, usage: ev.usage, cost: ev.cost ?? null, shots: ev.shots ?? [] },
      };
    default:
      return run;
  }
}

function mapCard(run: DesktopRun, id: string, fn: (c: Card) => Card): DesktopRun {
  return { ...run, items: run.items.map((it) => (it.kind === "card" && it.card.id === id ? { kind: "card", card: fn(it.card) } : it)) };
}

/** The card that waits for the user's answer, if any. */
export function waitingCard(run: DesktopRun): Card | undefined {
  for (let i = run.items.length - 1; i >= 0; i--) {
    const it = run.items[i];
    if (it.kind === "card" && it.card.decision === "waiting") return it.card;
  }
  return undefined;
}

/** The screenshot region a card shows, as the style of a box `width` px wide: a crop of the whole image. */
export function cropStyle(region: Region, url: string, width = 280): { box: CSSProperties; points: { left: number; top: number }[]; scale: number } {
  const scale = width / region.w;
  return {
    scale,
    box: {
      width, height: Math.round(region.h * scale), backgroundImage: `url(${url})`,
      backgroundSize: `${Math.round(region.image_w * scale)}px ${Math.round(region.image_h * scale)}px`,
      backgroundPosition: `-${Math.round(region.x * scale)}px -${Math.round(region.y * scale)}px`, backgroundRepeat: "no-repeat",
    },
    points: region.points.map((p) => ({ left: Math.round((p.x - region.x) * scale), top: Math.round((p.y - region.y) * scale) })),
  };
}

export const shotUrl = (task: string, n: number) => `/api/desktop/shots/${task}/${n}`;

/** What a card shows of its screenshot: the region around the action, or the whole screen for an action that points nowhere. */
export function regionOf(card: Card, shot?: { w: number; h: number }): Region | null {
  if (card.region) return card.region;
  return shot ? { x: 0, y: 0, w: shot.w, h: shot.h, image_w: shot.w, image_h: shot.h, points: [] } : null;
}

export type Strings = typeof ES;

const ES = {
  setting: "Control del escritorio (solo con un proveedor con computer use)",
  tab: "Escritorio",
  open: "Escritorio",
  intro: "SPIKE puede mirar tu pantalla y mover el ratón o escribir por ti, pero solo a través de un proveedor de API que ofrezca una herramienta de uso del ordenador (computer use) y que tú hayas configurado. Un modelo local nunca controla tu escritorio. Está apagado por defecto.",
  rules: [
    "Cada acción se te muestra con la parte de la pantalla donde actuará y no se ejecuta hasta que la apruebas.",
    "«Aprobar las siguientes» cubre como máximo 5 acciones. Comprar, enviar, borrar, pulsar Enter o escribir en un campo de contraseña siempre preguntan.",
    "Las capturas solo se envían al proveedor que elijas, y solo si le permites recibir tus archivos y las peticiones de pago. Se quedan en memoria en este ordenador; solo se guardan si lo pides.",
    "Una tarea tiene un tope de pasos y puedes detenerla en cualquier momento con el botón Detener.",
    "Lo que aparezca en la pantalla (páginas, correos, documentos) puede intentar dar órdenes al modelo. Vigila cada acción: la aprobación es tu protección.",
  ],
  provider: "Proveedor que hará las acciones", noProvider: "Elige un proveedor",
  maxSteps: "Pasos máximos por tarea", maxStepsHint: "Tope duro: 50.",
  tool: "Forma de la herramienta de computer use", toolHint: "Automática sigue la tabla de modelos documentada; cámbiala solo si el proveedor rechaza la herramienta.",
  tools: { auto: "Automática (según el modelo)", toolset: "Conjunto de herramientas (modelos 5.5)", computer_20251124: "computer_20251124 (modelos intermedios)", computer_20250124: "computer_20250124 (modelos anteriores)" } as Record<string, string>,
  driver: "Este ordenador", driverOk: "Se puede controlar con", driverNo: "No se puede controlar", needs: "Instala", can: "Puede", notes: "Notas",
  driverCodes: {
    wayland: "Es una sesión Wayland; las herramientas que usa SPIKE solo controlan X11.", no_display: "No hay pantalla gráfica ($DISPLAY).",
    no_xdotool: "Falta xdotool.", no_capture: "Falta un programa de capturas (ImageMagick o scrot).", display_unreachable: "No se puede acceder a la pantalla.",
    no_powershell: "No se encontró PowerShell.", no_macos_tools: "Faltan programas de macOS.", unsupported_os: "Este sistema no está soportado.",
  } as Record<string, string>,
  providerCodes: {
    no_provider: "No hay proveedor elegido.", local: "Es un modelo local: nunca controla el escritorio.", unsupported: "Su API no tiene una herramienta de computer use que SPIKE use.",
    no_key: "Falta la API key.", paid: "No permites peticiones de pago a este proveedor.", privacy: "No permites que reciba el contenido de tus archivos (las capturas lo son).",
    limit: "Alcanzó su tope mensual.",
  } as Record<string, string>,
  start: "Iniciar una tarea de escritorio", startNeeds: "Activa el control del escritorio y elige un proveedor que pueda usarlo.",
  saved: "Guardado",
  // the task
  title: "Tarea de escritorio", goal: "¿Qué quieres que haga en tu pantalla?", goalPlaceholder: "Por ejemplo: abre la calculadora y calcula 6 por 7",
  keep: "Guardar las capturas de esta tarea en la prueba del chat", keepHint: "Se guardan en este ordenador y van en el paquete de prueba. Sin marcar, solo quedan las acciones.",
  begin: "Empezar", cancel: "Cancelar", close: "Cerrar", stopClose: "Detener y cerrar", stop: "Detener", running: "En marcha",
  estimate: "Antes de empezar", estimating: "Calculando el coste…",
  estimateLine: (e: Estimate) => `Hasta ${e.calls} peticiones a ${e.provider} (${e.model || "modelo del proveedor"}), unos ${e.tokens_in.toLocaleString()} tokens de entrada y ${e.tokens_out.toLocaleString()} de salida como máximo (cada petición lleva la herramienta y todas las capturas hechas).`,
  costLine: (cost: number) => `Coste máximo estimado: ${cost.toFixed(2)} con los precios que tú pusiste.`,
  noPrice: "Sin precios configurados para este proveedor: SPIKE no puede calcular el coste. Ponlos en Ajustes › Proveedores.",
  stepsLeft: (n: number, max: number) => `Paso ${n} de ${max} como máximo`,
  waiting: "Espera tu aprobación", approve: "Aprobar", approveNext: "Aprobar las siguientes", deny: "Denegar", alwaysAsks: "Esta acción siempre pregunta",
  decided: { waiting: "esperando", approve: "aprobada", batch: "aprobada, y las siguientes", auto: "aprobada en lote", deny: "denegada", stop: "detenida", timeout: "sin respuesta" } as Record<Decision, string>,
  resultOk: "hecha", resultFailed: "falló", refusedShort: "no disponible",
  batchLeft: (n: number) => `${n} más sin preguntar`,
  password: "Contenido oculto", model: "El modelo dice",
  sensitive: { purchase: "compra o pago", send: "envío o publicación", delete: "borrado", password: "contraseña, tarjeta o código", submit: "Enter o enviar un formulario", close: "cerrar un programa", labelled: "marcada como sensible por el modelo" } as Record<string, string>,
  reasons: {
    finished: "terminó", stopped: "detenida por ti", step_limit: "se detuvo al llegar al tope de pasos", timeout: "se detuvo: nadie respondió a una aprobación",
    error: "se detuvo por un error", refused: "el modelo no quiso continuar", cut: "la respuesta del modelo se cortó", running: "en marcha",
  } as Record<string, string>,
  summary: (steps: number, reason: string) => `Tarea de escritorio: ${steps} ${steps === 1 ? "paso" : "pasos"}, ${reason}.`,
  tokens: "tokens", cost: "coste", openChat: "Abrir el chat", another: "Otra tarea", recordTitle: "Acciones", shotsKept: "Capturas guardadas en la prueba", shotsNot: "Sin capturas guardadas",
  action: {
    clicks: { left_click: "Clic", right_click: "Clic derecho", middle_click: "Clic central", double_click: "Doble clic", triple_click: "Triple clic" } as Record<string, string>,
    at: (x: number, y: number) => `en (${x}, ${y})`, atMouse: "donde está el ratón", move: (x: number, y: number) => `Mover el ratón a (${x}, ${y})`,
    drag: (a: number, b: number, x: number, y: number) => `Arrastrar de (${a}, ${b}) a (${x}, ${y})`,
    scroll: (dir: string, n: number) => `Desplazar ${dir} ${n}`, dirs: { up: "arriba", down: "abajo", left: "a la izquierda", right: "a la derecha" } as Record<string, string>,
    type: (text: string) => `Escribir «${text}»`, typeHidden: (n: number) => `Escribir ${n} caracteres (ocultos)`,
    key: (key: string, n?: number) => `Pulsar ${key}${n && n > 1 ? ` × ${n}` : ""}`, wait: (s: number) => `Esperar ${s} s`,
    screenshot: "Captura de pantalla", cursor_position: "Leer la posición del ratón", withKeys: (keys: string) => `con ${keys}`,
  },
};

const EN: Strings = {
  setting: "Desktop control (only with a provider that has computer use)",
  tab: "Desktop",
  open: "Desktop",
  intro: "SPIKE can look at your screen and move the mouse or type for you, but only through an API provider that offers a computer-use tool and that you have set up. A local model never controls your desktop. It is off by default.",
  rules: [
    "Every action is shown to you with the part of the screen where it will act, and it does not run until you approve it.",
    "“Approve the next” covers at most 5 actions. Buying, sending, deleting, pressing Enter or typing into a password field always ask.",
    "Screenshots are sent only to the provider you choose, and only if you let it receive your files and paid requests. They stay in memory on this computer; they are saved only if you ask.",
    "A task has a step limit and you can stop it at any moment with the Stop button.",
    "What appears on the screen (pages, emails, documents) may try to give orders to the model. Watch every action: your approval is your protection.",
  ],
  provider: "Provider that will do the actions", noProvider: "Choose a provider",
  maxSteps: "Maximum steps per task", maxStepsHint: "Hard limit: 50.",
  tool: "Form of the computer-use tool", toolHint: "Automatic follows the documented model table; change it only if the provider rejects the tool.",
  tools: { auto: "Automatic (by model)", toolset: "Toolset (5.5 models)", computer_20251124: "computer_20251124 (middle models)", computer_20250124: "computer_20250124 (earlier models)" },
  driver: "This computer", driverOk: "Can be controlled with", driverNo: "Cannot be controlled", needs: "Install", can: "Can do", notes: "Notes",
  driverCodes: {
    wayland: "This is a Wayland session; the tools SPIKE uses only control X11.", no_display: "There is no graphical display ($DISPLAY).",
    no_xdotool: "xdotool is missing.", no_capture: "A screenshot program (ImageMagick or scrot) is missing.", display_unreachable: "The display cannot be reached.",
    no_powershell: "PowerShell was not found.", no_macos_tools: "macOS programs are missing.", unsupported_os: "This system is not supported.",
  },
  providerCodes: {
    no_provider: "No provider chosen.", local: "It is a local model: it never controls the desktop.", unsupported: "Its API has no computer-use tool that SPIKE uses.",
    no_key: "The API key is missing.", paid: "You do not allow paid requests to this provider.", privacy: "You do not let it receive your files' contents (screenshots count).",
    limit: "It reached its monthly limit.",
  },
  start: "Start a desktop task", startNeeds: "Turn on desktop control and choose a provider that can do it.",
  saved: "Saved",
  title: "Desktop task", goal: "What do you want done on your screen?", goalPlaceholder: "For example: open the calculator and work out 6 times 7",
  keep: "Keep this task's screenshots in the chat's proof package", keepHint: "They are saved on this computer and go in the proof package. Unticked, only the actions are kept.",
  begin: "Start", cancel: "Cancel", close: "Close", stopClose: "Stop and close", stop: "Stop", running: "Running",
  estimate: "Before you start", estimating: "Working out the cost…",
  estimateLine: (e: Estimate) => `Up to ${e.calls} requests to ${e.provider} (${e.model || "the provider's model"}), about ${e.tokens_in.toLocaleString()} input and ${e.tokens_out.toLocaleString()} output tokens at most (every request carries the tool and all the screenshots so far).`,
  costLine: (cost: number) => `Estimated maximum cost: ${cost.toFixed(2)} at the prices you entered.`,
  noPrice: "No prices set for this provider: SPIKE cannot work out the cost. Enter them in Settings › Providers.",
  stepsLeft: (n: number, max: number) => `Step ${n} of at most ${max}`,
  waiting: "Waiting for your approval", approve: "Approve", approveNext: "Approve the next", deny: "Deny", alwaysAsks: "This action always asks",
  decided: { waiting: "waiting", approve: "approved", batch: "approved, and the next ones", auto: "approved in a batch", deny: "denied", stop: "stopped", timeout: "no answer" },
  resultOk: "done", resultFailed: "failed", refusedShort: "not available",
  batchLeft: (n: number) => `${n} more without asking`,
  password: "Hidden content", model: "The model says",
  sensitive: { purchase: "purchase or payment", send: "sending or posting", delete: "deletion", password: "password, card or code", submit: "Enter or submitting a form", close: "closing a program", labelled: "marked sensitive by the model" },
  reasons: {
    finished: "finished", stopped: "stopped by you", step_limit: "stopped at the step limit", timeout: "stopped: no answer to an approval",
    error: "stopped by an error", refused: "the model declined to continue", cut: "the model's answer was cut off", running: "running",
  },
  summary: (steps: number, reason: string) => `Desktop task: ${steps} ${steps === 1 ? "step" : "steps"}, ${reason}.`,
  tokens: "tokens", cost: "cost", openChat: "Open the chat", another: "Another task", recordTitle: "Actions", shotsKept: "Screenshots kept in the proof package", shotsNot: "No screenshots kept",
  action: {
    clicks: { left_click: "Click", right_click: "Right click", middle_click: "Middle click", double_click: "Double click", triple_click: "Triple click" },
    at: (x: number, y: number) => `at (${x}, ${y})`, atMouse: "where the mouse is", move: (x: number, y: number) => `Move the mouse to (${x}, ${y})`,
    drag: (a: number, b: number, x: number, y: number) => `Drag from (${a}, ${b}) to (${x}, ${y})`,
    scroll: (dir: string, n: number) => `Scroll ${dir} ${n}`, dirs: { up: "up", down: "down", left: "left", right: "right" },
    type: (text: string) => `Type “${text}”`, typeHidden: (n: number) => `Type ${n} characters (hidden)`,
    key: (key: string, n?: number) => `Press ${key}${n && n > 1 ? ` × ${n}` : ""}`, wait: (s: number) => `Wait ${s} s`,
    screenshot: "Screenshot", cursor_position: "Read the mouse position", withKeys: (keys: string) => `with ${keys}`,
  },
};

export const DESKTOP_STRINGS = { es: ES, en: EN };

/** A short phrase for an action, in the language of `s`. A masked text (a password) is never in `a`, only its length. */
export function actionLabel(a: ActionInfo, s: Strings, masked = false): string {
  const A = s.action;
  const has = (v: number | undefined): v is number => typeof v === "number";
  const keys = a.modifiers ? ` ${A.withKeys(a.modifiers)}` : "";
  switch (a.name) {
    case "left_click": case "right_click": case "middle_click": case "double_click": case "triple_click":
      return `${A.clicks[a.name]} ${has(a.x) && has(a.y) ? A.at(a.x, a.y) : A.atMouse}${keys}`;
    case "mouse_move":
      return has(a.x) && has(a.y) ? A.move(a.x, a.y) : A.screenshot;
    case "left_click_drag":
      return has(a.from_x) && has(a.from_y) && has(a.x) && has(a.y) ? A.drag(a.from_x, a.from_y, a.x, a.y) + keys : A.screenshot;
    case "scroll":
      return `${A.scroll(A.dirs[a.direction ?? ""] ?? a.direction ?? "", a.amount ?? 0)}${has(a.x) && has(a.y) ? ` ${A.at(a.x, a.y)}` : ""}${keys}`;
    case "type":
      return masked || a.text === undefined ? A.typeHidden(a.chars ?? 0) : A.type(a.text);
    case "key":
      return A.key(a.key ?? "", a.repeat);
    case "wait":
      return A.wait(a.seconds ?? 0);
    case "screenshot":
      return A.screenshot;
    case "cursor_position":
      return A.cursor_position;
    default:
      return a.name;
  }
}

/** A stored action of the chat's record as the same shape a card has. */
export function recordAction(r: RecordAction): ActionInfo {
  const { action, step: _step, decision: _decision, ok: _ok, result: _result, sensitive: _sensitive, ...rest } = r;
  return { ...rest, name: action };
}

export const decisionText = (d: string, s: Strings): string => (s.decided as Record<string, string>)[d] ?? (d === "refused" ? s.refusedShort : d);

/** "Up to N requests…" and the cost line (or the reason there is none). */
export function estimateText(e: Estimate, s: Strings): string[] {
  return [s.estimateLine(e), e.priced && e.cost !== null ? s.costLine(e.cost) : s.noPrice];
}

/** Whether a task can start from the settings page, and why not. */
export function startBlock(status: DesktopStatus | null, s: Strings): string {
  if (!status) return s.startNeeds;
  const chosen = status.providers.find((p) => p.id === status.settings.provider_id);
  if (!status.settings.enabled || !chosen?.ok || !status.driver.available) return s.startNeeds;
  return "";
}
