import { dicts, lang } from "../i18n";
import type { ProviderInfo, Specialist } from "../types";
import { SpecMark } from "./SpecMark";

export function SpecialistCard({
  specialist: s,
  providers,
  boundProviderId,
  defaultProviderId = "spike-local",
  instructions,
  onBind,
  onInstructions,
  locale = lang,
}: {
  specialist: Specialist;
  providers: ProviderInfo[];
  boundProviderId: string;
  defaultProviderId?: string;
  instructions: string;
  onBind: (providerId: string) => void;
  onInstructions: (value: string) => void;
  locale?: "es" | "en";
}) {
  const S = dicts[locale].specialistStatus;
  const isAccepted =
    Boolean(s.adapter) &&
    s.adapter_status === "evaluated" &&
    s.adapter_accepted === true;

  const catalogBadge = !s.adapter || s.adapter_status === "none"
    ? S.noAdapter
    : s.adapter_status === "evaluated"
      ? (isAccepted ? S.evaluatedAccepted : S.evaluatedPending)
      : S[s.adapter_status] ?? s.adapter_status;

  const effectivePid = boundProviderId || s.active_provider || defaultProviderId;
  const effectiveProvider = providers.find((p) => p.id === effectivePid);
  const supportsAdapters =
    effectiveProvider?.capabilities_effective?.adapters === true ||
    (effectivePid === s.active_provider && s.provider_supports_adapters === true);
  const loadedOnEffective =
    Boolean(s.adapter) &&
    supportsAdapters &&
    ((s.loaded_on_providers ?? []).includes(effectivePid) ||
      (effectivePid === (s.active_provider || defaultProviderId) &&
        s.active_mode === "adapter_loaded"));

  const activeModeText = loadedOnEffective
    ? S.modeAdapterLoaded
    : S.modeInstructionProfile;

  const hasBase = s.layers?.base_instructions ?? true;
  const hasUser = Boolean(instructions.trim()) || s.layers?.user_instructions === true;
  const hasLearned = s.layers?.learned_instructions === true;
  const knowledgeCount = s.layers?.knowledge_count ?? 0;

  return (
    <div className="card specialist-card" data-specialist={s.id}>
      <div className="card-head">
        <span className={`chip spec-${s.id}`}>
          <SpecMark id={s.id} />
          {s.name}
        </span>
        <span className="muted small">{s.domain}</span>
        <span
          className={`badge ${isAccepted ? "ok" : ""}`}
          data-testid={`catalog-status-${s.id}`}
        >
          {S.catalogLabel}: {catalogBadge}
        </span>
      </div>
      <p className="small muted">{s.description}</p>
      <div className="row small" data-testid={`active-mode-${s.id}`}>
        <span>
          <b>{S.modeLabel}:</b> {activeModeText}
        </span>
      </div>
      <div className="row small" data-testid={`active-layers-${s.id}`}>
        <span className="muted">{S.layersLabel}:</span>
        {hasBase && <span className="badge">{S.layerBase}</span>}
        {hasUser && <span className="badge">{S.layerUser}</span>}
        {hasLearned && <span className="badge">{S.layerLearned}</span>}
        {knowledgeCount > 0 && (
          <span className="badge">
            {S.layerKnowledge} ({knowledgeCount})
          </span>
        )}
      </div>
      {isAccepted && (s.adapter_reasons?.length ?? 0) > 0 && (
        <div className="small muted" data-testid={`adapter-receipt-${s.id}`}>
          <b>{S.receiptLabel}:</b> {s.adapter_reasons!.join(" · ")}
        </div>
      )}
      <div className="row">
        <label className="field">
          <span>{S.bind}</span>
          <select
            value={boundProviderId}
            onChange={(e) => onBind(e.target.value)}
          >
            <option value="">{S.inherit}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="field">
        <span>{S.specInstr}</span>
        <textarea
          rows={2}
          defaultValue={instructions}
          onBlur={(e) =>
            e.target.value !== instructions && onInstructions(e.target.value)
          }
        />
      </label>
    </div>
  );
}
