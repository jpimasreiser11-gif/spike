import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { SettingsDialog } from "./components/SettingsDialog";
import { dicts, projectError, t } from "./i18n";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.unstubAllGlobals());

const SETTINGS = {
  custom_instructions: "", use_planner: true, parallel: false, tools_enabled: true, temperature: null, max_tokens: 2048,
  reasoning: null, sandbox: "auto", tool_policies: {}, specialist_bindings: {}, specialist_instructions: {},
  disabled_skills: [], skill_mode: "auto", default_provider: "spike-local",
  trust: { enabled: true, escalate: true, escalate_unchecked: 3, model_pass: false },
  local_runtime: { model: "", adapters: [], context: null, threads: null, gpu_layers: null, kv_cache_type: "q8_0", port: 8737 },
};

function mount(putStatus = 200) {
  const puts: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/settings" && init?.method === "PUT") {
      puts.push(JSON.parse(String(init.body)));
      if (putStatus !== 200) return new Response(JSON.stringify({ detail: "invalid setting 'max_tokens': must be a whole number from 64 to 32768" }), { status: putStatus });
      return new Response(JSON.stringify({ ...SETTINGS, ...(puts[puts.length - 1] as object) }));
    }
    if (url === "/api/settings") return new Response(JSON.stringify(SETTINGS));
    return new Response(JSON.stringify([]));
  }));
  const el = document.createElement("div"); document.body.append(el);
  const root = createRoot(el);
  return { el, root, puts };
}

const render = async (m: ReturnType<typeof mount>) => {
  await act(async () => m.root.render(<SettingsDialog onClose={() => {}} onDesktop={() => {}} specialists={[]} providers={[]} reloadProviders={() => {}} />));
};
const blurWith = async (input: HTMLInputElement, value: string) => {
  await act(async () => {
    input.focus();
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.blur();
  });
};
const numberInput = (el: HTMLElement, min: string) => el.querySelector(`input[type=number][min="${min}"]`) as HTMLInputElement;

it("does not send an out-of-range temperature or max tokens, and says why in the user's language", async () => {
  const m = mount(); await render(m);
  const temp = numberInput(m.el, "0");
  await blurWith(temp, "5");
  expect(m.puts).toEqual([]);
  expect(m.el.querySelector("[role=alert]")!.textContent).toBe(t.settingsCheck.badTemperature);
  expect(temp.value).toBe("");
  const tokens = numberInput(m.el, "64");
  await blurWith(tokens, "10");
  expect(m.puts).toEqual([]);
  expect(m.el.querySelector("[role=alert]")!.textContent).toBe(t.settingsCheck.badMaxTokens);
  await blurWith(numberInput(m.el, "64"), "4096"); // the panel was rebuilt: take the field again
  expect(m.puts).toEqual([{ max_tokens: 4096 }]);
  expect(m.el.querySelector("[role=alert]")).toBeNull();
  await act(async () => m.root.unmount()); m.el.remove();
});

it("shows the translated server error when a save is refused and puts the field back", async () => {
  const m = mount(400); await render(m);
  const tokens = numberInput(m.el, "64");
  await blurWith(tokens, "4096");
  expect(m.puts).toEqual([{ max_tokens: 4096 }]);
  expect(m.el.querySelector("[role=alert]")!.textContent).toContain(t.settingsCheck.rules.max_tokens);
  expect((numberInput(m.el, "64")).value).toBe("2048");
  await act(async () => m.root.unmount()); m.el.remove();
});

it("explains that changes are saved at once, and that reasoning applies to local models only", async () => {
  const m = mount(); await render(m);
  expect(m.el.textContent).toContain(t.settingsCheck.autosave);
  expect(m.el.textContent).toContain(t.settingsCheck.reasoningHint);
  await act(async () => m.root.unmount()); m.el.remove();
});

it("translates server setting errors into both languages", () => {
  for (const lang of ["es", "en"] as const) {
    const rules = dicts[lang].settingsCheck.rules;
    expect(projectError("invalid setting 'temperature': must be a number", lang)).toContain(rules.temperature);
    expect(projectError("invalid setting 'trust': 'escalate_unchecked' must be a whole number", lang)).toContain(rules.trust);
    expect(projectError("invalid setting 'zzz'", lang)).toContain(dicts[lang].settingsCheck.generic);
    expect(projectError("invalid setting 'sandbox': must be one of auto, off, required", lang)).toContain(dicts[lang].settingsCheck.notSaved);
  }
  expect(Object.keys(dicts.es.settingsCheck.rules).sort()).toEqual(Object.keys(dicts.en.settingsCheck.rules).sort());
});
