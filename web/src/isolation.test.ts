import { describe, expect, it } from "vitest";
import { dicts } from "./i18n";
import { isolationText, reasonText } from "./isolation";
import { applyEvent, emptyRun } from "./run";

// every `code` spike/tools/sandbox.py can give a run that is not isolated
const CODES = ["off", "approved_command", "windows", "unsupported_os", "no_bwrap", "bwrap_failed", "no_sandbox_exec", "sandbox_exec_failed"];

describe("isolation text", () => {
  it("has every reason in Spanish and English", () => {
    for (const lang of ["es", "en"] as const) for (const code of CODES) expect(dicts[lang].isolation.reasons[code]).toBeTruthy();
    expect(Object.keys(dicts.es.isolation.reasons).sort()).toEqual(Object.keys(dicts.en.isolation.reasons).sort());
  });
  it("says aislado / sin aislamiento: <motivo> in Spanish and isolated / not isolated in English", () => {
    const on = { isolated: true, backend: "bwrap", reason: "", code: "" };
    const off = { isolated: false, backend: "none", reason: "bubblewrap (bwrap) is not installed", code: "no_bwrap" };
    expect(isolationText(on, dicts.es.isolation)).toBe("aislado (bwrap): sin red; escribe solo en la carpeta de trabajo y en una temporal privada");
    expect(isolationText(off, dicts.es.isolation)).toBe("sin aislamiento: bubblewrap (bwrap) no está instalado");
    expect(isolationText(on, dicts.en.isolation)).toBe("isolated (bwrap): no network; writes only in the working folder and a private temp folder");
    expect(isolationText(off, dicts.en.isolation)).toBe("not isolated: bubblewrap (bwrap) is not installed");
  });
  it("says why an approved command runs outside the sandbox under auto, apart from the no-sandbox reasons", () => {
    const cmd = { isolated: false, backend: "none", reason: "approved commands run outside the sandbox in auto mode", code: "approved_command" };
    expect(isolationText(cmd, dicts.es.isolation)).toBe("sin aislamiento: los comandos aprobados se ejecutan fuera del aislamiento en modo auto");
    expect(isolationText(cmd, dicts.en.isolation)).toBe("not isolated: approved commands run outside the sandbox in auto mode");
  });
  it("keeps what the system said when a sandbox program fails, and the server's text for an unknown code", () => {
    const failed = { reason: "bwrap does not work here: bwrap: No permissions to creating new namespace", code: "bwrap_failed" };
    expect(reasonText(failed, dicts.es.isolation)).toBe("bwrap no funciona en este ordenador: bwrap: No permissions to creating new namespace");
    expect(reasonText({ reason: "something new", code: "later" }, dicts.en.isolation)).toBe("something new");
  });
  it("reaches the permission card from the event", () => {
    const iso = { isolated: false, backend: "none", reason: "the sandbox is off in Settings", code: "off", line: "not isolated: the sandbox is off in Settings" };
    const run = applyEvent(emptyRun(), { type: "permission_request", id: "p1", tool: "python", risk: "execute", arguments: { code: "1" }, isolation: iso });
    expect(run.permissions[0]).toMatchObject({ id: "p1", status: "pending", isolation: iso });
    expect(applyEvent(emptyRun(), { type: "permission_request", id: "p2", tool: "write_file", risk: "write", arguments: {} }).permissions[0].isolation).toBeUndefined();
  });
});
