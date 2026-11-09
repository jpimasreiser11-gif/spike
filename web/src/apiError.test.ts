import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { projectError, projectErrors } from "./i18n";

afterEach(() => vi.unstubAllGlobals());

it("translates project import and path errors in both languages", () => {
  expect(projectError("invalid project note (kind/text)", "es")).toBe("Nota de proyecto no válida (tipo o texto).");
  expect(projectError("invalid project note (kind/text)", "en")).toBe("Invalid project note (kind or text).");
  expect(projectError("file path leaves the project or uses a symbolic link", "es")).toContain("enlace simbólico");
  expect(projectError("other error", "es")).toBe("other error");
});

it("translates server error codes and dynamic messages into actionable es/en text", () => {
  const codes = [
    "design system not found",
    "skill not found",
    "built-in skills can be disabled, not deleted",
    "connector not found",
    "provider not found",
    "the built-in local provider cannot be removed",
    "project not found",
    "file not found",
    "invalid file path",
    "conversation not found",
    "memory not found",
    "folder not found",
    "entry not found",
    "topic not found",
    "relation not found",
    "no pending permission request with this id",
    "no pending question with this id",
    "data_app_expired",
    "data_app_conflict",
    "data_app_approval",
    "data_app_project",
    "data_app_invalid",
    "history_filter",
    "project_not_found",
    "invalid_target",
    "invalid_cases",
    "one_probe_target",
    "expired_quote",
    "changed_quote",
    "provider_blocked",
    "unknown_run",
    "Launcher only",
    "Adapter unavailable",
    "Installation busy or insufficient resources",
  ];
  for (const code of codes) {
    expect(projectErrors[code], `missing projectErrors[${code}]`).toBeDefined();
    const es = projectError(code, "es");
    const en = projectError(code, "en");
    expect(es).not.toBe(code);
    expect(en).not.toBe(code);
    expect(es).not.toBe(en);
  }

  const dynamic = [
    "unknown provider 'openai'",
    "unknown project 'demo'",
    "unknown specialist 'medicine'",
    "unknown mode 'fast'",
    "unknown skill 'pdf'",
    "unknown design system 'editorial'",
    "unknown memory scope 'bad'",
    "unknown template 'chart'",
    "unknown component 'router:2'",
    "provider 'openai' already exists",
    "the upload is limited to 25 MB",
    "speech can only be changed on the computer SPIKE runs on",
    "model file not found: qwen3.5-4b.gguf",
  ];
  for (const msg of dynamic) {
    const es = projectError(msg, "es");
    const en = projectError(msg, "en");
    expect(es).not.toBe(msg);
    expect(en).not.toBe(msg);
    expect(es).not.toBe(en);
  }
});

it("shows the translated project error when an upload fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 400, statusText: "Bad Request",
    json: async () => ({ detail: "invalid project note (kind/text)" }),
  }));
  await expect(api.upload("POST", "/api/projects/import", new Blob())).rejects.toThrow(/Nota de proyecto|Invalid project note/);
});
