import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { dicts } from "./i18n";
import type { ProviderInfo, Specialist } from "./types";
import { SpecialistCard } from "./components/SpecialistCard";

const PROVIDERS: ProviderInfo[] = [
  {
    id: "spike-local",
    kind: "llamacpp",
    name: "SPIKE Local (llama.cpp)",
    base_url: "http://127.0.0.1:8737/v1",
    model: "Qwen3.5-4B",
    paid: false,
    allow_paid: false,
    local: true,
    has_key: false,
    capabilities_effective: { adapters: true },
  },
  {
    id: "deepseek",
    kind: "openai",
    name: "DeepSeek",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    paid: true,
    allow_paid: true,
    local: false,
    has_key: true,
    capabilities_effective: { adapters: false },
  },
];

const MEDICINE_ACCEPTED: Specialist = {
  id: "medicine",
  name: "Spike Medicine",
  domain: "Clinical Medicine & Biomedical Literature",
  description: "Clinical reasoning, differential diagnosis, pharmacology, and evidence synthesis.",
  adapter: "spike-medicine",
  adapter_status: "evaluated",
  sensitive: true,
  tools: ["read_file"],
  base_model: "qwen3.5-4b",
  adapter_accepted: true,
  adapter_reasons: [
    "medicine: +35.07 pts (need ≥ 3.0), p = 0 (need ≤ 0.05)",
    "general: -0.62 pts (max drop 1.5)",
  ],
  adapter_file_present: true,
  loaded_on_providers: [],
  active_provider: "spike-local",
  provider_supports_adapters: true,
  active_mode: "instruction_profile",
  layers: {
    base_instructions: true,
    user_instructions: true,
    learned_instructions: true,
    knowledge_count: 2,
  },
};

describe("SpecialistCard (G4)", () => {
  it("has complete es/en i18n parity for specialist status labels", () => {
    expect(Object.keys(dicts.es.specialistStatus)).toEqual(Object.keys(dicts.en.specialistStatus));
  });

  it("shows evaluated and accepted only when catalog and approval receipt both confirm it", () => {
    const htmlAccepted = renderToStaticMarkup(
      <SpecialistCard
        specialist={MEDICINE_ACCEPTED}
        providers={PROVIDERS}
        boundProviderId=""
        instructions="Cita guías clínicas"
        onBind={vi.fn()}
        onInstructions={vi.fn()}
        locale="es"
      />,
    );
    expect(htmlAccepted).toContain("Evaluado y aceptado");
    expect(htmlAccepted).toContain("+35.07 pts");
    expect(htmlAccepted).toContain("-0.62 pts");
    expect(htmlAccepted).toContain("Perfil de instrucciones");
    expect(htmlAccepted).toContain("Instrucciones base");
    expect(htmlAccepted).toContain("Instrucciones del usuario");
    expect(htmlAccepted).toContain("Instrucciones aprendidas");
    expect(htmlAccepted).toContain("Conocimiento (2)");

    // Without receipt (even if adapter="spike-medicine", adapter_file_present=true, adapter_status="evaluated")
    const htmlNoReceipt = renderToStaticMarkup(
      <SpecialistCard
        specialist={{ ...MEDICINE_ACCEPTED, adapter_accepted: false, adapter_reasons: [] }}
        providers={PROVIDERS}
        boundProviderId=""
        instructions=""
        onBind={vi.fn()}
        onInstructions={vi.fn()}
        locale="es"
      />,
    );
    expect(htmlNoReceipt).not.toContain("Evaluado y aceptado");
    expect(htmlNoReceipt).toContain("Evaluado (sin recibo de aprobación)");
  });

  it("never shows evaluated and accepted when catalog status is planned, training, or trained even if receipt/file exist", () => {
    for (const status of ["planned", "training", "trained"] as const) {
      const html = renderToStaticMarkup(
        <SpecialistCard
          specialist={{
            ...MEDICINE_ACCEPTED,
            id: "code",
            name: "Spike Code",
            adapter: "spike-code",
            adapter_status: status,
            adapter_accepted: true, // even if someone passed true, catalog status gates it
          }}
          providers={PROVIDERS}
          boundProviderId=""
          instructions=""
          onBind={vi.fn()}
          onInstructions={vi.fn()}
          locale="en"
        />,
      );
      expect(html).not.toContain("Evaluated and accepted");
    }
  });

  it("renders adapter loaded mode in English when adapter is loaded in llama-server", () => {
    const html = renderToStaticMarkup(
      <SpecialistCard
        specialist={{
          ...MEDICINE_ACCEPTED,
          loaded_on_providers: ["spike-local"],
          active_mode: "adapter_loaded",
        }}
        providers={PROVIDERS}
        boundProviderId=""
        instructions=""
        onBind={vi.fn()}
        onInstructions={vi.fn()}
        locale="en"
      />,
    );
    expect(html).toContain("Evaluated and accepted");
    expect(html).toContain("Adapter loaded in llama-server");
  });
});
