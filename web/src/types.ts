export type Specialist = {
  id: string;
  name: string;
  domain: string;
  description: string;
  adapter: string | null;
  adapter_status: "none" | "planned" | "training" | "trained" | "evaluated";
  sensitive: boolean;
  tools: string[];
};

export type Preset = {
  id: string;
  kind: string;
  name: string;
  base_url: string;
  paid: boolean;
  local: boolean;
  needs_key: boolean;
  key_url: string;
  example_model: string;
};

export type ProviderInfo = {
  id: string;
  kind: string;
  name: string;
  base_url: string;
  model: string;
  paid: boolean;
  allow_paid: boolean;
  local: boolean;
  share_files?: boolean;
  limits?: Limits;
  has_key: boolean;
  preset?: string | null;
  capabilities_effective: Record<string, unknown> | null;
};

export type Conversation = { id: string; title: string; created: number; updated: number; mode: string; project_id?: string | null };

export type Project = { id: string; name: string; instructions: string; mode: string; design: string; created: number; updated: number };

/** A design system (Spike Design): its DESIGN.md and tokens go into the prompt of chats that use it. */
export type DesignSystemInfo = {
  id: string; name: string; category: string; description: string; source: "bundled" | "user";
  has_tokens: boolean; colors: { name: string; value: string }[];
};

export type ProjectFile = { path: string; size: number };

export type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: Record<string, any>;
  created: number;
};

export type RouteSpecialist = {
  id: string;
  name: string;
  provider: string;
  model: string;
  adapter: string | null;
  profile_only: boolean;
};

export type SubtaskState = {
  id: string;
  specialist: string;
  name: string;
  instruction: string;
  text: string;
  done: boolean;
  ok?: boolean;
  elapsed?: number;
  role?: "research" | "execute";
  round?: number; // 2 and 3: the checker sent this step back
  feedback?: string; // what the checker asked to fix
};

export type Criterion = { text: string; ok: boolean | null; note: string }; // ok null: not checked
export type FileCheck = { subtask: string; path: string; ok: boolean; bytes: number };
export type Returned = { subtask: string; fix: string };

/** One pass of the checker over a multi-step run (Collective). */
export type VerifyState = { round: number; method: "llm" | "unavailable"; note: string; returned: Returned[]; criteria: Criterion[]; checks: FileCheck[] };

export type ForgeReport = { verified: boolean; note: string; criteria: Criterion[]; deliverables: FileCheck[]; rounds: number; unresolved: Returned[] };

export type BlueprintStep = { id: string; specialist: string; role: "research" | "execute"; instruction: string; depends_on: string[]; deliverables: string[] };

/** A Forge task as the core model drafted it; the user edits and approves it before anything runs. */
export type Blueprint = { goal: string; requirements: string[]; steps: BlueprintStep[]; criteria: string[]; method: string; note: string };

export type ToolState = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  specialist?: string;
  result?: string;
  ok?: boolean;
  file?: string; // workspace path of a file the tool wrote
  checkpoint?: string; // copy kept before the tool changed files: the step can be undone
  undone?: boolean;
  ui?: { kind: "live_order"; order: LiveOrder } | McpAppUi | DataUi; // something to act on or look at next to the result
};

/** Spike Data: a data file loaded as a table for a query. */
export type DataTableInfo = { name: string; file: string; rows: number; sheet: string | null; columns: { name: string; type: string }[] };
type DataResult = { title: string; sql: string; tables: DataTableInfo[]; columns: string[]; types: string[]; rows: unknown[][]; truncated: boolean };
export type DataTableUi = { kind: "data_table" } & DataResult;
export type ChartUi = { kind: "chart"; spec: Record<string, unknown> } & DataResult;
export type CodeRunUi = { kind: "code_run"; language: string; code: string; output: string; files: string[]; returncode: number | null };
export type DataUi = DataTableUi | ChartUi | CodeRunUi | { kind: "data_tables"; items: DataTableUi[] };

/** An MCP App: the connector tool's result is shown in this `ui://` view of the same server. */
export type McpAppUi = {
  kind: "mcp_app"; connector: string; connector_name: string; tool: string; uri: string;
  result?: { content?: unknown[]; structuredContent?: unknown; isError?: boolean; _meta?: Record<string, unknown> } | null;
};

/** A real exchange order a specialist proposed; only the user's click in the app places it. */
export type LiveOrder = {
  id: string; created: number; exchange: string; sandbox: boolean; symbol: string; side: "buy" | "sell";
  type: "market" | "limit"; amount: number; price: number | null; est_price: number; notional: number;
  status: "proposed" | "sending" | "placed" | "failed" | "cancelled" | "expired"; decided: number | null; result: string;
};

export type LiveSettings = {
  enabled: boolean; exchange: string; sandbox: boolean; no_withdrawal: boolean; max_order: number; max_day: number; symbols: string[];
};

export type LiveStatus = LiveSettings & {
  has_key: boolean; spent_today: number; withdrawals: "yes" | "no" | null; problems: string[]; problem_codes: string[]; testnets: string[];
};

export type PaperOrder = {
  id: string; created: number; exchange: string; symbol: string; side: string; type: string; amount: number;
  limit_price: number | null; status: string; fill_price: number | null; fee: number | null; note: string;
};

export type PaperView = {
  valuation: { quote: string; positions: { asset: string; quantity: number; price: number; value: number }[]; total: number;
    start_cash: number; pnl: number | null; pnl_pct: number | null; unpriced: string[] };
  balances: Record<string, number>; start: { cash: number; quote: string; time: number }; orders: PaperOrder[];
  price_error: string | null;
};

export type FinanceInfo = {
  settings: { exchange: string; live: LiveSettings }; exchanges: string[]; strategies: Record<string, Record<string, number>>;
  live: LiveStatus; live_orders: LiveOrder[];
};

export type PermissionState = {
  id: string;
  tool: string;
  risk: string;
  arguments: Record<string, unknown>;
  status: "pending" | "allow_once" | "allow_always" | "deny" | "sending";
  reason?: string; // why SPIKE asks about this call (a browser page or form), in English
  code?: string; // the reason's name, to show it in the user's language
  once?: boolean; // decided for this call only: no "always"
  domain?: string; // the page's domain, which can be allowed or blocked for good
};

/** A question a specialist asked the user (`ask_user`); the run waits for the answer. */
export type QuestionState = {
  id: string;
  question: string;
  options: string[];
  answer?: string | null; // null: the run went on without one
  status: "pending" | "answered" | "unanswered";
};

export type RunState = {
  status: "idle" | "planning" | "running" | "verifying" | "synthesizing" | "done" | "error" | "stopped";
  route?: { mode: string; method: string; confidence: number; specialists: RouteSpecialist[] };
  plan?: { method: string; note: string; subtasks: { id: string; specialist: string; instruction: string }[] };
  subtasks: Record<string, SubtaskState>;
  order: string[];
  tools: ToolState[];
  permissions: PermissionState[];
  text: string;
  reasoning: string;
  error?: string;
  elapsed?: number;
  trimmed?: number;
  skills?: string[];
  design?: { id: string; name: string };
  memory?: MemoryUse;
  privacy?: Record<string, number>; // provider name -> file passages withheld from it
  events?: ChatEvent[]; // the run as it happened, for the step-by-step view (each with `t`, seconds from the start)
  learn?: Learn;
  questions?: QuestionState[];
  contract?: { valid: boolean; attempts: number; errors: string[] }; // the answer had to be JSON for a schema
  verify?: VerifyState[];
  forge?: { report?: ForgeReport };
};

/** What the user's message taught SPIKE: notes saved at once ("recuerda que…"), or a rule proposed from a correction. */
export type Learn = {
  saved?: { id: string; kind: string; text: string; scope: string; existing?: boolean; undone?: boolean }[];
  correction?: { text: string; status: "proposed" | "saved" | "dismissed"; memory?: string; existing?: boolean };
};

export type BrowserSettings = { domains: Record<string, "allow" | "deny">; unknown: "ask" | "allow" };

export type ChatEvent = { type: string; [key: string]: any };

export type Settings = {
  custom_instructions: string;
  specialist_instructions: Record<string, string>;
  default_provider: string;
  specialist_bindings: Record<string, { provider_id?: string; model?: string }>;
  tool_policies: Record<string, "allow" | "ask" | "deny">;
  tools_enabled: boolean;
  use_planner: boolean;
  parallel: boolean;
  reasoning: boolean | null;
  temperature: number | null;
  max_tokens: number | null;
  local_runtime: {
    model: string;
    adapters: string[];
    context: number | null;
    threads: number | null;
    gpu_layers: number | null;
    kv_cache_type: string;
    port: number;
  };
  custom_specialists: unknown[];
  skill_mode: "auto" | "router" | "model" | "off";
  disabled_skills: string[];
  memory: { enabled: boolean; embeddings: "auto" | "off"; auto_summary: boolean; learn?: boolean };
  evolution?: { enabled: boolean; auto_router: boolean };
  finance?: { exchange: string; live: LiveSettings };
};

export type Checks = { include?: string[]; exclude?: string[] };

/** Something Evolution recorded: a correction, a route correction, a failure or an eval candidate. */
export type EvolutionItem = {
  id: string; kind: "correction" | "route" | "failure" | "candidate"; status: string; created: number; updated: number;
  [key: string]: any;
};

export type RouterSplit = { n: number; primary: number | null; exact: number | null };

export type EvolutionVersion = {
  id: number; component: string; created: number; active: boolean; reason: string; replaces: number | null;
  data: Record<string, any>; report: Record<string, any>;
};

export type EvolutionOverview = {
  settings: { enabled: boolean; auto_router: boolean };
  counts: Record<string, Record<string, number>>;
  router: { active: EvolutionVersion | null; pending: number; built_in: Record<string, RouterSplit>; current?: Record<string, RouterSplit> };
  versions: EvolutionVersion[];
};

export type CheckResult = {
  name: string; ok: boolean; detail: string; count?: number; passed?: number; total?: number;
  built_in?: Record<string, RouterSplit>; current?: Record<string, RouterSplit> | null;
  results?: { id: string; question: string; passed: boolean; problems: string[]; checked: boolean }[];
};

export type ToolInfo = { name: string; description: string; risk: string; default_policy: string; policy: string };

export type ConnectorInfo = {
  id: string;
  name: string;
  transport: "stdio" | "http";
  description: string;
  command: string;
  args: string[];
  url: string;
  preview: string;
  header_names: string[];
  secrets: { name: string; label?: string; url?: string; optional?: boolean }[];
  license: string;
  source: string;
  paid: boolean;
  requires: string;
  note: string;
  custom: boolean;
  enabled: boolean;
  policy: "allow" | "ask" | "deny";
  status: "stopped" | "starting" | "running" | "error";
  error: string | null;
  secrets_set: Record<string, boolean>;
  tools: { name: string; remote_name: string; description: string; policy: string; visibility?: string[]; view?: string }[];
  views?: string[]; // MCP Apps: the ui:// pages its tools show results in
};

export type SkillInfo = {
  name: string;
  description: string;
  source: "bundled" | "user";
  license: string;
  specialists: string[];
  keywords: string[];
  resources: string[];
  enabled: boolean;
};

/** What a chat answer recalled from memory (the "memory" event). */
export type MemoryUse = {
  rules: number;
  semantic: boolean;
  notes: { id: string; kind: string; source: string; preview: string; by: string[] }[];
};

export type MemoryItem = {
  id: string;
  scope: string;
  kind: "fact" | "decision" | "preference" | "rule" | "summary" | "document";
  text: string;
  source: string;
  created: number;
  updated: number;
  meta: Record<string, unknown>;
  match?: string;
  by?: string[];
};

export type MemoryStatus = {
  enabled: boolean;
  embeddings: "auto" | "off";
  auto_summary: boolean;
  stats: { memories: number; by_kind: Record<string, number>; chunks: number; embedded: number };
  semantic: { model: string | null; installed: boolean; running: boolean; error: string | null; install: string };
};

/** Monthly limits of one provider; prices per million tokens, in the user's own currency. */
export type Limits = { monthly_tokens?: number | null; monthly_cost?: number | null; price_in?: number | null; price_out?: number | null };

export type CallRow = {
  id: number;
  ts: number;
  provider_id: string;
  provider: string;
  model: string;
  local: boolean;
  status: "ok" | "error" | "blocked" | "cancelled";
  tokens_in: number;
  tokens_out: number;
  estimated: boolean;
  cost: number | null;
  files_sent: number;
  files_withheld: number;
  detail: string;
};

export type UsageRow = {
  provider_id: string;
  name: string;
  local: boolean;
  limits: Limits;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  estimated: number;
};
