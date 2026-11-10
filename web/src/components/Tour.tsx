import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { useRestoreFocus } from "../useRestoreFocus";
import "./Tour.css";

const T = t.tour;
const STEPS = [
  [T.s1Title, T.s1Body], [T.s2Title, T.s2Body], [T.s3Title, T.s3Body], [T.s4Title, T.s4Body], [T.s5Title, T.s5Body],
];
const FOCUSABLE = "button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)";
export const OPEN_TOUR = "spike:open-tour";

/** Asks the tour to open (Settings and the command palette use this). */
export const openTour = () => window.dispatchEvent(new Event(OPEN_TOUR));

/** The first-use tour (G33). Whether it was seen lives in the server's settings (`onboarding.tour_seen`); it makes no
 * request but those two local reads and one local write. While the first-run setup wizard is on screen it waits. */
export function Tour() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const waitForWizard = () => {
      if (!live) return;
      if (document.querySelector(".setup-backdrop")) timer = setTimeout(waitForWizard, 500);
      else setOpen(true);
    };
    (async () => {
      const settings = await api.get<{ onboarding?: { tour_seen?: boolean } }>("/api/settings").catch(() => null);
      if (!live || !settings || settings.onboarding?.tour_seen !== false) return;
      const setup = await api.get<{ enabled: boolean; complete: boolean }>("/api/setup").catch(() => null);
      if (live) { if (setup?.enabled && !setup.complete) waitForWizard(); else setOpen(true); }
    })();
    const again = () => setOpen(true);
    window.addEventListener(OPEN_TOUR, again);
    return () => { live = false; clearTimeout(timer); window.removeEventListener(OPEN_TOUR, again); };
  }, []);
  const close = useCallback(() => {
    setOpen(false);
    api.put("/api/settings", { onboarding: { tour_seen: true } }).catch(() => {}); // asking again next time is harmless
  }, []);
  return open ? <TourDialog onClose={close} /> : null;
}

function TourDialog({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  const dialog = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const bodyId = useId();
  const last = step === STEPS.length - 1;
  useRestoreFocus();

  useEffect(() => { primary.current?.focus(); }, [step]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab" || !dialog.current) return;
      const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const active = document.activeElement as HTMLElement | null;
      const inside = !!active && dialog.current.contains(active);
      if (!items.length) { e.preventDefault(); return; }
      if (e.shiftKey && (!inside || active === items[0])) { e.preventDefault(); items.at(-1)!.focus(); }
      else if (!e.shiftKey && (!inside || active === items.at(-1))) { e.preventDefault(); items[0].focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="tour-backdrop">
      <div className="tour" ref={dialog} role="dialog" aria-modal="true" aria-label={T.title} aria-describedby={bodyId}>
        <p className="tour-step muted" role="status">{T.step.replace("{n}", String(step + 1)).replace("{total}", String(STEPS.length))}</p>
        <h2>{STEPS[step][0]}</h2>
        <p id={bodyId}>{STEPS[step][1]}</p>
        <div className="row tour-actions">
          <button className="btn" onClick={onClose}>{T.skip}</button>
          <span className="spacer" />
          <button className="btn" disabled={step === 0} onClick={() => setStep(step - 1)}>{T.back}</button>
          <button className="btn primary" ref={primary} onClick={() => (last ? onClose() : setStep(step + 1))}>{last ? T.done : T.next}</button>
        </div>
      </div>
    </div>
  );
}
