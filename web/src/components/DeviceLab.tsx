import { useContext, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { projectError, t } from "../i18n";
import type { DeviceLabAndroid, DeviceLabUi } from "../types";
import { ArtifactContext } from "./Artifact";
import { PNG_URL, deviceLabDocument, profileName, reasonLines, summaryText } from "./DeviceLabCard";
export { DeviceLabCard, deviceLabDocument, profileName, reasonLines } from "./DeviceLabCard";
import "./DeviceLab.css";

const D = t.deviceLab;

type Custom = { name: string; width: number; height: number; scale: number; touch: boolean; mobile: boolean };
type Info = { profiles: { id: string; name: string; width: number; height: number }[]; limits: { custom: number }; browser: boolean; adb: boolean };
type AndroidList = { found: boolean; devices: { serial: string; state: string; model: string; kind: string; usable: boolean }[]; error: string };

const hostList = (text: string) => text.split(/[\s,]+/).map(h => h.trim()).filter(Boolean);

/** Test a local web app in device profiles. Running anything asks first: one approval for the browser, another for adb. */
export function DeviceLab({ onClose }: { onClose: () => void }) {
  const open = useContext(ArtifactContext);
  const dialog = useRef<HTMLDialogElement>(null), alive = useRef(true);
  const [info, setInfo] = useState<Info | null>(null), [phones, setPhones] = useState<AndroidList | null>(null);
  const [url, setUrl] = useState("http://localhost:5173/"), [hosts, setHosts] = useState("");
  const [chosen, setChosen] = useState<string[]>([]), [customs, setCustoms] = useState<Custom[]>([]);
  const [draft, setDraft] = useState({ name: "", width: "390", height: "844", scale: "3", touch: true });
  const [approved, setApproved] = useState(false), [phoneApproved, setPhoneApproved] = useState(false);
  const [serial, setSerial] = useState(""), [openOnPhone, setOpenOnPhone] = useState(true);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [report, setReport] = useState<DeviceLabUi | null>(null), [shot, setShot] = useState<DeviceLabAndroid | null>(null);
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null;
    const el = dialog.current!; el.showModal();
    api.get<Info>("/api/device-lab").then((i) => {
      if (!alive.current) return;
      setInfo(i); setChosen(i.profiles.map((p) => p.id));
      if (i.adb) api.get<AndroidList>("/api/device-lab/android").then((l) => { if (alive.current) { setPhones(l); setSerial(l.devices.find((d) => d.usable)?.serial ?? ""); } })
        .catch(() => { if (alive.current) setPhones({ found: true, devices: [], error: "adb_failed" }); });
    }).catch(() => { if (alive.current) setError(D.failed); });
    return () => { alive.current = false; el.close(); if (previous?.isConnected) previous.focus(); };
  }, []);
  async function action(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await fn(); } catch (e) { if (alive.current) setError(e instanceof ApiError ? e.message : D.failed); }
    finally { if (alive.current) setBusy(false); }
  }
  const draftOk = (() => {
    const w = Number(draft.width), h = Number(draft.height), s = Number(draft.scale);
    return draft.name.trim().length > 0 && draft.name.trim().length <= 40 && Number.isInteger(w) && w >= 200 && w <= 4000 && Number.isInteger(h) && h >= 200 && h <= 4000 && s >= 1 && s <= 4;
  })();
  const addCustom = () => {
    if (!draftOk || customs.length >= (info?.limits.custom ?? 6)) return;
    setCustoms([...customs, { name: draft.name.trim(), width: Number(draft.width), height: Number(draft.height), scale: Number(draft.scale), touch: draft.touch, mobile: draft.touch }]);
    setDraft({ ...draft, name: "" }); setApproved(false);
  };
  const run = () => action(async () => {
    setReport(null);
    const result = await api.post<DeviceLabUi>("/api/device-lab/run", { url: url.trim(), profiles: chosen, custom: customs, allow_hosts: hostList(hosts), approved: true });
    if (alive.current) setReport(result);
  });
  const capture = () => action(async () => {
    setShot(null);
    const result = await api.post<{ android: DeviceLabAndroid }>("/api/device-lab/android", { url: url.trim(), serial, open_url: openOnPhone, allow_hosts: hostList(hosts), approved: true });
    if (alive.current) { setShot(result.android); setPhoneApproved(false); }
  });
  const download = () => {
    if (!report) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    link.download = "device-lab-report.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  };
  const toggle = (id: string) => { setChosen(chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id]); setApproved(false); };
  const usable = phones?.devices.filter((d) => d.usable) ?? [];
  return (
    <dialog ref={dialog} className="device-lab" aria-labelledby="device-lab-heading" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <header><div><span className="device-lab-eyebrow">SPIKE Dev</span><h2 id="device-lab-heading">{D.title}</h2></div>
        <button className="btn" data-testid="device-lab-close" onClick={onClose}>{D.close}</button></header>
      <p>{D.intro}</p>
      <section aria-label={D.url}>
        <label>{D.url}<input name="device-lab-url" type="url" value={url} disabled={busy} onChange={(e) => { setUrl(e.target.value); setApproved(false); setPhoneApproved(false); }} /></label>
        <p className="device-lab-hint">{D.urlHint}</p>
        <label>{D.allowHosts}<input name="device-lab-hosts" value={hosts} placeholder="staging.example.test" disabled={busy} onChange={(e) => { setHosts(e.target.value); setApproved(false); setPhoneApproved(false); }} /></label>
        <p className="device-lab-hint">{D.allowHostsHint}</p>
      </section>
      <section aria-label={D.profiles}><h3>{D.profiles}</h3>
        <div className="device-lab-profiles">{info?.profiles.map((p) => <label key={p.id} className="device-lab-check">
          <input type="checkbox" name={`profile-${p.id}`} checked={chosen.includes(p.id)} disabled={busy} onChange={() => toggle(p.id)} />{D.names[p.id] ?? p.name} <small>{p.width} × {p.height}</small></label>)}
          {customs.map((c, i) => <span key={i} className="device-lab-check">{c.name} <small>{c.width} × {c.height} @{c.scale}×{c.touch ? ` · ${D.touch.toLowerCase()}` : ""}</small>
            <button type="button" className="btn small" aria-label={`${D.removeCustom} ${c.name}`} disabled={busy} onClick={() => { setCustoms(customs.filter((_, j) => j !== i)); setApproved(false); }}>{D.removeCustom}</button></span>)}</div>
        <fieldset className="device-lab-custom"><legend>{D.customTitle}</legend>
          <label>{D.customName}<input name="custom-name" maxLength={40} value={draft.name} disabled={busy} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label>{D.width}<input name="custom-width" type="number" min={200} max={4000} value={draft.width} disabled={busy} onChange={(e) => setDraft({ ...draft, width: e.target.value })} /></label>
          <label>{D.height}<input name="custom-height" type="number" min={200} max={4000} value={draft.height} disabled={busy} onChange={(e) => setDraft({ ...draft, height: e.target.value })} /></label>
          <label>{D.scale}<input name="custom-scale" type="number" min={1} max={4} step={0.5} value={draft.scale} disabled={busy} onChange={(e) => setDraft({ ...draft, scale: e.target.value })} /></label>
          <label className="device-lab-check"><input type="checkbox" name="custom-touch" checked={draft.touch} disabled={busy} onChange={(e) => setDraft({ ...draft, touch: e.target.checked })} />{D.touch}</label>
          <button type="button" className="btn" data-testid="device-lab-add" disabled={busy || !draftOk || customs.length >= (info?.limits.custom ?? 6)} onClick={addCustom}>{D.addCustom}</button>
          {draft.name.trim() && !draftOk && <p className="device-lab-hint" role="note">{D.customInvalid}</p>}
        </fieldset>
      </section>
      <label className="device-lab-check device-lab-approve"><input name="device-lab-approve" type="checkbox" checked={approved} disabled={busy} onChange={(e) => setApproved(e.target.checked)} />{D.approve}</label>
      <button className="btn primary" data-testid="device-lab-run" disabled={busy || !approved || !url.trim() || !(chosen.length || customs.length) || info?.browser === false} onClick={() => void run()}>{D.run}</button>
      <p role="status" aria-live="polite">{busy ? D.running : ""}</p>
      {error && <p className="notice error" role="alert">{projectError(error)}</p>}
      {report && <section aria-label={D.results} data-testid="device-lab-results"><h3>{D.results}</h3>
        <p><b>{summaryText(report)}</b> · {report.browser}</p>
        <div className="device-lab-table"><table><thead><tr><th>{D.profile}</th><th>{D.screen}</th><th>{D.verdict}</th><th>{D.reason}</th></tr></thead><tbody>
          {report.profiles.map((p) => <tr key={p.id} data-status={p.status}><td>{profileName(p)}</td><td>{p.viewport.width} × {p.viewport.height}</td><td>{D.statuses[p.status] ?? p.status}</td><td>{reasonLines(p).join("; ")}</td></tr>)}
        </tbody></table></div>
        <p className="device-lab-hint">{D.emulated}</p>
        <div className="device-lab-actions">
          <button className="btn primary" data-testid="device-lab-open" disabled={!open} onClick={() => { open?.(deviceLabDocument(report)); onClose(); }}>{D.openReport}</button>
          <button className="btn" onClick={download}>{D.downloadJson}</button></div>
      </section>}
      <section aria-label={D.androidTitle}><h3>{D.androidTitle}</h3>
        {info && !info.adb && <p>{D.androidNone}</p>}
        {info?.adb && phones && !usable.length && <p>{phones.error ? D.androidFail : D.androidEmpty}</p>}
        {info?.adb && usable.length > 0 && <>
          <label>{D.androidDevice}<select name="android-device" value={serial} disabled={busy} onChange={(e) => { setSerial(e.target.value); setPhoneApproved(false); }}>
            {phones!.devices.map((d) => <option key={d.serial} value={d.serial} disabled={!d.usable}>{d.model || d.serial} ({d.serial}, {D.device[d.state] ?? d.state})</option>)}</select></label>
          <label className="device-lab-check"><input type="checkbox" name="android-open" checked={openOnPhone} disabled={busy} onChange={(e) => setOpenOnPhone(e.target.checked)} />{D.androidOpen}</label>
          <label className="device-lab-check device-lab-approve"><input type="checkbox" name="android-approve" checked={phoneApproved} disabled={busy} onChange={(e) => setPhoneApproved(e.target.checked)} />{D.androidApprove}</label>
          <button className="btn" data-testid="device-lab-android-shot" disabled={busy || !phoneApproved || !serial || !url.trim()} onClick={() => void capture()}>{D.androidShot}</button>
          <p className="device-lab-hint">{D.androidNote}</p></>}
        {shot && <div data-testid="device-lab-android-result"><p>{D.androidStatuses[shot.status] ?? shot.status}{shot.steps.length > 0 && `: ${shot.steps.map((s) => `${D.steps[s.step] ?? s.step} ${s.ok ? "✓" : "✕"}`).join(" · ")}`}</p>
          {PNG_URL.test(shot.screenshot) && <img className="device-lab-shot" alt={D.androidImage} src={shot.screenshot} />}</div>}
      </section>
    </dialog>
  );
}
