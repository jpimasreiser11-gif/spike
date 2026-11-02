import { useContext } from "react";
import { architectureDocument, cycleRow, fill, geoAccuracy, geoCaption, geoDocument, geoNotes, graphCaption, graphNotes, num, safeSvg, slug, svgImage } from "../explorer";
import { t } from "../i18n";
import type { ArchitectureUi, ExplorerUi, GeoUi } from "../types";
import { ArtifactContext, type ArtifactDoc } from "./Artifact";
import "./Explorer.css";

export const isExplorer = (ui: { kind?: string } | undefined): ui is ExplorerUi => ui?.kind === "geo_map" || ui?.kind === "architecture";

function saveSvg(name: string, svg: string) {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.svg`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The drawing the server made, as an image (it can run nothing), with the buttons to open and save it. */
function Drawing({ svg, title, doc, failed }: { svg: string | null; title: string; doc: ArtifactDoc | null; failed: string }) {
  const open = useContext(ArtifactContext);
  return <>
    {svg ? <img className="explorer-svg" alt={title} src={svgImage(svg)} /> : <p className="muted small" role="alert">{failed}</p>}
    <div className="row">
      <button type="button" className="btn small" disabled={!open || !doc} onClick={() => doc && open?.(doc)}>{t.explorer.openPanel}</button>
      <button type="button" className="btn small" disabled={!svg} onClick={() => svg && saveSvg(slug(title), svg)}>{t.explorer.saveSvg}</button>
    </div>
  </>;
}

/** A map from geo_map: the picture, what was drawn, and the measures of each feature. */
export function GeoCard({ ui }: { ui: GeoUi }) {
  const e = t.explorer;
  const title = ui.title || e.map;
  const svg = safeSvg(ui.svg);
  return <section className="data-card explorer-card" aria-label={title}>
    <header><b>{title}</b><span className="muted small">{geoCaption(ui)}</span></header>
    <Drawing svg={svg} title={title} doc={svg ? geoDocument(ui) : null} failed={ui.svg ? e.unsafe : e.noMap} />
    <p className="muted small">{geoAccuracy(ui)}</p>
    {ui.rows.length > 0 && <details className="explorer-rows">
      <summary>{e.table}</summary>
      <div className="data-grid"><table>
        <thead><tr><th>{e.name}</th><th className="num">{e.pointsCol}</th><th className="num">{e.length}</th><th className="num">{e.perimeter}</th><th className="num">{e.area}</th>{ui.value && <th className="num">{e.value}: {ui.value}</th>}</tr></thead>
        <tbody>{ui.rows.map((r, i) => <tr key={i}><td>{r.name}</td><td className="num">{num(r.points, 0)}</td><td className="num">{num(r.length_km)}</td><td className="num">{num(r.perimeter_km)}</td><td className="num">{num(r.area_km2)}</td>{ui.value && <td className="num">{num(r.value)}</td>}</tr>)}</tbody>
      </table></div>
      {ui.rows_truncated && <p className="muted small">{e.firstRows}</p>}
    </details>}
    {geoNotes(ui).map((n, i) => <p key={i} className="muted small">{n}</p>)}
  </section>;
}

/** The module graph from architecture_graph: the picture, the notes on what it counts and leaves out, and the cycles. */
export function ArchitectureCard({ ui }: { ui: ArchitectureUi }) {
  const e = t.explorer;
  const title = ui.title || e.graph;
  const svg = safeSvg(ui.svg);
  return <section className="data-card explorer-card" aria-label={`${e.graph}: ${title}`}>
    <header><b>{e.graph}: {title}</b><span className="muted small">{graphCaption(ui)}</span></header>
    <Drawing svg={svg} title={title} doc={svg ? architectureDocument(ui) : null} failed={ui.svg ? e.unsafe : e.noGraph} />
    <div className="explorer-cycles">
      <b className="small">{e.cyclesTitle}</b>
      {ui.cycles.length === 0 ? <p className="small">{e.noCycles}</p> : <>
        <p className="small">{fill(e.cyclesLine, { n: ui.stats.cycles, k: ui.stats.in_cycles })}</p>
        <div className="data-grid"><table>
          <thead><tr><th>#</th><th className="num">{e.size}</th><th>{e.path}</th></tr></thead>
          <tbody>{ui.cycles.map((c, i) => <tr key={i}><td className="num">{i + 1}</td><td className="num">{c.size}</td><td><code>{cycleRow(c)}</code></td></tr>)}</tbody>
        </table></div>
      </>}
    </div>
    {graphNotes(ui).map((n, i) => <p key={i} className="muted small">{n}</p>)}
  </section>;
}
