# ADR 0005: A small MCP client of our own, tested against the official SDK

Status: accepted (2026-10-17).

## Decision

SPIKE speaks the Model Context Protocol with its own client (`spike/connectors/mcp.py`, about 300 lines on
httpx and asyncio): the initialize handshake at protocol revision 2025-11-25, `tools/list` with pagination and
`tools/call`, over stdio and Streamable HTTP (JSON or event-stream answers, `Mcp-Session-Id`,
`MCP-Protocol-Version`). Requests a server sends to the client are answered (`ping`) or refused (sampling,
elicitation, roots). The official Python SDK (`mcp`, MIT) is a **development** dependency only: it builds the
server the tests run against (`tests/fixtures/mcp_test_server.py`), over both transports.

## Why

- SPIKE uses MCP for tools only. The official SDK 2.3.0 pulls about fifteen packages into every install
  (among them `cryptography` through `pyjwt[crypto]`, `starlette`, `sse-starlette`, `opentelemetry-api`), which
  works against the light install on 16 GB machines that SPIKE targets.
- Interoperability is checked against the reference implementation instead of our own reading of the spec:
  `tests/test_mcp_client.py` runs the SDK's server over stdio and Streamable HTTP.
- Revision 2025-11-25 is the newest one the SDK still reaches through the initialize handshake; servers
  negotiate down to an older revision when they need to.

## Consequences

- New protocol features (resources, prompts, sampling, the 2026-07-28 revision) need code here; the SDK would
  bring them for free. Revisit if SPIKE starts using more than tools.
- Server processes get only the environment they need to start (PATH, home, temp, proxy and CA settings) plus
  the connector's own secrets, never SPIKE's API token or provider keys (tested).
