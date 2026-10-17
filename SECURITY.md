# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's security advisory form ("Report a
vulnerability") rather than a public issue. Include steps to reproduce and the affected version. We aim to
acknowledge reports within 7 days.

## Security model

- The server binds to `127.0.0.1` by default. Exposing it on a network gives anyone who can reach it the
  ability to run the configured tools; do not do that without your own authentication in front.
- When bound to a specific address, requests whose `Host` or `Origin` header names anything else are refused
  (403). This stops DNS rebinding and other websites from using SPIKE through the user's browser.
- The OpenAI-compatible API (`/v1`, [integrations](docs/INTEGRATIONS.md)): without `SPIKE_API_TOKEN` only
  programs on the same computer can call it, and requests carrying an `Origin` header (web pages) are refused;
  with it set, every request needs `Authorization: Bearer <token>` (compared in constant time). Tools that
  need approval are refused there instead of waiting, since nobody can answer an approval card through the
  API; the client's own tools are returned to the client and never run by SPIKE.
- API keys are stored in the OS keychain through `keyring`; if no keychain is available SPIKE falls back to a
  file readable only by the current user (mode 0600, **not encrypted**) and the UI says which backend is active.
  Keys are never written to the SQLite database or returned by the API.
- Paid providers cannot be called until the user enables `allow_paid` for that provider.
- Tools: file tools are confined to the workspace directory; `write_file`, `python` and `web_fetch` ask for
  permission by default. `web_fetch` refuses private, loopback and link-local addresses and redirects.
  The Python tool runs in a separate process with CPU, memory (Linux) and time limits but **without network
  isolation**; treat "allow always" for it as granting code execution on your machine.
- Connectors (MCP servers): enabling a stdio connector runs its command on your computer (the app shows the exact
  command first; catalog entries pin a reviewed version). Their tools ask for permission by default. A server
  process receives only the variables it needs to start plus its own secrets, never SPIKE's token or provider
  keys. Connector secrets are stored like provider keys and never returned by the API.
- Project files are served as downloads (`application/octet-stream`, `Content-Security-Policy: sandbox`), so an
  uploaded HTML file cannot run with the app's origin. Imported project archives are checked for unsafe paths
  and size before anything is written.
- Artifacts (HTML or SVG a model wrote) run in an iframe with `sandbox="allow-scripts"` and no
  `allow-same-origin`, so they get an opaque origin: no access to the app's storage, cookies or window, no forms,
  popups or top navigation. A Content-Security-Policy placed before the page's markup allows only inline code and
  `data:`/`blob:` media (`connect-src 'none'`), and the server refuses requests with `Origin: null` when it runs with
  its host allow-list (`spike serve`). Document tools ask before writing, stay inside the workspace, and refuse
  spreadsheet formulas that reach outside the file (DDE, `WEBSERVICE`, `CALL`, …).
- Memory lives in `$SPIKE_HOME/memory.db` on your computer. Deleting a memory removes its text, word index and
  vectors, and SQLite's `secure_delete` overwrites the freed pages. The `remember` tool asks before saving, so a
  page the model read cannot plant a note silently; notes are given to the model as information, and only rules
  you wrote are presented as instructions. Chat summaries are only made with a local model, and the `/v1` API
  never receives your memory.
- Model output is rendered as sanitized Markdown (DOMPurify). The built frontend only calls the local
  `/api/*` endpoints ([audit](docs/audits/2026-10-17-web-bundle-rea.md)).
- Downloads: models are fetched only from allowlisted licenses and verified against the SHA-256 published by
  the Hub.
