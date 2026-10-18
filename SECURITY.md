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
- SPIKE as an MCP server (`POST /mcp`, `spike mcp`): the HTTP endpoint follows the `/v1` rules above (loopback
  only and no `Origin` without the token; bearer token with it). Calls get no memory, no connectors and no chat
  history, and tools that need approval are refused. `spike mcp` over stdio is started by the user's own agent
  and has the same reach as the app's settings on that computer.
- API keys are stored in the OS keychain through `keyring`; if no keychain is available SPIKE falls back to a
  file readable only by the current user (mode 0600, **not encrypted**) and the UI says which backend is active.
  Keys are never written to the SQLite database or returned by the API.
- Paid providers cannot be called until the user enables `allow_paid` for that provider.
- Every provider call goes through one guard (`spike/providers/guard.py`). A remote provider gets the contents of
  your files only if you enable "send your files' contents" for it (off by default): file passages that memory
  recalled, results of `read_file`, of `recall` hits from files and of file connectors (filesystem, git, GitHub,
  Claude Code), and answers a model wrote after reading your files (in the same run or earlier in the chat) are
  replaced by a notice before the request is built. A test checks the requests on the wire. Not covered: text you
  type or paste yourself, the output of the `python` tool (you approve each script) and custom connectors.
  Optional monthly limits per provider (tokens, or spend at the prices you enter) stop calls before they are
  sent, and every call is written to a local call log (provider, model, tokens, files sent or withheld, status;
  Settings → Privacy), kept 400 days.
- Tools: file tools are confined to the workspace directory; `write_file`, `python` and `web_fetch` ask for
  permission by default. `web_fetch` refuses private, loopback and link-local addresses and redirects.
  The Python tool runs in a separate process with CPU, memory (Linux) and time limits but **without network
  isolation**; treat "allow always" for it as granting code execution on your machine.
- Connectors (MCP servers): enabling a stdio connector runs its command on your computer (the app shows the exact
  command first; catalog entries pin a reviewed version). Their tools ask for permission by default. A server
  process receives only the variables it needs to start plus its own secrets, never SPIKE's token or provider
  keys. Connector secrets are stored like provider keys and never returned by the API.
- The browser connector (Playwright) is checked call by call, whatever its permission setting: a domain you have
  not allowed asks before it opens, a blocked one is refused, and submitting a form, accepting a dialog,
  uploading files or running code in a page asks every time; nobody can approve those for the `/v1` API or the
  MCP server, so they are refused there. Your domain rules live in SPIKE's settings. Blocked domains are also
  passed to the browser when it starts, which Playwright MCP says is not a security boundary, and the browser
  runs with an isolated profile (no saved logins); the page snapshots it saves go to the workspace folder
  `.playwright-mcp/`.
- Forge runs a blueprint only after you approve it, and its steps save files through the same file tools and
  permission prompts as any chat. `spike forge eval` runs its checks as Python in a subprocess with CPU and memory
  limits, in a temporary folder per task, and some checks import the module the model wrote; during the eval the
  file tools and `python` run without asking and `web_fetch` is refused.
- `spike dev` works only inside the folder you start it on (paths outside are refused, symlinks resolved). Edits and commands ask first, showing the diff or the command; `--accept-edits` lets edits through, never commands. Edits can be undone with `/undo`; what a command does cannot, and a command runs with your user's rights, not in a sandbox, so read it before allowing it. `-p` and input that is not a terminal refuse every ask. Started on your home folder or a disk root it warns first.
- Imported design systems are text: `DESIGN.md` and `tokens.css` up to 64 KB each (zips up to 4 MB, no paths outside the archive). Tokens may only hold CSS custom properties: `@import`, `url(`, `</style`, `expression(` and `javascript:` are refused, so a pasted token block cannot load anything or break out of a page's style. Their preview runs in the artifacts sandbox, and imported names are escaped.
- Real exchange orders (Spike Finance) are off by default. Turning them on needs an exchange, a list of markets, a per-order and a 24-hour limit, and your confirmation that the API key cannot withdraw funds (on Binance SPIKE asks the exchange and refuses a key that can); the exchange's test network is the default. A model can only propose an order: the chat shows it and nothing is sent until you click Confirm and then "Yes, send it", after the settings and limits are checked again; a proposal expires after 10 minutes and a second click cannot send it twice. The tool that proposes is never offered to `/v1` or MCP callers. Exchange keys go to the key store like provider keys and are never returned by the API; keys and real-order settings can only be changed, and orders confirmed, from a browser on the computer SPIKE runs on (not from another machine or another site). Backtests and paper trading use public prices only.
- MCP Apps: a connector's view (HTML its server wrote) runs in an iframe with `sandbox="allow-scripts"` and no `allow-same-origin`, so it has an opaque origin: it cannot read SPIKE's storage or cookies, call SPIKE's API (its CSP blocks it too) or touch the app's window. Its CSP only allows the public https/wss origins the server declared (shown above the view); localhost, IP addresses, `.local` names and plain http are dropped. It gets no camera, microphone, location or clipboard. SPIKE serves only views that a tool of that connector declared. A view can call only tools of its own connector that allow it, under each tool's permission (an "ask" tool waits for your click in the card); opening a link asks first; a chat message from a view is put in the text box for you to send; context a view gives goes to the model once, marked as data. Every call is written to `$SPIKE_HOME/connectors/apps-audit.jsonl`. A view can still show misleading content, so it always appears inside a SPIKE frame naming its connector.
- Project files are served as downloads (`application/octet-stream`, `Content-Security-Policy: sandbox`), so an
  uploaded HTML file cannot run with the app's origin. Imported project archives are checked for unsafe paths
  and size before anything is written.
- Artifacts (HTML or SVG a model wrote) run in an iframe with `sandbox="allow-scripts"` and no
  `allow-same-origin`, so they get an opaque origin: no access to the app's storage, cookies or window, no forms,
  popups or top navigation. A Content-Security-Policy placed before the page's markup allows only inline code and
  `data:`/`blob:` media (`connect-src 'none'`), and the server refuses requests with `Origin: null` when it runs with
  its host allow-list (`spike serve`). Document tools ask before writing, stay inside the workspace, and refuse
  spreadsheet formulas that reach outside the file (DDE, `WEBSERVICE`, `CALL`, …).
- Before `write_file` or a document tool changes a file, SPIKE keeps a copy in `$SPIKE_HOME/checkpoints` (files up to
  100 MB, kept 30 days, deleted with their chat) so the step can be undone; those copies are your files' contents,
  stored unencrypted like the rest of `$SPIKE_HOME`. Undo never overwrites a file you edited afterwards without a
  second confirmation. Changes made by the `python` tool or by connectors are not copied.
- Memory lives in `$SPIKE_HOME/memory.db` on your computer. Deleting a memory removes its text, word index and
  vectors, and SQLite's `secure_delete` overwrites the freed pages. The `remember` tool asks before saving, so a
  page the model read cannot plant a note silently; notes are given to the model as information, and only rules
  you wrote are presented as instructions. Rules come only from your own typed message: "recuerda que…" /
  "a partir de ahora…" saves at once (shown on the answer, with undo), and a correction only becomes a rule when
  you press "Guardar regla"; file contents, tool results and web pages never create one. Chat summaries are only
  made with a local model, and the `/v1` API and the MCP server never receive your memory.
- Temporary chats live in an in-memory database: their messages are never written to disk and vanish when SPIKE
  stops. They neither read nor write memory. The spending log still records each call's token counts (no text),
  and files a tool writes are ordinary files.
- Evolution keeps what it learns in `$SPIKE_HOME/evolution.db`: corrections you saved (question, wrong answer,
  rule), retries with another specialist, failures (error text, specialists, SPIKE version and platform) and
  proposed eval questions. Nothing in it is sent anywhere; "Copiar como issue" only puts text on your clipboard
  and leaves your question out. Temporary chats and the "Aprender de mi uso" switch turned off record nothing. A
  learned router is used only after it passes its check, and an adapter is installed only if its measured eval
  results pass its acceptance rule; both roll back from Settings → Evolución or `spike evolve rollback`.
- Model output is rendered as sanitized Markdown (DOMPurify). The built frontend only calls the local
  `/api/*` endpoints ([audit](docs/audits/2026-10-17-web-bundle-rea.md)).
- Downloads: models are fetched only from allowlisted licenses and verified against the SHA-256 published by
  the Hub.
