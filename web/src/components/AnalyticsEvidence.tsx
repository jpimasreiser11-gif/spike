import { lang, t } from "../i18n";
import type { AnalyticsEvidenceData } from "../types";

/** Keep the original result alongside its repair history, bounded SQL plan and comparable forecast scores. */
export function AnalyticsEvidence({ ui }: { ui: AnalyticsEvidenceData }) {
  const d = t.analytics;
  if (!ui.lineage?.length && !ui.guardian?.sql && !ui.backtest?.length) return null;
  return (
    <details className="analytics-evidence">
      <summary>{d.evidence}</summary>
      {ui.guardian?.sql && <section>
        <b>{d.guardian}</b>
        <p>{ui.guardian.explanation?.[lang]}</p>
        <pre className="data-output">{ui.guardian.sql}</pre>
      </section>}
      {ui.backtest?.length && <section>
        <b>{d.backtest}</b>
        <p>{d.selected}: {d.methods[ui.forecast?.method ?? ""] ?? ui.forecast?.method}</p>
        <p className="muted small">{d.baseline}</p>
        <div className="data-grid"><table>
          <thead><tr><th>{d.method}</th><th>{d.mae}</th><th>{d.folds}</th></tr></thead>
          <tbody>{ui.backtest.map((row) => <tr key={row.method}>
            <td>{d.methods[row.method] ?? row.method}</td><td>{row.mae}</td><td>{row.folds}</td>
          </tr>)}</tbody>
        </table></div>
      </section>}
      {ui.lineage?.length && <section>
        <b>{d.lineage}</b>
        <ol>{ui.lineage.map((step) => <li key={step.step}>
          {d.steps[step.operation] ?? step.operation}
          {step.report && <>
            <p>{d.before}: {step.report.before.rows} {d.rows}, {step.report.before.columns} {d.columns}
              {" → "}{d.after}: {step.report.after.rows} {d.rows}, {step.report.after.columns} {d.columns}</p>
            <ul>{step.report.steps.map((fix, i) => <li key={i}>{d.steps[fix.code] ?? fix.code}{fix.count === undefined ? "" : `: ${fix.count}`}</li>)}</ul>
          </>}
          <pre className="data-output">{JSON.stringify(step, null, 2)}</pre>
        </li>)}</ol>
      </section>}
    </details>
  );
}
