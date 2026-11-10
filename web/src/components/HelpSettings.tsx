import { t } from "../i18n";
import { shortcutList } from "../shortcuts";
import "./CommandPalette.css";

/** Settings > General: reopen the getting-started tour, and the list of keyboard shortcuts. */
export function HelpSettings({ onTour }: { onTour: () => void }) {
  return (
    <div className="card help-settings">
      <button className="btn" onClick={onTour} title={t.tour.againHint}>{t.tour.again}</button>
      <h3>{t.palette.shortcuts.title}</h3>
      <p className="muted">{t.palette.shortcuts.hint}</p>
      <dl className="shortcut-list">
        {shortcutList().map((s, i) => (
          <div key={i}><dt><kbd>{s.keys}</kbd></dt><dd>{s.what}</dd></div>
        ))}
      </dl>
    </div>
  );
}
