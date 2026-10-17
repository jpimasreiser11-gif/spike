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
};

export type ToolInfo = { name: string; description: string; risk: string; default_policy: string; policy: string };
