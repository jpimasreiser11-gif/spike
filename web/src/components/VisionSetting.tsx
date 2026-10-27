import { t } from "../i18n";

/** A declaration by the owner, never a claim that a real vision model was measured or installed. */
export function VisionSetting({ capabilities = {}, effective, save }: {
  capabilities?: Record<string, unknown>; effective: boolean; save: (caps: Record<string, unknown>) => void;
}) {
  return <label className="check"><input type="checkbox" checked={effective}
    onChange={(e) => save({ ...capabilities, vision: e.target.checked })} />{t.media.vision}
    <small className="hint">{t.media.visionHint}</small></label>;
}
