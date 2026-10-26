import type { ChatEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, extra?: Record<string, string>): Promise<T> {
  const raw = body instanceof Blob;
  const res = await fetch(path, {
    method,
    headers: body === undefined ? extra : { "Content-Type": raw ? "application/octet-stream" : "application/json", ...extra },
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) => request<T>("POST", path, body ?? {}, headers),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  /** Sends a file (Blob) as the raw request body. */
  upload: <T>(method: "PUT" | "POST", path: string, file: Blob) => request<T>(method, path, file),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** Incremental Server-Sent Events parser: feed text chunks, get complete `data:` payloads. */
export class SSEParser {
  private buffer = "";

  feed(chunk: string): ChatEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: ChatEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) >= 0) {
      const block = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (!data) continue;
      try {
        events.push(JSON.parse(data));
      } catch {
        /* ignore malformed block */
      }
    }
    return events;
  }
}

export async function streamChat(
  body: {
    comment_threads?: string[];
    message: string; conversation_id?: string | null; mode: string; provider_id?: string | null; project_id?: string | null;
    replace_from?: string | null; // a user message: it and everything after it are replaced (edit, retry)
    temporary?: boolean; // a new chat kept in memory only, without SPIKE's memory
    response_schema?: object; // answer contract: the answer is JSON following this JSON Schema
  },
  onEvent: (ev: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  return streamPost("/api/chat", body, onEvent, signal);
}

/** POST a JSON body and call `onEvent` for each Server-Sent Event of the response. */
export async function streamPost(path: string, body: unknown, onEvent: (ev: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail));
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const ev of parser.feed(decoder.decode(value, { stream: true }))) onEvent(ev);
  }
}
