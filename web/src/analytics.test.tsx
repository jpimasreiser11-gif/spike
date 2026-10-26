import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AnalyticsEvidence } from "./components/AnalyticsEvidence";
import { t } from "./i18n";

const evidence = {
  lineage: [{ step: 1, operation: "rescue", report: { before: { rows: 3, columns: 3 }, after: { rows: 2, columns: 2 },
    steps: [{ code: "duplicates", count: 1 }], sha256: "abc123" } }],
  guardian: { sql: "SELECT * FROM sales LIMIT 3", explanation: { en: "Read loaded rows.", es: "Leer filas cargadas." } },
  backtest: [{ method: "naive", mae: 3, folds: 2 }, { method: "drift", mae: 0, folds: 2 }],
  forecast: { method: "drift" },
};

describe("analytics evidence", () => {
  it("shows the plan, rescue before/after, lineage and all backtest scores", () => {
    const html = renderToStaticMarkup(<AnalyticsEvidence ui={evidence} />);
    expect(html).toContain(t.analytics.guardian);
    expect(html).toContain("LIMIT 3");
    expect(html).toContain(t.analytics.before);
    expect(html).toContain(t.analytics.after);
    expect(html).toContain("abc123");
    expect(html).toContain(t.analytics.backtest);
    expect(html).toContain("<td>3</td><td>2</td>");
    expect(html).toContain("<td>0</td><td>2</td>");
    expect(html).toContain(t.analytics.methods.drift);
  });

  it("keeps historical cards working without evidence and escapes data", () => {
    expect(renderToStaticMarkup(<AnalyticsEvidence ui={{}} />)).toBe("");
    const html = renderToStaticMarkup(<AnalyticsEvidence ui={{ guardian: { sql: "<script>", explanation: {} } }} />);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });
});
