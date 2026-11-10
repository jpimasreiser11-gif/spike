// G6 + G18 browser check of all main SPIKE views across light, OS-dark, explicit-dark, narrow mobile touch and reduced-motion.
// Evaluates SPIKE's own deterministic spike/dev/visual_checks.js plus SVG/focus/role/tab-order assertions in real Chromium:
// no SPIKE server, no model, no network.
// Usage (from web/ or repo root): node web/e2e/a11y.mjs [screenshotDir]
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = process.argv[2] || path.resolve(root, "e2e/screenshots");
fs.mkdirSync(out, { recursive: true });
const visualChecksSource = fs.readFileSync(path.resolve(root, "../spike/dev/visual_checks.js"), "utf-8");
const fail = (msg) => {
  console.error("FAIL:", msg);
  process.exitCode = 1;
};

const ENTRY = "/__g18_harness.tsx";
const HARNESS = `
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import { createRoot } from "react-dom/client";
import "/src/styles.css";
import { ArtifactContext, ArtifactPanel } from "/src/components/Artifact";
import { AssistantMessage } from "/src/components/AssistantMessage";
import { Composer } from "/src/components/Composer";
import { Creator } from "/src/components/Creator";
import { DesktopTask } from "/src/components/Desktop";
import { DeviceLab } from "/src/components/DeviceLab";
import { Forge } from "/src/components/Forge";
import { CommandPalette } from "/src/components/CommandPalette";
import { HistorySearch } from "/src/components/HistorySearch";
import { Tour } from "/src/components/Tour";
import { Lab } from "/src/components/Lab";
import { ProjectDialog, ProjectPanel } from "/src/components/Projects";
import { Prototypes } from "/src/components/Prototypes";
import { Replay } from "/src/components/Replay";
import { Research } from "/src/components/Research";
import { SettingsDialog } from "/src/components/SettingsDialog";
import { SetupWizard } from "/src/components/SetupWizard";
import { SubtitleStudio } from "/src/components/SubtitleStudio";
import { WorkflowBuilder } from "/src/components/WorkflowBuilder";
import { WorkspacePanel } from "/src/components/WorkspacePanel";

const params = new URLSearchParams(location.search);
const theme = params.get("theme");
const view = params.get("view") || "chat";
if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
if (view === "modals") {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
}

const PNG_1X1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
const SAMPLE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 80" width="240" height="80"><rect width="240" height="80" fill="#f3f6ef"/><text x="16" y="44" fill="#13261c" font-size="14">SPIKE Graph</text></svg>';

const SPECIALISTS = [
  { id: "core", name: "Spike Core", domain: "General", description: "General assistant", adapter: null, adapter_status: "none", sensitive: false, tools: ["read_file"], active_mode: "instruction_profile", layers: { base_instructions: true, user_instructions: false, learned_instructions: false, knowledge_count: 0 } },
  { id: "finance", name: "Spike Finance", domain: "Finance", description: "Financial analysis", adapter: "spike-finance-v1.gguf", adapter_status: "planned", sensitive: true, tools: ["read_file"], active_mode: "instruction_profile", layers: { base_instructions: true, user_instructions: true, learned_instructions: true, knowledge_count: 2 } },
  { id: "medicine", name: "Spike Medicine", domain: "Medicine", description: "Clinical reference", adapter: "spike-medicine-v1.gguf", adapter_status: "evaluated", adapter_accepted: true, adapter_file_present: true, adapter_file_check: "verified", sensitive: true, tools: ["read_file"], active_mode: "adapter_loaded", active_provider: "spike-local", loaded_on_providers: ["spike-local"], provider_supports_adapters: true, layers: { base_instructions: true, user_instructions: false, learned_instructions: false, knowledge_count: 1 } },
  { id: "code", name: "Spike Code", domain: "Software", description: "Code & debugging", adapter: "spike-code-v1.gguf", adapter_status: "trained", sensitive: false, tools: ["read_file"], active_mode: "instruction_profile", layers: { base_instructions: true, user_instructions: false, learned_instructions: false, knowledge_count: 0 } },
  { id: "data", name: "Spike Data", domain: "Analytics", description: "SQL & charts", adapter: null, adapter_status: "planned", sensitive: false, tools: ["read_file"], active_mode: "instruction_profile", layers: { base_instructions: true, user_instructions: false, learned_instructions: false, knowledge_count: 0 } },
];

const PROVIDERS = [
  { id: "spike-local", name: "Spike Local", kind: "llama.cpp", base_url: "http://127.0.0.1:8080/v1", model: "Qwen3.5-4B-Q4_K_M.gguf", local: true, paid: false, allow_paid: false, has_key: false, share_files: false, capabilities: { vision: false }, capabilities_effective: { vision: false } },
  { id: "cloud-pro", name: "Cloud Pro", kind: "openai", base_url: "https://api.example.test/v1", model: "pro-1", local: false, paid: true, allow_paid: false, has_key: true, share_files: false, limits: { monthly_tokens: 500000, monthly_cost: 20, price_in: 1.5, price_out: 6.0 }, capabilities: {}, capabilities_effective: { vision: false } },
];

const DESIGNS = [
  {
    id: "editorial",
    name: "Editorial",
    category: "Editorial",
    description: "Warm paper & crisp contrast",
    source: "bundled",
    has_tokens: true,
    colors: [
      { name: "bg", value: "#fdfdfa" },
      { name: "accent", value: "#2a7b20" },
    ],
  },
];

const PROJECTS = [
  { id: "p-1", name: "Q1 Margin Audit", description: "Quarterly revenue & margin dataset", instructions: "Cite SQL queries.", mode: "finance", specialist: "finance", design: "editorial", created: 1730000000, updated: 1730000000, created_at: 1730000000, updated_at: 1730000000, file_count: 2 },
];

const WORKFLOW_DOC = {
  id: "wf-1",
  format: "spike-workflow",
  version: 1,
  revision: 2,
  name: "Margin Audit Flow",
  nodes: [
    { id: "n1", type: "input", name: "topic", label: "Topic", x: 30, y: 40, kind: "text", default: "Q1 margins" },
    { id: "n2", type: "specialist", name: "analyst", label: "Analyst", x: 250, y: 40, specialist: "finance", prompt: "Analyze {{topic}}" },
    { id: "n3", type: "condition", name: "check_ok", label: "Has margin", x: 470, y: 40, op: "contains", value: "margin" },
    { id: "n4", type: "output", name: "report_out", label: "Report", x: 690, y: 40, mode: "artifact", title: "Audit", format: "markdown", content: "{{analyst}}" },
  ],
  edges: [
    { id: "e1", from: "n1", fromPort: "out", to: "n2", toPort: "in" },
    { id: "e2", from: "n2", fromPort: "out", to: "n3", toPort: "in" },
    { id: "e3", from: "n3", fromPort: "true", to: "n4", toPort: "in" },
  ],
};

const WORKFLOW_RUN = {
  id: "run-1",
  workflow_id: "wf-1",
  status: "completed",
  live: false,
  started: 1730000000,
  elapsed_s: 1.8,
  nodes: {
    n1: { status: "ok", elapsed_s: 0.1, output: "Q1 margins", log: [{ kind: "output", text: "Q1 margins" }] },
    n2: { status: "ok", elapsed_s: 1.2, output: "Net margin is 24.5%", log: [{ kind: "text", text: "Net margin is 24.5%" }] },
    n3: { status: "running", elapsed_s: 0.2, branch: "true", log: [] },
    n4: { status: "cancelled", elapsed_s: 0.1, log: [] },
  },
};

const jsonResp = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(typeof data === "string" ? data : JSON.stringify(data), {
    status,
    headers: { "Content-Type": typeof data === "string" ? "text/plain; charset=utf-8" : "application/json", ...headers },
  });

window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  const u = new URL(rawUrl, location.origin);
  const p = u.pathname;
  const method = (init?.method || "GET").toUpperCase();

  if (p === "/api/setup") {
    return jsonResp({
      enabled: view === "setup",
      complete: false,
      can_download: true,
      disk_free: 50 * 1024 ** 3,
      ram_total: 16 * 1024 ** 3,
      ram_available: 12 * 1024 ** 3,
      required_disk: 4 * 1024 ** 3,
      required_ram: 8 * 1024 ** 3,
      specialists: [
        { id: "medicine", name: "Spike Medicine", available: true },
        { id: "finance", name: "Spike Finance", available: false },
      ],
      job: { status: "idle", file: "", done: 0, total: 0 },
    });
  }
  if (p === "/api/settings") {
    return jsonResp({
      default_provider: "spike-local",
      custom_instructions: "Cite exact rows and files.",
      use_planner: true,
      parallel: false,
      tools_enabled: true,
      temperature: null,
      max_tokens: null,
      reasoning: null,
      sandbox: "auto",
      trust: { enabled: true, escalate: true, escalate_unchecked: 1, model_pass: false },
      specialist_bindings: {},
      specialist_instructions: { finance: "Use IFRS terminology." },
      tool_policies: { read_file: "allow", run_command: "ask" },
      skill_policies: {},
      skill_mode: "auto",
      disabled_skills: [],
      custom_specialists: [],
      memory: { enabled: true, embeddings: "auto", auto_summary: true, learn: true },
      evolution: { enabled: true, auto_router: false, training_data: true, auto_strategy: true, personal_adapter: true },
      desktop: { enabled: true, provider_id: "spike-local", max_steps: 20, tool: "auto" },
      local_runtime: { model: "", adapters: [], context: 8192, threads: 6, gpu_layers: -1, kv_cache_type: "q8_0", port: 8740 },
      onboarding: { tour_seen: false },
    });
  }
  if (p === "/api/specialists") return jsonResp(SPECIALISTS);
  if (p === "/api/specialists/runtime-status") {
    return jsonResp([
      {
        id: "medicine",
        catalog_status: "evaluated",
        approved: true,
        active_mode: "adapter_loaded",
        provider_id: "spike-local",
        provider_name: "Spike Local",
        model: "Qwen3.5-4B-Q4_K_M.gguf",
        adapter: "spike-medicine-v1.gguf",
        evaluation: { domain_delta: 35.07, general_delta: -0.62 },
        layers: { base_instructions: true, user_instructions: false, learned_instructions: false, knowledge_pack: true },
      },
      {
        id: "finance",
        catalog_status: "planned",
        approved: false,
        active_mode: "prompt_profile",
        provider_id: "spike-local",
        provider_name: "Spike Local",
        model: "Qwen3.5-4B-Q4_K_M.gguf",
        adapter: null,
        evaluation: null,
        layers: { base_instructions: true, user_instructions: true, learned_instructions: true, knowledge_pack: true },
      },
    ]);
  }
  if (p === "/api/presets") {
    return jsonResp([
      { id: "ollama", name: "Ollama (local)", kind: "openai", base_url: "http://127.0.0.1:11434/v1", example_model: "qwen3:4b", local: true, paid: false, needs_key: false },
      { id: "openai", name: "OpenAI", kind: "openai", base_url: "https://api.openai.com/v1", example_model: "gpt-4.1-mini", local: false, paid: true, needs_key: true, key_url: "https://platform.openai.com" },
    ]);
  }
  if (p === "/api/tools") {
    return jsonResp([
      { name: "read_file", description: "Read a file inside the workspace", risk: "read", default_policy: "allow" },
      { name: "run_command", description: "Execute a shell command", risk: "execute", default_policy: "ask" },
      { name: "web_search", description: "Query external search provider", risk: "network", default_policy: "ask" },
    ]);
  }
  if (p === "/api/sandbox") {
    return jsonResp({ available: true, backend: "sandbox-exec", mode: "auto", isolated_tools: ["python", "data_python"] });
  }
  if (p === "/api/skills" || p === "/api/forge/skills") {
    return jsonResp([
      { name: "dashboard-creator", description: "Build verified HTML dashboards", source: "bundled", scope: "builtin", enabled: true, specialists: ["data", "code"], keywords: ["dashboard", "html"], tools: ["write_file"], verify: ["check_html"] },
      { name: "sql-auditor", description: "Audit DuckDB SQL queries", source: "user", scope: "user", enabled: true, specialists: ["data", "finance"], keywords: ["sql", "duckdb"], tools: ["query_data"], verify: [] },
    ]);
  }
  if (p === "/api/designs" || p === "/api/design-systems") return jsonResp(DESIGNS);
  if ((p.startsWith("/api/designs/") || p.startsWith("/api/design-systems/")) && p.endsWith("/preview")) {
    return jsonResp({ html: "<!doctype html><html><body><h1>Editorial Preview</h1></body></html>" });
  }
  if (p === "/api/reverse") {
    return jsonResp({
      browser: true,
      providers: [{ id: "spike-local", name: "Spike Local", local: true, vision: false, receives_files: false }],
      default_provider: "spike-local",
      statement: "I own this reference.",
    });
  }
  if (p === "/api/finance") {
    return jsonResp({
      settings: { exchange: "binance", live: { enabled: true, exchange: "binance", sandbox: true, no_withdrawal: true, max_order: 500, max_day: 1000, symbols: ["BTC/USDT"] } },
      exchanges: ["binance", "kraken"],
      strategies: {},
      live: { enabled: true, exchange: "binance", sandbox: true, no_withdrawal: true, max_order: 500, max_day: 1000, symbols: ["BTC/USDT"], has_key: true, spent_today: 120, withdrawals: "no", problems: [], problem_codes: [], testnets: ["binance"] },
      live_orders: [
        { id: "ord-1", created: 1730000000, exchange: "binance", sandbox: true, symbol: "BTC/USDT", side: "buy", type: "limit", amount: 0.05, price: 60000, est_price: 60000, notional: 3000, status: "placed", decided: 1730000010, result: "Filled on sandbox" },
      ],
    });
  }
  if (p === "/api/finance/paper") {
    return jsonResp({
      valuation: { quote: "USDT", positions: [{ asset: "BTC", quantity: 0.05, price: 62000, value: 3100 }], total: 10100, start_cash: 10000, pnl: 100, pnl_pct: 1.0, unpriced: [] },
      balances: { USDT: 7000, BTC: 0.05 },
      start: { cash: 10000, quote: "USDT", time: 1730000000 },
      orders: [{ id: "po-1", created: 1730000000, exchange: "binance", symbol: "BTC/USDT", side: "buy", type: "market", amount: 0.05, limit_price: null, status: "filled", fill_price: 60000, fee: 3, note: "" }],
      price_error: null,
    });
  }
  if (p === "/api/finance/live/orders/ord-1") {
    return jsonResp({ id: "ord-1", created: 1730000000, exchange: "binance", sandbox: true, symbol: "BTC/USDT", side: "buy", type: "limit", amount: 0.05, price: 60000, est_price: 60000, notional: 3000, status: "placed", decided: 1730000010, result: "Filled on sandbox" });
  }
  if (p === "/api/connectors") {
    return jsonResp([
      {
        id: "notes-mcp",
        name: "Local Notes MCP",
        transport: "stdio",
        description: "Local markdown notes",
        command: "python3",
        args: ["-m", "notes_mcp"],
        url: "",
        preview: "python3 -m notes_mcp",
        header_names: [],
        secrets: [],
        license: "MIT",
        source: "bundled",
        paid: false,
        requires: "python3",
        note: "",
        custom: false,
        enabled: true,
        policy: "allow",
        status: "running",
        error: null,
        secrets_set: {},
        tools: [{ name: "mcp__notes__search", remote_name: "search", description: "Search markdown notes", policy: "allow" }],
      },
    ]);
  }
  if (p === "/api/connectors/catalog") {
    return jsonResp([
      { id: "filesystem", name: "Filesystem MCP", description: "Local folder access", transport: "stdio", command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"], env: [] },
    ]);
  }
  if (p === "/api/browser" || p === "/api/browser/domains") {
    return jsonResp({ domains: { "docs.python.org": "allow", "ads.example.test": "deny" }, unknown: "ask", allow: ["docs.python.org"], block: ["ads.example.test"] });
  }
  if (p === "/api/browser/recorder") {
    return jsonResp({
      running: true,
      recording: { recording: false, name: "", steps: [], ignored: {}, truncated: false },
      scripts: [{ id: "docs-check", name: "Docs check", steps: 2 }],
      replay: { state: "idle", reason: "", mode: "auto", script: null, index: 0, total: 0, steps: [], question: null },
    });
  }
  if (p === "/api/memory" || p === "/api/memories") {
    return jsonResp([
      { id: "m-1", kind: "rule", text: "Always pass encoding='utf-8' when reading or writing files.", scope: "global", source: "user", created: 1730000000, updated: 1730000000, created_at: 1730000000, updated_at: 1730000000, meta: {} },
      { id: "m-2", kind: "fact", text: "Q1 revenue grew 18% year over year.", scope: "project:p-1", source: "chat", created: 1730000000, updated: 1730000000, created_at: 1730000000, updated_at: 1730000000, meta: {} },
    ]);
  }
  if (p === "/api/memory-status") {
    return jsonResp({
      enabled: true,
      embeddings: "auto",
      auto_summary: true,
      stats: { memories: 2, by_kind: { rule: 1, fact: 1 }, chunks: 48, embedded: 48 },
      semantic: { model: "bge-small", installed: true, running: true, error: null, install: "" },
    });
  }
  if (p === "/api/memory-folders") {
    return jsonResp({
      defaults: { include: ["*.md"], exclude: ["node_modules"], max_file_bytes: 2097152, max_files: 500 },
      folders: [
        {
          id: "fld-1",
          path: "/Users/ana/notes",
          scope: "global",
          include: ["*.md"],
          exclude: ["node_modules"],
          max_file_bytes: 2097152,
          max_files: 500,
          added: 1730000000,
          files: 12,
          chunks: 48,
          indexed: 1730000000,
          skipped: { binary: 1 },
          job: { state: "done", total: 12, done: 12, indexed: 12, unchanged: 0, removed: 0, embedded: 12, skipped: {}, current: "", started: 1730000000, finished: 1730000002, error: "", warning: "", force: false },
        },
      ],
    });
  }
  if (p.startsWith("/api/memory-folders/") && p.endsWith("/files")) {
    return jsonResp([{ path: "notes.md", size: 480, status: "indexed", mtime_ns: 1730000000 }]);
  }
  if (p === "/api/glossary") {
    return jsonResp([{ id: "g-1", term: "EBITDA", translation: "Beneficio antes de intereses, impuestos, depreciaciones y amortizaciones", lang: "es", note: "Finanzas", scope: "global", created: 1730000000, updated: 1730000000, updated_at: 1730000000 }]);
  }
  if (p === "/api/tutor") {
    return jsonResp({
      now: 1730000000,
      due: 1,
      topics: [
        { id: "t-1", name: "DuckDB Window Functions", notes: "PARTITION BY & ORDER BY", scope: "global", mastery: 3, ease: 2.5, interval_days: 4, reviews: 5, lapses: 0, last_quality: 4, last_review: 1729600000, next_review: 1729990000, due: true, overdue_days: 1, created: 1729000000 },
      ],
    });
  }
  if (p === "/api/memory-graph") {
    return jsonResp({
      focus: null,
      stats: { entities: 2, relations: 1, proposed: 1 },
      nodes: [
        { id: "e:spike", label: "SPIKE", type: "entity", kind: "name", weight: 3 },
        { id: "n:m-1", label: "Always pass encoding='utf-8'", type: "note", kind: "rule", weight: 1 },
      ],
      edges: [{ id: "e-1", source: "e:spike", target: "n:m-1", type: "mentions", label: "mentions", status: "confirmed", weight: 1 }],
    });
  }
  if (p === "/api/memory-graph/relations") {
    return jsonResp([
      { id: "r-1", source: "e:spike", target: "e:duckdb", from: "SPIKE", label: "uses", to: "DuckDB", status: "confirmed", origin: "user", scope: "global", memory: "m-1" },
      { id: "r-2", source: "e:spike", target: "e:apple", from: "SPIKE", label: "runs on", to: "Apple Silicon", status: "proposed", origin: "chat", scope: "global", memory: "m-2" },
    ]);
  }
  if (p === "/api/memory-graph/svg") {
    return new Response(SAMPLE_SVG, { headers: { "Content-Type": "image/svg+xml" } });
  }
  if (p === "/api/evolution") {
    return jsonResp({
      settings: { enabled: true, auto_router: false },
      counts: { route: { proposed: 1 }, correction: { proposed: 1 }, failure: { open: 1 }, candidate: { proposed: 0 } },
      router: {
        active: { id: 2, component: "router", created: 1730000000, active: true, reason: "learned", replaces: 1, data: { overlay: { finance: { ebitda: 1.2 } } }, report: {} },
        pending: 1,
        built_in: { train: { n: 20, primary: 0.9, exact: 0.85 }, test: { n: 10, primary: 0.9, exact: 0.8 } },
        current: { train: { n: 20, primary: 0.95, exact: 0.9 }, test: { n: 10, primary: 0.95, exact: 0.9 } },
      },
      versions: [{ id: 2, component: "router", created: 1730000000, active: true, reason: "learned", replaces: 1, data: {}, report: {} }],
    });
  }
  if (p === "/api/evolution/items") {
    return jsonResp([
      { id: "ev-1", kind: "route", status: "proposed", question: "Compute Sharpe ratio", chosen: "finance", first: "math", created: 1730000000, updated: 1730000000 },
      { id: "ev-2", kind: "correction", status: "proposed", specialist: "code", question: "Read UTF-8 file", wrong: "p.read_text()", rule: "Always pass encoding='utf-8'", created: 1730000000, updated: 1730000000 },
      { id: "f-1", kind: "failure", status: "open", specialist: "data", error: "Column margin not found", question: "Join Q1 sales", created: 1730000000, updated: 1730000000 },
    ]);
  }
  if (p === "/api/evolution/prompts") {
    return jsonResp([
      {
        specialist: "finance",
        name: "Spike Finance",
        questions: 4,
        ideas: ["Cite exact rows"],
        skills: ["dashboard-creator"],
        versions: [],
        active: { id: 1, component: "prompt:finance", created: 1730000000, active: true, reason: "learned", replaces: null, data: { instructions: ["Show formulas"] }, report: {} },
        candidate: {
          id: 2,
          component: "prompt:finance",
          created: 1730000010,
          active: false,
          reason: "proposed",
          replaces: 1,
          data: { instructions: ["Show formulas", "Cite exact rows"] },
          report: {
            status: "ok",
            changes: ["Cite exact rows"],
            regression: { evaluated: true, ok: true, questions: 4, drop_points: 0, tolerance_points: 2, baseline: { passed: 3, total: 4 }, candidate: { passed: 4, total: 4 } },
          },
        },
      },
    ]);
  }
  if (p === "/api/evolution/strategy") {
    return jsonResp({
      uses: 12,
      min_samples: 5,
      margin: 0.05,
      active: { id: 1, component: "strategy", created: 1730000000, active: true, reason: "learned", replaces: null, data: {}, report: {} },
      versions: [],
      rows: [{ kind: "skill", name: "dashboard-creator", task_type: "data:chart", n: 6, good: 6, retried: 0, undone: 0, corrected: 0, rate: 1.0, enough: true }],
    });
  }
  if (p === "/api/evolution/personal") {
    return jsonResp({
      enabled: true,
      training_data: true,
      available: true,
      reason: "",
      command: "python -m training.personal_adapter",
      active: null,
      versions: [],
      counts: { used: 5, needed: 20, corrections: 3, chat_answers: 2, excluded: 0, duplicates: 0, approved_corrections: 3, corrections_need_consent: false },
      chats: { marked: 1, missing: 0, answers_not_used: { origin: 0, corrected: 0 } },
      marked: [{ id: "mk-1", conversation: "c-1", title: "Quarterly margin review" }],
      entries: [{ id: "pe-1", source: "correction", conversation: "c-1", question: "Format SQL", answer: "SELECT * FROM sales;", excluded: false, duplicate: false }],
    });
  }
  if (p === "/api/conversations") {
    return jsonResp([{ id: "c-1", title: "Quarterly margin review", mode: "finance", created: 1730000000, updated: 1730000000 }, { id: "c-2", title: "DuckDB schema audit", mode: "data", created: 1730000100, updated: 1730000100 }]);
  }
  if (p === "/api/conversations/search") {
    return jsonResp({
      total: 1,
      hits: [
        {
          conversation_id: "c-1",
          message_id: "msg-1",
          title: "Quarterly margin review",
          role: "assistant",
          specialist: "finance",
          project_id: "p-1",
          project_name: "Q1 Margin Audit",
          created_at: 1730000000,
          excerpt: "The verified Q1 [[HIGHLIGHT]]margin[[/HIGHLIGHT]] reached 24.5%.",
          highlights: ["margin"],
        },
      ],
    });
  }
  if (p === "/api/history/search") {
    return jsonResp({
      has_more: false,
      next_offset: null,
      results: [
        {
          id: 1,
          conversation_id: "c-1",
          message_id: "msg-1",
          title: "Quarterly margin review",
          project_id: "p-1",
          project_name: "Q1 Margin Audit",
          role: "assistant",
          created: 1730000000,
          segments: [
            { text: "The verified Q1 ", matched: false },
            { text: "margin", matched: true },
            { text: " reached 24.5%.", matched: false },
          ],
        },
      ],
    });
  }
  if (p === "/api/usage") {
    return jsonResp([
      { provider_id: "spike-local", name: "Spike Local", local: true, limits: {}, calls: 2, tokens_in: 420, tokens_out: 180, cost: 0, estimated: 0 },
      { provider_id: "cloud-pro", name: "Cloud Pro", local: false, limits: { monthly_tokens: 500000, monthly_cost: 20, price_in: 1.5, price_out: 6.0 }, calls: 1, tokens_in: 200, tokens_out: 100, cost: 0.01, estimated: 0 },
    ]);
  }
  if (p === "/api/calls") {
    return jsonResp([
      { id: 1, ts: 1730000000, provider_id: "cloud-pro", provider: "Cloud Pro", model: "pro-1", local: false, status: "ok", tokens_in: 200, tokens_out: 100, estimated: false, cost: 0.01, files_sent: 0, files_withheld: 1, detail: "" },
    ]);
  }
  if (p === "/api/privacy") {
    return jsonResp({
      total_calls: 2,
      local_calls: 2,
      external_calls: 0,
      blocked_calls: 0,
      total_tokens_in: 420,
      total_tokens_out: 180,
      total_cost: 0,
      by_provider: [{ provider_id: "spike-local", name: "Spike Local", local: true, calls: 2, blocked: 0, tokens_in: 420, tokens_out: 180, cost: 0, limits: {} }],
      recent: [{ id: 1, ts: 1730000000, provider_id: "spike-local", provider_name: "Spike Local", model: "Qwen3.5-4B", local: true, specialist: "finance", tokens_in: 210, tokens_out: 90, estimated: false, cost: 0, files_shared: 0, files_withheld: 0, status: "ok" }],
    });
  }
  if (p === "/api/jobs") {
    return jsonResp({
      limit: 2,
      ram_floor: 6 * 1024 ** 3,
      jobs: [{ id: "job-1", kind: "indexing", status: "running" }],
    });
  }
  if (p === "/api/creator/data-files") {
    return jsonResp([{ path: "margins.csv", bytes: 1240 }]);
  }
  if (p === "/api/desktop") {
    return jsonResp({
      settings: { enabled: true, provider_id: "spike-local", max_steps: 20, tool: "auto" },
      driver: { available: true, backend: "quartz", reason: "", code: "", needs: "", supports: ["click", "type", "screenshot"], notes: [] },
      providers: [{ id: "spike-local", name: "Spike Local", model: "Qwen3.5-4B", ok: true, code: "", reason: "" }],
      hard_max_steps: 50,
      running: false,
      task: null,
    });
  }
  if (p === "/api/desktop/estimate") {
    return jsonResp({
      calls: 5,
      provider: "Spike Local",
      model: "Qwen3.5-4B",
      tokens_in: 1200,
      tokens_out: 300,
      cost: 0,
    });
  }
  if (p === "/api/system") {
    return jsonResp({
      hardware: { cpu_model: "Apple M2", physical_cores: 8, total_ram_gb: 16, os: "macOS", arch: "arm64", apple_silicon: true },
      recommendation: { quant: "Q4_K_M", context: 8192, kv_cache_type: "q8_0", threads: 6, notes: ["Metal unified memory ready"] },
      runtime: { running: true, rss_mb: 2450, load_seconds: 1.4, adapters: ["spike-medicine-v1.gguf"] },
      secrets_backend: "Keychain",
    });
  }
  if (p === "/api/tune") {
    return jsonResp({ date_utc: "2026-11-05T10:00:00Z", best: { threads: 6, kv_cache_type: "q8_0", context: 8192 } });
  }
  if (p === "/api/projects") return jsonResp(PROJECTS);
  if (p === "/api/project-branches") return jsonResp([{ id: "p-1", parent: "p-0" }]);
  if (p === "/api/projects/p-1/compare") {
    return jsonResp({
      token: "tok-1",
      parent: "p-0",
      files: [{ path: "notes.md", diff: "+Verified Q1 margin 24.5%", conflict: false, deleted: false, before: "Draft", after: "Verified", before_size: 5, after_size: 32 }],
    });
  }
  if (p === "/api/projects/p-1/files" || p === "/api/workspace/files") {
    return jsonResp([
      { path: "margins.csv", size: 1240, updated_at: 1730000000 },
      { path: "summary.md", size: 480, updated_at: 1730000000 },
    ]);
  }
  if (p.startsWith("/api/projects/p-1/files/") || p.startsWith("/api/workspace/files/")) {
    return new Response("# Verified Summary\\nNet margin: 24.5%\\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
  if (p === "/api/workspace/jobs") {
    return jsonResp([
      { id: "job-1", name: "Nightly CSV Audit", prompt: "Verify margins.csv", specialist: "finance", enabled: true, interval_minutes: 60, last_run: 1730000000, last_status: "ok" },
    ]);
  }
  if (p === "/api/forge/prototypes") {
    return jsonResp({
      git: true,
      runs: [
        {
          id: "proto-1",
          task: "Implement CSV BOM parser",
          status: "built",
          dirty: 0,
          base: { branch: "main", commit: "12345678" },
          tests: { files: ["tests/test_csv.py"], checks: [] },
          merged: null,
          comparison: {
            leader: "a",
            basis: "tests",
            rows: [
              { label: "a", built: true, tests_passed: 6, tests_total: 6, tests_ran: true, checks_passed: 2, checks_total: 2, files_changed: 2, insertions: 42, deletions: 4, seconds: 4.2 },
              { label: "b", built: true, tests_passed: 5, tests_total: 6, tests_ran: true, checks_passed: 1, checks_total: 2, files_changed: 2, insertions: 58, deletions: 6, seconds: 5.1 },
            ],
          },
          approaches: [
            {
              label: "a",
              goal: "Streaming reader",
              branch: "spike/proto-1-a",
              start: "12345678",
              blueprint: SAMPLE_BLUEPRINT,
              status: "built",
              seconds: { build: 3.0, tests: 1.2, total: 4.2 },
              files: { count: 2, insertions: 42, deletions: 4, paths: ["spike/csv_reader.py", "tests/test_csv.py"] },
              tests: { ran: true, reason: "", passed: 6, failed: [], total: 6 },
              checks: { passed: 2, total: 2, items: [{ name: "UTF-8 BOM", kind: "check", ok: true, note: "" }, { name: "Empty cells", kind: "check", ok: true, note: "" }] },
            },
            {
              label: "b",
              goal: "In-memory buffer",
              branch: "spike/proto-1-b",
              start: "12345678",
              blueprint: SAMPLE_BLUEPRINT,
              status: "built",
              seconds: { build: 3.8, tests: 1.3, total: 5.1 },
              files: { count: 2, insertions: 58, deletions: 6, paths: ["spike/csv_buffer.py", "tests/test_csv.py"] },
              tests: { ran: true, reason: "", passed: 5, failed: ["tests/test_csv.py::test_large_file"], total: 6 },
              checks: { passed: 1, total: 2, items: [{ name: "UTF-8 BOM", kind: "check", ok: true, note: "" }, { name: "Empty cells", kind: "check", ok: false, note: "Failed on trailing delimiter" }] },
            },
          ],
        },
      ],
    });
  }
  if (p === "/api/creator/templates") {
    return jsonResp([
      {
        id: "dashboard",
        name: "Verified Dashboard",
        description: "Interactive HTML report from local data",
        icon: "chart",
        fields: [
          { id: "title", label: "Dashboard title", kind: "text", default: "", placeholder: "Q1 Margin Overview", required: true },
          { id: "goal", label: "Key question", kind: "textarea", default: "", placeholder: "Compare Q1 vs Q4 margins", required: true },
          { id: "file", label: "Data file", kind: "file", default: "margins.csv", placeholder: "margins.csv", required: false },
        ],
        skills: ["dashboard-creator"],
        design: true,
        deliverables: ["dashboard.html"],
      },
      {
        id: "brief",
        name: "Executive Brief",
        description: "One-page cited summary",
        icon: "doc",
        fields: [{ id: "topic", label: "Topic", kind: "text", default: "", placeholder: "Unit economics", required: true }],
        skills: [],
        design: false,
        deliverables: ["brief.md"],
      },
    ]);
  }
  if (p === "/api/workflows/catalog") {
    return jsonResp({
      specialists: SPECIALISTS.map((s) => ({ id: s.id, name: s.name })),
      tools: [{ name: "query_data", description: "Run read-only SQL", risk: "read", policy: "allow", parameters: { properties: { sql: { type: "string", description: "SQL query" } }, required: ["sql"] } }],
      tools_enabled: true,
    });
  }
  if (p === "/api/workflows") {
    return jsonResp([{ id: "wf-1", name: "Margin Audit Flow", revision: 2 }]);
  }
  if (p === "/api/workflows/wf-1") return jsonResp(WORKFLOW_DOC);
  if (p === "/api/workflows/wf-1/runs") {
    return jsonResp([{ id: "run-1", status: "completed", started: 1730000000, elapsed_s: 1.8 }]);
  }
  if (p === "/api/workflows/wf-1/runs/run-1") return jsonResp(WORKFLOW_RUN);
  if (p === "/api/lab/runs") {
    return jsonResp([
      {
        id: "lab-1",
        created: 1730000000,
        kind: "compare",
        rows: [
          { specialist: "finance", provider_id: "spike-local", model: "Qwen3.5-4B", adapter: null, status: "ok", output: "Margin = 24.5%", latency_ms: 420, tokens_in: 85, tokens_out: 32, cost: 0, score: 1.0, case: 1, prompt: "Compute Q1 margin" },
        ],
      },
    ]);
  }
  if (p === "/api/lab/preview") {
    return jsonResp({
      id: "q-1",
      calls: 1,
      estimated_cost: 0,
      blocked: false,
      targets: [{ specialist: "finance", provider_id: "spike-local", model: "Qwen3.5-4B", adapter: null }],
    });
  }
  if (p === "/api/research/preview") {
    return jsonResp({
      id: "rp-1",
      sources: [{ id: "s-1", path: "summary.md", sha256: "e3b0c44298fc1c149afbf4c8996fb924", pages: ["Net margin in Q1 reached 24.5% across all regions."] }],
      calls: 1,
      blocked: null,
      estimated_cost: 0,
      provider: { id: "spike-local", name: "Spike Local", model: "Qwen3.5-4B", local: true },
    });
  }
  if (p === "/api/research/analyze") {
    return jsonResp({
      kind: "contradictions",
      sources: [{ id: "s-1", path: "summary.md", sha256: "e3b0c44298fc1c149afbf4c8996fb924", pages: ["Net margin 24.5%"] }],
      analysis: {
        status: "ok",
        pairs: [
          {
            left: { source_id: "s-1", path: "summary.md", page: 1, start: 0, end: 24, quote: "Net margin in Q1 was 24.5%", claim: "Margin 24.5%", sha256: "aaa111" },
            right: { source_id: "s-2", path: "draft.md", page: 1, start: 0, end: 24, quote: "Net margin in Q1 was 21.0%", claim: "Margin 21.0%", sha256: "bbb222" },
            reason: "Different Q1 net margin percentage reported",
          },
        ],
      },
    });
  }
  if (p === "/api/device-lab") {
    return jsonResp({
      profiles: [
        { id: "desktop", name: "Desktop", width: 1360, height: 860 },
        { id: "mobile", name: "Mobile", width: 375, height: 760 },
      ],
      limits: { custom: 6 },
      browser: true,
      adb: true,
    });
  }
  if (p === "/api/device-lab/android") {
    return jsonResp({
      found: true,
      devices: [{ serial: "emulator-5554", state: "device", model: "Pixel_7", kind: "usb", usable: true }],
      error: "",
    });
  }
  if (p === "/api/device-lab/run") {
    return jsonResp({
      kind: "device_lab",
      url: "http://localhost:5173/",
      browser: "Chromium",
      started: "2026-11-05T10:00:00Z",
      summary: { profiles: 2, pass: 1, fail: 1, error: 0 },
      profiles: [
        {
          id: "desktop",
          name: "Desktop",
          builtin: true,
          status: "pass",
          reason: "",
          reasons: [],
          viewport: { width: 1360, height: 860 },
          scale: 1,
          touch: false,
          mobile: false,
          http_status: 200,
          seconds: 0.4,
          screenshot: PNG_1X1,
          notes: [],
          overflow: { total: 0, px: 0, items: [] },
          tap_targets: { total: 0, items: [] },
          small_text: { total: 0, items: [] },
          console_errors: { total: 0, items: [] },
          failed_requests: { total: 0, items: [] },
          blocked_requests: { total: 0, items: [] },
        },
        {
          id: "mobile",
          name: "Mobile",
          builtin: true,
          status: "fail",
          reason: "overflow",
          reasons: ["overflow"],
          viewport: { width: 375, height: 760 },
          scale: 2,
          touch: true,
          mobile: true,
          http_status: 200,
          seconds: 0.5,
          screenshot: PNG_1X1,
          notes: [],
          overflow: { total: 1, px: 18, items: [{ selector: ".wide-table", kind: "box", right: 393, width: 393 }] },
          tap_targets: { total: 0, items: [] },
          small_text: { total: 0, items: [] },
          console_errors: { total: 0, items: [] },
          failed_requests: { total: 0, items: [] },
          blocked_requests: { total: 0, items: [] },
        },
      ],
    });
  }
  if (p === "/api/subtitles") {
    return jsonResp({ enabled: true, whisper: true, ffmpeg: true, ffprobe: true, max_seconds: 600 });
  }
  if (p === "/api/subtitles/transcribe" || p === "/api/subtitles/import" || p === "/api/subtitles/edit") {
    return jsonResp({
      cues: [
        { start_ms: 0, end_ms: 2400, text: "SPIKE runs locally on your computer." },
        { start_ms: 2500, end_ms: 5200, text: "Every specialist and tool is auditable." },
      ],
    });
  }
  if (p === "/api/artifact-versions") return jsonResp({ id: "av-1" });
  if (p === "/api/artifact-versions/av-1/comments") {
    return jsonResp([{ id: "cm-1", line: 1, text: "Verify header contrast in dark mode.", parent: null }]);
  }
  if (p === "/api/media") {
    return jsonResp({ enabled: true, whisper: true, piper: true, whisper_model: "ggml-base.bin", piper_model: "es_ES-davefx-medium.onnx", piper_license: "MIT", license: "MIT License" });
  }
  if (p === "/api/minds/estimate") {
    return jsonResp({ n: 3, multiplier: 3, multi_step: false, cost: 0, unpriced: [], blocked: null, providers: [{ provider_id: "spike-local", name: "Spike Local", calls: 3 }] });
  }
  if (method !== "GET") return jsonResp({ ok: true });
  return jsonResp({});
};

const SAMPLE_BLUEPRINT = {
  goal: "Audit Q1 margin CSV and generate verified dashboard",
  requirements: ["Read margins.csv with UTF-8", "Compute gross and net margin by region"],
  criteria: ["All SQL numbers match margins.csv", "Dark and light themes meet 4.5:1 contrast"],
  steps: [
    {
      id: "s1",
      specialist: "data",
      role: "research",
      instruction: "Query margins.csv with DuckDB and verify schema",
      depends_on: [],
      deliverables: ["audit.json"],
    },
    {
      id: "s2",
      specialist: "code",
      role: "execute",
      instruction: "Build standalone HTML report from audit.json",
      depends_on: ["s1"],
      deliverables: ["report.html"],
    },
  ],
};

const SAMPLE_RUN: any = {
  status: "done",
  text: "Here is the **verified** Q1 margin analysis with [isolated report](#report) and inline \\u0060SELECT region, margin FROM sales\\u0060.\\n\\n\\u0060\\u0060\\u0060python\\ndef check_margin(rows: int) -> bool:\\n    # WCAG 2.1 AA verified\\n    return rows > 0\\n\\u0060\\u0060\\u0060",
  reasoning: "Checked 4 regions in margins.csv via DuckDB.",
  elapsed: 1.6,
  trimmed: 1,
  route: {
    mode: "team",
    method: "router",
    specialists: [
      { id: "finance", name: "Spike Finance", provider: "Spike Local", model: "Qwen3.5-4B", adapter: "spike-finance-v1.gguf", profile_only: true },
      { id: "medicine", name: "Spike Medicine", provider: "Spike Local", model: "Qwen3.5-4B", adapter: "spike-medicine-v1.gguf", profile_only: false },
    ],
  },
  skills: ["dashboard-creator"],
  design: { id: "editorial", name: "Editorial" },
  memory: { rules: 1, notes: [{ id: "m-1", kind: "rule", source: "file:notes.md", preview: "Use UTF-8" }], glossary: ["EBITDA"] },
  privacy: { "secret.env": 1 },
  order: ["st-1"],
  subtasks: {
    "st-1": { id: "st-1", specialist: "finance", name: "Spike Finance", role: "execute", instruction: "Compute regional margin", text: "Region North: 24.5%", done: true, elapsed: 0.8, round: 1 },
  },
  verifications: [
    { round: 1, method: "checker", returned: [], checks: [{ path: "summary.md", ok: true, bytes: 480 }], criteria: [{ text: "Dark mode meets 4.5:1 text contrast", ok: true }] },
  ],
  tools: [
    {
      id: "tc-1",
      name: "query_data",
      arguments: { sql: "SELECT region, margin FROM margins" },
      result: "2 rows",
      ok: true,
      checkpoint: "cp-1",
      file: "summary.md",
      ui: {
        kind: "data_table",
        title: "Regional Margins",
        sql: "SELECT region, margin FROM margins",
        columns: ["region", "margin"],
        types: ["VARCHAR", "DOUBLE"],
        rows: [["North", 24.5], ["South", null]],
        truncated: false,
        tables: [{ name: "margins", file: "margins.csv", rows: 2 }],
        guardian: { sql: "SELECT region, margin FROM margins LIMIT 100", explanation: { en: "Bounded query", es: "Consulta acotada" } },
        backtest: [{ method: "seasonal_naive", mae: 0.42, folds: 3 }],
        forecast: { method: "seasonal_naive" },
        lineage: [{ step: 1, operation: "clean_csv", report: { before: { rows: 2, columns: 2 }, after: { rows: 2, columns: 2 }, steps: [{ code: "bom_stripped", count: 1 }] } }],
      },
    },
    {
      id: "tc-2",
      name: "geo_map",
      arguments: {},
      result: "ok",
      ok: true,
      ui: {
        kind: "geo_map",
        title: "Regional Coverage",
        svg: SAMPLE_SVG,
        source: "regions.geojson",
        projection: "mercator",
        lat_ts: 40.4,
        radius_km: 6371,
        stats: { features: 1, points: 0, lines: 0, polygons: 1 },
        bbox: [-3.7, 40.4, 2.1, 41.4],
        value: null,
        legend: [],
        rows: [{ name: "Iberia", points: 4, length_km: 0, perimeter_km: 120.5, area_km2: 850.2 }],
        rows_truncated: false,
        skipped: [],
      },
    },
    {
      id: "tc-3",
      name: "architecture_graph",
      arguments: {},
      result: "ok",
      ok: true,
      ui: {
        kind: "architecture",
        title: "SPIKE Modules",
        svg: SAMPLE_SVG,
        lazy: false,
        cycles: [],
        cycles_total: 0,
        stats: { modules: 12, python: 10, javascript: 2, edges: 18, static: 18, lazy: 0, type: 0, external: 2, unresolved: 0, cycles: 0, in_cycles: 0, shown: 12 },
        truncated: {},
        errors: [],
      },
    },
    {
      id: "tc-4",
      name: "godot_check",
      arguments: {},
      result: "ok",
      ok: true,
      ui: {
        kind: "godot_check",
        project: "sim/project.godot",
        version: "4.3",
        passed: true,
        scripts: 1,
        seconds: 0.6,
        not_checked: 0,
        checks: [{ kind: "scene", name: "Main.tscn", ok: true, problems: [] }],
      },
    },
    {
      id: "tc-5",
      name: "dev_diagnostic",
      arguments: {},
      result: "ok",
      ok: true,
      ui: {
        kind: "dev_diagnostic",
        report: "visual",
        url: "http://127.0.0.1:5173",
        issues: [],
      },
    },
    {
      id: "tc-6",
      name: "live_order",
      arguments: {},
      result: "ok",
      ok: true,
      ui: {
        kind: "live_order",
        order: {
          id: "ord-1",
          created: 1730000000,
          exchange: "binance",
          sandbox: true,
          symbol: "BTC/USDT",
          side: "buy",
          type: "limit",
          amount: 0.05,
          price: 60000,
          est_price: 60000,
          notional: 3000,
          status: "placed",
          decided: 1730000010,
          result: "Filled on sandbox",
        },
      },
    },
  ],
  permissions: [
    {
      id: "perm-1",
      tool: "dependency_doctor",
      risk: "network",
      arguments: { path: "pyproject.toml" },
      status: "pending",
      reason: "Audits contact package registries.",
      isolation: { isolated: true, backend: "sandbox-exec", reason: "", code: "" },
    },
  ],
  questions: [
    {
      id: "q-1",
      question: "Which fiscal calendar should we use?",
      options: ["April–March", "January–December"],
      status: "pending",
    },
  ],
  desktop: {
    task: "dsk-1",
    goal: "Export chart PNG",
    provider: "Spike Local",
    model: "Qwen3.5-4B",
    tool: "computer",
    max_steps: 20,
    steps: 1,
    reason: "completed",
    error: null,
    final: "Exported chart.png",
    actions: [{ step: 1, action: "left_click", x: 300, y: 200, decision: "approve", ok: true }],
    screenshots: "none",
    shots: [],
    usage: { input: 400, output: 30, calls: 1 },
  },
  trust: {
    counts: { verified: 1, tool_checked: 1, hypothesis: 0, unchecked: 0 },
    claims: [
      {
        id: "cl-1",
        text: "Q1 net margin reached 24.5%.",
        label: "verified",
        why: "citation",
        citations: [{ source: "summary.md", status: "verified", ok: true, found: 1 }],
      },
    ],
    skipped: 0,
    escalation: {
      status: "offered",
      reasons: ["unchecked"],
      unchecked: 1,
      threshold: 1,
      offers: [{ provider_id: "cloud-pro", name: "Cloud Pro", model: "pro-1", paid: true, blocked: null, estimated_cost: 0.0012, files_withheld: 1 }],
    },
  },
  minds: {
    n: 2,
    chosen: 0,
    why: { kind: "trust", verified: 1 },
    minds: [
      { index: 0, temperature: 0.2, ok: true, elapsed: 1.1, counts: { verified: 1, tool_checked: 0, hypothesis: 0, unchecked: 0 }, run: { status: "done", text: "Net margin is 24.5%." } },
      { index: 1, temperature: 0.7, ok: true, elapsed: 1.3, counts: { verified: 1, tool_checked: 0, hypothesis: 0, unchecked: 0 }, run: { status: "done", text: "Q1 margin is 24.5%." } },
    ],
  },
  forge: {
    report: {
      verified: true,
      rounds: 1,
      criteria: [{ text: "Dark mode meets 4.5:1 text contrast", ok: true }],
      deliverables: [{ path: "summary.md", ok: true, bytes: 480 }],
      unresolved: [],
    },
  },
  learn: {
    saved: [{ id: "m-1", kind: "rule", text: "Always use UTF-8", existing: false }],
    correction: { status: "proposed", text: "Cite exact DuckDB row numbers" },
  },
  events: [
    { ts: 0.1, type: "route", mode: "single", method: "router", specialists: [{ id: "finance", name: "Spike Finance", provider: "Spike Local", model: "Qwen3.5-4B" }] },
    { ts: 0.8, type: "token", content: "Verified Q1 margin: 24.5%." },
    { ts: 1.2, type: "done", elapsed: 1.2 },
  ],
};

function Harness() {
  if (view === "setup") {
    return <SetupWizard />;
  }
  if (view === "settings") {
    return (
      <ArtifactContext.Provider value={() => {}}>
        <SettingsDialog onClose={() => {}} onDesktop={() => {}} specialists={SPECIALISTS as any} providers={PROVIDERS as any} reloadProviders={() => {}} />
      </ArtifactContext.Provider>
    );
  }
  if (view === "forge") {
    return (
      <main className="main" style={{ height: "auto", minHeight: "100vh" }}>
        <Forge specialists={SPECIALISTS as any} providers={PROVIDERS as any} projectId="p-1" initialTask={SAMPLE_BLUEPRINT.goal}
          initialBlueprint={SAMPLE_BLUEPRINT as any} onRun={() => {}} onClose={() => {}} />
        <Prototypes specialists={SPECIALISTS as any} projectId="p-1" onBack={() => {}} onClose={() => {}} />
      </main>
    );
  }
  if (view === "creator") {
    return (
      <main className="main" style={{ height: "auto", minHeight: "100vh" }}>
        <Creator specialists={SPECIALISTS as any} providers={PROVIDERS as any} projectId="p-1" designs={DESIGNS as any}
          projectDesign="editorial" onRun={() => {}} onClose={() => {}} />
      </main>
    );
  }
  if (view === "workflows") {
    return (
      <ArtifactContext.Provider value={() => {}}>
        <main className="main" style={{ height: "auto", minHeight: "100vh" }}>
          <WorkflowBuilder projectId="p-1" providers={PROVIDERS as any} onClose={() => {}} />
        </main>
      </ArtifactContext.Provider>
    );
  }
  if (view === "lab") {
    return (
      <main className="main" style={{ height: "auto", minHeight: "100vh" }}>
        <Lab specialists={SPECIALISTS as any} providers={PROVIDERS as any} onClose={() => {}} />
      </main>
    );
  }
  if (view === "research") {
    return (
      <main className="main" style={{ height: "auto", minHeight: "100vh" }}>
        <Research conversationId="c-1" projectId="p-1" projectName="Q1 Margin Audit" specialists={SPECIALISTS as any}
          providers={PROVIDERS as any} onRun={() => {}} onClose={() => {}} />
      </main>
    );
  }
  if (view === "projects") {
    return (
      <main className="main" style={{ height: "auto", minHeight: "100vh", padding: 16 }}>
        <style>{".modal-backdrop { position: static !important; inset: auto !important; padding: 12px 0 !important; }"}</style>
        <ProjectPanel project={PROJECTS[0] as any} specialists={SPECIALISTS as any} designs={DESIGNS as any} onEdit={() => {}} />
        <ProjectDialog project={PROJECTS[0] as any} specialists={SPECIALISTS as any} designs={DESIGNS as any}
          onClose={() => {}} onSaved={() => {}} onDeleted={() => {}} />
        <WorkspacePanel specialists={SPECIALISTS as any} onClose={() => {}} />
      </main>
    );
  }
  if (view === "device-lab") {
    return (
      <ArtifactContext.Provider value={() => {}}>
        <DeviceLab onClose={() => {}} />
      </ArtifactContext.Provider>
    );
  }
  if (view === "subtitles") {
    return <SubtitleStudio projectId="p-1" projectName="Q1 Margin Audit" onClose={() => {}} />;
  }
  if (view === "palette") {
    const none = () => {};
    const handlers: any = new Proxy({}, { get: () => none });
    return <CommandPalette onClose={none} ctx={{ busy: false, desktopOn: true, inProject: true, specialists: SPECIALISTS as any, projects: PROJECTS as any, handlers }} />;
  }
  if (view === "tour") return <Tour />;
  if (view === "modals") {
    return (
      <div>
        <style>{".modal-backdrop, dialog { position: static !important; inset: auto !important; padding: 12px 0 !important; display: block !important; }"}</style>
        <HistorySearch projects={PROJECTS as any} projectId="p-1" onClose={() => {}} onSelect={() => {}} />
        <Replay events={SAMPLE_RUN.events} specialists={SPECIALISTS as any} onClose={() => {}} />
        <DesktopTask onClose={() => {}} onFinished={() => {}} onChat={() => {}} />
      </div>
    );
  }

  return (
    <ArtifactContext.Provider value={() => {}}>
      <div className="app with-sidebar" style={{ height: "auto", minHeight: "100vh", flexDirection: "column" }}>
        <style>{".artifact-panel { position: static !important; width: 100% !important; height: 320px !important; }"}</style>
        <aside className="sidebar" aria-label="Conversations" style={{ position: "static", marginLeft: 0, width: "100%", maxWidth: 320 }}>
          <div className="conv-group">Today</div>
          <div className="conv-list">
            <div className="conv active">
              <button type="button" className="conv-title">Quarterly margin review</button>
              <button type="button" className="icon-btn conv-del" aria-label="Delete chat">×</button>
            </div>
          </div>
          <div className="sidebar-bottom">
            <div className="engine-status"><span className="status-dot on" />Local engine ready</div>
          </div>
        </aside>

        <main className="main" style={{ padding: 16, gap: 14 }}>
          <div className="welcome-mark" style={{ width: 28, height: 28, background: "var(--accent)", borderRadius: 8 }} />
          <div className="flash">Saved default provider</div>

          <Composer
            onSend={() => {}}
            onStop={() => {}}
            busy={false}
            mode="auto"
            setMode={() => {}}
            providerId="spike-local"
            setProviderId={() => {}}
            specialists={SPECIALISTS.filter((s) => s.id !== "core") as any}
            providers={PROVIDERS as any}
            followUp={false}
            designs={DESIGNS as any}
            design="editorial"
            setDesign={() => {}}
            projectDesign="Editorial"
            projectId="p-1"
            conversationId="c-1"
          />

          <div className="msg user">
            <button type="button" className="icon-btn edit-btn" aria-label="Edit message">✎</button>
            <div className="bubble"><div className="markdown"><p>Check verified badges, tables, maps and code blocks.</p></div></div>
          </div>

          <AssistantMessage
            run={SAMPLE_RUN}
            specialists={SPECIALISTS as any}
            providers={PROVIDERS as any}
            projectId="p-1"
            messageId="msg-1"
            question="Audit Q1 margins"
            onPermission={() => {}}
            onRetry={() => {}}
            onReplay={() => {}}
          />

          <section className="card" aria-label="Status badges and links">
            <div className="row" style={{ alignItems: "center" }}>
              <span className="badge ok">2/2 criteria met</span>
              <span className="badge status-trained">trained</span>
              <span className="badge status-evaluated">evaluated</span>
              <span className="badge status-placed">placed</span>
              <span className="badge status-planned">planned</span>
              <span className="badge warn">needs review</span>
              <span className="badge kind-rule">rule</span>
              <span className="chip skill-chip">✦ dashboard-creator</span>
              <span className="chip trust-chip ok">1 verified</span>
              <span className="badge claim-badge verified">verified</span>
              <span className="role role-execute">execute</span>
              <span className="role role-verify">verify</span>
            </div>
            <div className="flash-box" role="status">Workspace indexed locally without errors.</div>
            <div className="warn-box">External search sends your query text to the configured provider.</div>
            <div className="error-box">Connection refused on port 8740.</div>
            <ul className="tune-rows"><li className="best">Checkpoint 400 · 0.84</li></ul>
            <ul className="evo-checks"><li className="ok"><b>PASS</b> Regression suite</li></ul>
            <div><span className="side side-buy">BUY</span> <span className="muted">10 units · simulated</span></div>
            <button type="button" className="template-card">
              <span className="template-icon" aria-hidden="true">★</span>
              <b>Verified Dashboard</b>
              <span className="muted small">Local HTML artifact</span>
            </button>
          </section>

          <div className="trace">
            <div className="trace-item live">
              <button type="button" className="trace-head"><span className="trace-title">Running local check</span></button>
            </div>
          </div>
          <div className="typing" aria-label="Assistant typing">
            <span className="dot" /><span className="dot" /><span className="dot" />
            <span className="muted">Checking...</span>
          </div>
        </main>

        <ArtifactPanel
          doc={{ title: "Verified Q1 Dashboard", html: "<h1>Verified Q1 Dashboard</h1><p>Net margin 24.5%</p>", filename: "dashboard.html" }}
          onClose={() => {}}
        />
      </div>
    </ArtifactContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<Harness />);
`;

const virtualHarness = {
  name: "g18-a11y-harness",
  resolveId: (id) => (id === ENTRY ? ENTRY : null),
  load: (id) => (id === ENTRY ? HARNESS : null),
  configureServer(srv) {
    srv.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/__g18.html")) return next();
      const html = await srv.transformIndexHtml(
        req.url,
        `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
          `<title>G18 accessibility harness</title></head><body><div id="root"></div>` +
          `<script type="module" src="${ENTRY}"></script></body></html>`,
      );
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(html);
    });
  },
};

const server = await createServer({
  root,
  logLevel: "error",
  plugins: [virtualHarness],
  server: { host: "127.0.0.1", port: 5198, strictPort: false },
});
await server.listen();
const base = server.resolvedUrls.local[0];
const executablePath = [
  process.env.CHROMIUM_PATH,
  "/Users/jpima/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  "/Users/jpima/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell",
  "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(executablePath ? { executablePath } : {});

const runs = [
  { name: "wide-light", viewport: { width: 1360, height: 860 }, colorScheme: "light", themeParam: "light" },
  { name: "wide-dark-system", viewport: { width: 1360, height: 860 }, colorScheme: "dark", themeParam: "" },
  { name: "wide-dark-explicit", viewport: { width: 1360, height: 860 }, colorScheme: "light", themeParam: "dark" },
  {
    name: "narrow-dark-reduced-touch",
    viewport: { width: 375, height: 760 },
    colorScheme: "dark",
    reducedMotion: "reduce",
    hasTouch: true,
    isMobile: true,
    themeParam: "",
  },
];

const views = [
  {
    id: "chat",
    readyText: "2/2 criteria met",
    prepare: async (page, run) => {
      // Expand ArtifactFiles plain-text preview and ArtifactPanel comments tab to audit their controls & focus rings
      const previewBtn = page.locator(".artifact-files button").first();
      if (await previewBtn.count()) {
        await previewBtn.click();
        await page.locator(".artifact-file-text pre").waitFor();
      }
      if (!run.hasTouch) {
        const pre = page.locator(".artifact-file-text pre").first();
        if (await pre.count()) {
          await pre.focus();
          const preFocus = await pre.evaluate((el) => {
            const s = getComputedStyle(el);
            return { outlineStyle: s.outlineStyle, outlineColor: s.outlineColor, bg: getComputedStyle(document.body).backgroundColor };
          });
          if (preFocus.outlineStyle !== "solid") {
            fail(`${run.name}/chat: .artifact-file-text pre missing solid focus outline`);
          }
        }
      }
    },
  },
  { id: "setup", readySelector: ".setup-wizard" },
  {
    id: "settings",
    readySelector: ".modal[role='dialog']",
    prepare: async (page, run) => {
      // Audit every settings tab (and Memory's 5 sub-tabs + editing state)
      const tabButtons = page.locator(".tabs[role='tablist'] > button[role='tab']");
      const count = await tabButtons.count();
      for (let i = 0; i < count; i++) {
        await tabButtons.nth(i).click();
        const label = (await tabButtons.nth(i).textContent())?.trim() || `tab-${i}`;
        // If on Memory tab, also check all 5 sub-tabs and memory note editing state
        const memSub = page.locator(".memory-sub[role='tablist'] > button[role='tab']");
        if (await memSub.count()) {
          // Click Edit on the first memory note to verify edit textarea accessible label
          const editBtn = page.locator(".card .card-head button.btn.small").first();
          if (await editBtn.count()) {
            await editBtn.click();
            await auditDom(page, `${run.name}/settings:${label}:edit-note`);
          }
          const subCount = await memSub.count();
          for (let j = 1; j < subCount; j++) {
            await memSub.nth(j).click();
            const subLabel = (await memSub.nth(j).textContent())?.trim() || `sub-${j}`;
            await auditDom(page, `${run.name}/settings:${label}:${subLabel}`);
          }
        } else {
          await auditDom(page, `${run.name}/settings:${label}`);
        }
      }
    },
  },
  {
    id: "forge",
    readySelector: ".forge",
    prepare: async (page, run) => {
      const summary = page.locator(".forge-skills summary").first();
      if (await summary.count()) {
        await summary.click();
        if (!run.hasTouch) {
          await summary.focus();
        }
      }
      const openProto = page.locator("[data-proto-run] button").first();
      if (await openProto.count()) {
        await openProto.click();
        await page.locator("[data-proto-compare]").waitFor();
      }
    },
  },
  {
    id: "creator",
    readySelector: ".template-card",
    prepare: async (page) => {
      await page.locator(".template-card").first().click();
    },
  },
  {
    id: "workflows",
    readySelector: ".wf-canvas",
    prepare: async (page) => {
      const wfSelect = page.locator(".wf-bar select").first();
      await wfSelect.selectOption("wf-1");
      await page.locator(".wf-node").first().waitFor();
      const openRunBtn = page.locator(".wf-history button").first();
      if (await openRunBtn.count()) {
        await openRunBtn.click();
        await page.locator(".wf-state.st-ok").first().waitFor();
      }
    },
  },
  {
    id: "lab",
    readySelector: ".lab",
    prepare: async (page) => {
      const probeBtn = page.locator(".lab-fields .row button").nth(2);
      if (await probeBtn.count()) await probeBtn.click();
      const histBtn = page.locator(".lab > .row button").first();
      if (await histBtn.count()) await histBtn.click();
    },
  },
  {
    id: "research",
    readySelector: ".research-panel",
    prepare: async (page) => {
      const ta = page.locator(".research-inputs textarea");
      await ta.fill("summary.md\ndraft.md");
      await page.locator(".research-inputs > button").click();
      await page.locator(".research-preview button.primary").waitFor();
      await page.locator(".research-preview button.primary").click();
      await page.locator(".research-result").waitFor();
    },
  },
  {
    id: "projects",
    readySelector: ".project-panel",
    prepare: async (page) => {
      const branches = page.locator(".project-branches summary");
      if (await branches.count()) {
        await branches.click();
        const cmpBtn = page.locator(".project-branches .row button").nth(1);
        if (await cmpBtn.count()) await cmpBtn.click();
      }
    },
  },
  {
    id: "device-lab",
    readySelector: "dialog.device-lab",
    prepare: async (page) => {
      await page.locator("input[name='device-lab-approve']").check();
      await page.getByTestId("device-lab-run").click();
      await page.getByTestId("device-lab-results").waitFor();
    },
  },
  {
    id: "subtitles",
    readySelector: "dialog.subtitle-studio",
    prepare: async (page) => {
      await page.locator("input[name='media-path']").fill("media/clip.mp4");
      await page.locator("input[name='approve-media']").check();
      await page.getByTestId("subtitle-transcribe").click();
      await page.locator(".subtitle-cue").first().waitFor();
    },
  },
  { id: "palette", readySelector: ".palette [role='option']" },
  { id: "tour", readySelector: ".tour[role='dialog']" },
  {
    id: "modals",
    readySelector: "dialog.history-dialog",
    prepare: async (page) => {
      const q = page.locator(".history-query input");
      await q.fill("margin");
      await page.locator(".history-query button[type='submit']").click();
      await page.locator(".history-hit").first().waitFor();
    },
  },
];

async function auditDom(page, label) {
  const report = await page.evaluate((src) => window.eval(`(${src})`)(), visualChecksSource);
  const blocking = report.issues.filter((i) => ["contrast", "alt", "label", "overflow"].includes(i.code));
  if (blocking.length) {
    fail(`${label}: visual_checks found blocking issues: ${JSON.stringify(blocking)}`);
  }

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 0) {
    fail(`${label}: horizontal overflow ${overflow}px`);
  }

  // Verify accessible roles, names, tab-order invariants and SVG text contrast
  const semIssues = await page.evaluate(() => {
    const problems = [];
    const hasName = (el) => {
      const aria = (el.getAttribute("aria-label") || "").trim();
      if (aria) return true;
      const refs = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
      return refs.some((id) => document.getElementById(id)?.textContent?.trim());
    };
    for (const d of document.querySelectorAll("dialog[open], [role='dialog'], [role='alertdialog']")) {
      if (!hasName(d)) problems.push(`dialog without accessible name: ${d.tagName}.${d.className}`);
    }
    for (const tl of document.querySelectorAll("[role='tablist']")) {
      if (!hasName(tl)) problems.push(`tablist without accessible name: ${tl.tagName}.${tl.className}`);
      const tabs = tl.querySelectorAll("[role='tab']");
      if (!tabs.length) problems.push(`tablist without role='tab' children: ${tl.className}`);
    }
    for (const el of document.querySelectorAll("[tabindex]")) {
      const ti = Number(el.getAttribute("tabindex"));
      if (Number.isFinite(ti) && ti > 0) {
        problems.push(`positive tabindex (${ti}) breaks natural Tab order: ${el.tagName}.${el.className}`);
      }
    }
    // Check SVG workflow text contrast (.wf-state, .wf-name, .wf-type, .wf-sub) against .wf-box fill
    const rgba = (value) => {
      const m = value && value.match(/^rgba?\(([^)]+)\)$/);
      if (!m) return null;
      const raw = m[1].trim().split(/[,\s/]+/).filter(Boolean).map(Number);
      return raw.length >= 3 && raw.slice(0, 3).every(Number.isFinite) ? raw.slice(0, 3) : null;
    };
    const lum = (rgb) =>
      rgb
        .map((v) => v / 255)
        .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
        .reduce((a, c, i) => a + c * [0.2126, 0.7152, 0.0722][i], 0);
    for (const node of document.querySelectorAll(".wf-node")) {
      const box = node.querySelector(".wf-box");
      if (!box) continue;
      const bg = rgba(getComputedStyle(box).fill);
      if (!bg) continue;
      for (const txt of node.querySelectorAll("text.wf-state, text.wf-name, text.wf-type, text.wf-sub")) {
        const fg = rgba(getComputedStyle(txt).fill);
        if (!fg) continue;
        const l1 = lum(fg), l2 = lum(bg);
        const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        if (ratio < 4.5) {
          problems.push(`SVG text contrast ${ratio.toFixed(2)} < 4.5 on ${txt.className.baseVal}`);
        }
      }
    }
    return problems;
  });
  if (semIssues.length) {
    fail(`${label}: semantic/SVG a11y issues: ${JSON.stringify(semIssues)}`);
  }
}

try {
  for (const run of runs) {
    const ctx = await browser.newContext({
      viewport: run.viewport,
      colorScheme: run.colorScheme,
      reducedMotion: run.reducedMotion || "no-preference",
      hasTouch: Boolean(run.hasTouch),
      isMobile: Boolean(run.isMobile),
    });
    const page = await ctx.newPage();
    page.setDefaultTimeout(5000);
    await page.route("**/api/memory-graph/svg*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 80" width="240" height="80"><rect x="4" y="4" width="232" height="72" rx="8" fill="#18231d" stroke="#3a8f6b"/><text x="20" y="44" fill="#eef4ef" font-size="13">SPIKE</text></svg>',
      }),
    );
    const errors = [];
    page.on("pageerror", (e) => { console.error("PAGEERROR:", e); errors.push(String(e)); });
    page.on("console", (m) => { if (m.type() === "error") console.error("CONSOLE ERROR:", m.text()); });

    for (const v of views) {
      const q = new URLSearchParams({ view: v.id });
      if (run.themeParam) q.set("theme", run.themeParam);
      await page.goto(`${base}__g18.html?${q}`);
      if (v.readyText) await page.getByText(v.readyText).first().waitFor();
      if (v.readySelector) await page.locator(v.readySelector).first().waitFor();
      if (v.prepare) await v.prepare(page, run);

      const label = `${run.name}/${v.id}`;
      await auditDom(page, label);

      if (v.id === "chat") {
        if (run.hasTouch) {
          const touchOpacity = await page.locator(".conv-del").evaluate((el) => getComputedStyle(el).opacity);
          if (touchOpacity !== "1") fail(`${label}: .conv-del must be visible on touch devices, got opacity=${touchOpacity}`);
        } else {
          await page.locator(".conv-title").focus();
          const withinOpacity = await page.locator(".conv-del").evaluate((el) => getComputedStyle(el).opacity);
          if (withinOpacity !== "1") fail(`${label}: .conv:focus-within must reveal .conv-del, got opacity=${withinOpacity}`);
          await page.keyboard.press("Tab");
          const delState = await page.locator(".conv-del").evaluate((el) => {
            const s = getComputedStyle(el);
            return { active: el === document.activeElement, opacity: s.opacity, outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth };
          });
          if (!delState.active || delState.opacity !== "1" || delState.outlineStyle !== "solid") {
            fail(`${label}: Tab to .conv-del failed focus-visible state: ${JSON.stringify(delState)}`);
          }
        }

        if (run.reducedMotion === "reduce") {
          const motion = await page.evaluate(() => {
            const mark = getComputedStyle(document.querySelector(".welcome-mark"));
            const dot = getComputedStyle(document.querySelector(".typing .dot"));
            const sidebar = getComputedStyle(document.querySelector(".sidebar"));
            const composer = getComputedStyle(document.querySelector(".composer"));
            return {
              markAnim: mark.animationName,
              dotAnim: dot.animationName,
              dotOpacity: Number(dot.opacity),
              sidebarTrans: sidebar.transitionDuration,
              composerTrans: composer.transitionDuration,
            };
          });
          if (
            motion.markAnim !== "none" ||
            motion.dotAnim !== "none" ||
            motion.dotOpacity < 0.7 ||
            motion.sidebarTrans !== "0s" ||
            motion.composerTrans !== "0s"
          ) {
            fail(`${label}: prefers-reduced-motion not respected: ${JSON.stringify(motion)}`);
          }
        }
        await page.screenshot({ path: `${out}/g6-${run.name}.png`, fullPage: !run.isMobile });
      }

      if (v.id === "workflows" && run.reducedMotion === "reduce") {
        const wfAnim = await page.locator(".wf-node.st-running .wf-box").first().evaluate((el) => getComputedStyle(el).animationName);
        if (wfAnim !== "none") {
          fail(`${label}: workflow running node animation not disabled under prefers-reduced-motion: ${wfAnim}`);
        }
      }

      await page.screenshot({ path: `${out}/g18-${run.name}-${v.id}.png`, fullPage: false });
    }

    if (errors.length) fail(`${run.name}: page errors: ${errors.join(" | ")}`);
    console.log(`${run.name}: ok (${views.length} views audited)`);
    await ctx.close();
  }
} finally {
  await browser.close();
  await server.close();
}
