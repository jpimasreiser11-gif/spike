import { describe, expect, it } from "vitest";
import { ARTIFACT_CSP, artifactDocument, artifactFromCode } from "./components/Artifact";
import { fileUrl } from "./components/AssistantMessage";

describe("artifacts", () => {
  it("puts the policy in the head before any of the page's markup", () => {
    const doc = artifactDocument("<script>fetch('/api/conversations')</script>");
    const parsed = new DOMParser().parseFromString(doc, "text/html");
    const meta = parsed.head.querySelector('meta[http-equiv="Content-Security-Policy"]');
    expect(meta?.getAttribute("content")).toBe(ARTIFACT_CSP);
    expect(doc.indexOf(ARTIFACT_CSP)).toBeLessThan(doc.indexOf("<script>"));
    expect(ARTIFACT_CSP).toContain("connect-src 'none'");
    expect(ARTIFACT_CSP).toContain("default-src 'none'");
  });
  it("names the artifact after its title", () => {
    expect(artifactFromCode("<title>Informe Q3</title><p>x</p>", "html")).toMatchObject({ title: "Informe Q3", filename: "informe-q3.html" });
    expect(artifactFromCode("<svg></svg>", "svg").filename).toBe("artifact.svg");
  });
  it("builds download URLs per project and escapes each path segment", () => {
    expect(fileUrl("informes/q3 final.docx")).toBe("/api/workspace/files/informes/q3%20final.docx");
    expect(fileUrl("a#b.pdf", "p1")).toBe("/api/projects/p1/files/a%23b.pdf");
  });
});
