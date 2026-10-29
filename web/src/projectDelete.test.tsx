import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { PL, ProjectDialog } from "./components/Projects";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("project deletion", () => {
  it("keeps the dialog and project after a failed delete, then allows a confirmed retry", async () => {
    const del = vi.spyOn(api, "del").mockRejectedValueOnce(new Error("File locked / Archivo bloqueado")).mockResolvedValue({ ok: true });
    const deleted = vi.fn();
    const el = document.createElement("div");
    const root = createRoot(el);
    try {
      act(() => root.render(<ProjectDialog project={{ id: "p1", name: "Sitio", instructions: "", mode: "auto", design: "", created: 1, updated: 1 }} specialists={[]} onClose={() => {}} onSaved={() => {}} onDeleted={deleted} />));
      const remove = () => el.querySelector<HTMLButtonElement>("button.danger")!;
      act(() => remove().click());
      expect(del).not.toHaveBeenCalled();
      await act(async () => remove().click());
      expect(el.querySelector('[role="alert"]')?.textContent).toContain("Archivo bloqueado");
      expect(deleted).not.toHaveBeenCalled();
      expect(remove().textContent).toBe(PL.remove);
      act(() => remove().click());
      await act(async () => remove().click());
      expect(del).toHaveBeenCalledTimes(2);
      expect(deleted).toHaveBeenCalledTimes(1);
      expect(deleted).toHaveBeenCalledWith("p1");
    } finally {
      act(() => root.unmount());
      del.mockRestore();
    }
  });

  it("disables repeated delete and save while the request is pending", async () => {
    let resolve!: (value: unknown) => void;
    const del = vi.spyOn(api, "del").mockImplementation(() => new Promise(done => { resolve = done; }));
    const el = document.createElement("div");
    const root = createRoot(el);
    try {
      act(() => root.render(<ProjectDialog project={{ id: "p1", name: "Sitio", instructions: "", mode: "auto", design: "", created: 1, updated: 1 }} specialists={[]} onClose={() => {}} onSaved={() => {}} onDeleted={() => {}} />));
      const button = el.querySelector<HTMLButtonElement>("button.danger")!;
      act(() => button.click());
      act(() => button.click());
      expect(button.disabled).toBe(true);
      expect(el.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);
      act(() => button.click());
      expect(del).toHaveBeenCalledTimes(1);
      await act(async () => resolve({ ok: true }));
    } finally {
      act(() => root.unmount());
      del.mockRestore();
    }
  });
});
