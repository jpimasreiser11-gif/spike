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

export type Project = { id: string; name: string; instructions: string; mode: string; created: number; updated: number };

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
};

export type ToolState = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  specialist?: string;
  result?: string;
  ok?: boolean;
  file?: string; // workspace path of a file the tool wrote
};

export type PermissionState = {
  id: string;
  tool: string;
  risk: string;
  arguments: Record<string, unknown>;
  status: "pending" | "allow_once" | "allow_always" | "deny" | "sending";
};

export type RunState = {
  status: "idle" | "planning" | "running" | "synthesizing" | "done" | "error" | "stopped";
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
  memory?: MemoryUse;
  privacy?: Record<string, number>; // provider name -> file passages withheld from it
};

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
  memory: { enabled: boolean; embeddings: "auto" | "off"; auto_summary: boolean };
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
  tools: { name: string; remote_name: string; description: string; policy: string }[];
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
