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
- Model output is rendered as sanitized Markdown (DOMPurify). The built frontend only calls the local
  `/api/*` endpoints ([audit](docs/audits/2026-10-17-web-bundle-rea.md)).
- Downloads: models are fetched only from allowlisted licenses and verified against the SHA-256 published by
  the Hub.
