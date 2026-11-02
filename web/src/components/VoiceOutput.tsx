import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { t } from "../i18n";
import type { SpeechStatus } from "../media";

/** Show the installed voice's license before a separate click runs the local synthesizer. */
export function VoiceOutput({ text }: { text: string }) {
  const [status, setStatus] = useState<SpeechStatus | null>(null), [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const act = async () => {
    setBusy(true); setError("");
    try {
      if (!status) { setStatus(await api.get<SpeechStatus>("/api/media")); return; }
      const response = await fetch("/api/media/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (!response.ok) throw new ApiError(response.status, (await response.json()).detail);
      setUrl(URL.createObjectURL(await response.blob()));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <div className="small">
    <button type="button" className="btn small" disabled={busy || !!status && (!status.enabled || !status.piper || !status.license)}
      onClick={() => void act()}>{status ? t.media.play : t.media.speak}</button>
    {status && <><span>{status.enabled && status.piper && status.license ? t.media.license : t.media.configure}</span>
      {status.license && <pre style={{ maxHeight: 100, overflow: "auto", whiteSpace: "pre-wrap" }}>{status.license}</pre>}</>}
    {url && <audio src={url} controls />}
    {error && <span role="alert">{error}</span>}
  </div>;
}
