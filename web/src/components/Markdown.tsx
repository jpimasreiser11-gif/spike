import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { Marked } from "marked";
import { memo, useEffect, useMemo, useRef } from "react";
import { t } from "../i18n";

for (const [name, lang] of Object.entries({ bash, css, javascript, json, python, rust, sql, typescript, xml, yaml })) {
  hljs.registerLanguage(name, lang);
}
hljs.registerAliases(["sh", "shell", "zsh"], { languageName: "bash" });
hljs.registerAliases(["js", "jsx"], { languageName: "javascript" });
hljs.registerAliases(["ts", "tsx"], { languageName: "typescript" });
hljs.registerAliases(["html"], { languageName: "xml" });
hljs.registerAliases(["py"], { languageName: "python" });

const marked = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    code({ text, lang }) {
      const language = (lang || "").trim().split(/\s+/)[0];
      const valid = language && hljs.getLanguage(language);
      const html = valid ? hljs.highlight(text, { language }).value : hljs.highlightAuto(text).value;
      return `<div class="code-block"><div class="code-head"><span>${valid ? language : ""}</span><button class="code-copy" type="button">${t.copy}</button></div><pre><code class="hljs">${html}</code></pre></div>`;
    },
  },
});

function MarkdownImpl({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const html = useMemo(() => {
    const raw = marked.parse(text, { async: false }) as string;
    return DOMPurify.sanitize(raw, { ADD_ATTR: ["target"] });
  }, [text]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.querySelectorAll("a[href^='http']").forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
    const onClick = (e: Event) => {
      const btn = (e.target as HTMLElement).closest(".code-copy") as HTMLButtonElement | null;
      if (!btn) return;
      const code = btn.closest(".code-block")?.querySelector("code")?.textContent ?? "";
      navigator.clipboard?.writeText(code).then(() => {
        btn.textContent = t.copied;
        setTimeout(() => (btn.textContent = t.copy), 1500);
      });
    };
    el.addEventListener("click", onClick);
    return () => el.removeEventListener("click", onClick);
  }, [html]);

  return <div ref={ref} className="markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}

export const Markdown = memo(MarkdownImpl);
