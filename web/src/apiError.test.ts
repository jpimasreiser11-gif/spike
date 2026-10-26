import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { projectError } from "./i18n";

afterEach(() => vi.unstubAllGlobals());

it("translates project import and path errors in both languages", () => {
  expect(projectError("invalid project note (kind/text)", "es")).toBe("Nota de proyecto no válida (tipo o texto).");
  expect(projectError("invalid project note (kind/text)", "en")).toBe("Invalid project note (kind or text).");
  expect(projectError("file path leaves the project or uses a symbolic link", "es")).toContain("enlace simbólico");
  expect(projectError("other error", "es")).toBe("other error");
});

it("shows the translated project error when an upload fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 400, statusText: "Bad Request",
    json: async () => ({ detail: "invalid project note (kind/text)" }),
  }));
  await expect(api.upload("POST", "/api/projects/import", new Blob())).rejects.toThrow(/Nota de proyecto|Invalid project note/);
});
