import { describe, expect, it } from "vitest";
import { appDocument, contextText, readMessage } from "./components/McpApp";

describe("MCP Apps", () => {
  it("puts SPIKE's policy in a head of its own, before the server's page", () => {
    const doc = appDocument('<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src *"></head><body>hi</body></html>',
      "default-src 'none'; connect-src https://api.example.com");
    const parsed = new DOMParser().parseFromString(doc, "text/html");
    const metas = parsed.head.querySelectorAll('meta[http-equiv="Content-Security-Policy"]');
    expect(metas.length).toBe(1); // the server's own one lands in the body, where browsers ignore it
    expect(metas[0].getAttribute("content")).toBe("default-src 'none'; connect-src https://api.example.com");
    expect(appDocument("x", 'a"b')).toContain('content="a&quot;b"');
  });

  it("accepts only well-formed JSON-RPC from a view", () => {
    expect(readMessage({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "x" } })).not.toBeNull();
    expect(readMessage({ jsonrpc: "2.0", method: "ui/notifications/initialized" })).not.toBeNull();
    expect(readMessage({ jsonrpc: "1.0", id: 1, method: "ping" })).toBeNull();
    expect(readMessage({ jsonrpc: "2.0", id: 1, method: "../evil" })).toBeNull();
    expect(readMessage({ jsonrpc: "2.0", id: {}, method: "ping" })).toBeNull();
    expect(readMessage({ jsonrpc: "2.0", id: 1, method: "ping", params: [1] })).toBeNull();
    expect(readMessage({ jsonrpc: "2.0" })).toBeNull();
    expect(readMessage("not an object")).toBeNull();
    expect(readMessage({ jsonrpc: "2.0", id: 1, method: "ping", params: { big: "x".repeat(1_000_001) } })).toBeNull();
  });

  it("turns a context update into text for the next message", () => {
    expect(contextText({ content: [{ type: "text", text: "BTC 50.100" }, { type: "image", data: "…" }], structuredContent: { price: 50100 } }))
      .toBe('BTC 50.100\n{"price":50100}');
    expect(contextText(undefined)).toBe("");
    expect(contextText({ content: [{ type: "text", text: "x".repeat(5000) }] }).length).toBe(4000);
  });
});
