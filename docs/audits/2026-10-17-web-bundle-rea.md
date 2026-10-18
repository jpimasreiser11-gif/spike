# Audit: network surface of the built web app (REA)

- Date: 2026-10-17. Tool: [REA](https://github.com/morluto/rea) `rea-agents` 6.5.0 (MIT, official npm package,
  installed locally with `--ignore-scripts`). Target: our own build, `web/dist` (Vite production build),
  main bundle SHA-256 prefix `b4e3765b8487f777`.
- Command: `rea analyze-javascript-application web/dist --format json` (static; the bundle is parsed as
  inert text and never executed).

## Findings

| Kind | Evidence |
|---|---|
| Network endpoints with literal URLs | 9, all same-origin: `/api/chat`, `/api/conversations`, `/api/providers`, `/api/presets`, `/api/runtime`, `/api/settings`, `/api/specialists`, `/api/system`, `/api/tools` |
| Browser storage | one `localStorage` key, `spike-theme` (light/dark preference) |
| Electron / IPC / native addons | none |

Cross-check with `grep -oE "https?://…"` over the bundle: the only absolute URLs are XML/SVG/MathML
namespace URIs and links inside library error messages (React, marked, highlight.js); none is fetched.

## Limitations (from REA)

Static analysis does not prove runtime behaviour; endpoints built from dynamic expressions (for example
`/api/conversations/${id}`) are not listed as literals; unavailable facts are not evidence of absence.
Conclusion supported by this evidence: the frontend talks only to the local SPIKE server; external
providers are called by the backend, only when the user configures them.
