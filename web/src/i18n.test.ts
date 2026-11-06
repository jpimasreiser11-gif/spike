import ts from "typescript";
import { describe, expect, it } from "vitest";
import { DESKTOP_STRINGS } from "./desktop";
import { dicts } from "./i18n";

const fsSpec = "node:" + "fs";
const pathSpec = "node:" + "path";
const urlSpec = "node:" + "url";

const fs = await (import(/* @vite-ignore */ fsSpec) as Promise<{
  readdirSync(path: string, options: { withFileTypes: true }): { name: string; isDirectory(): boolean }[];
  readFileSync(path: string, encoding: string): string;
}>);
const path = await (import(/* @vite-ignore */ pathSpec) as Promise<{
  dirname(p: string): string;
  join(...paths: string[]): string;
  relative(from: string, to: string): string;
}>);
const { fileURLToPath } = await (import(/* @vite-ignore */ urlSpec) as Promise<{
  fileURLToPath(url: string): string;
}>);

const SRC_DIR = path.dirname(fileURLToPath(import.meta.url));

/** Technical tokens, brand names, units, and protocol/URI examples that are invariant across languages. */
const ALLOWED_TECHNICAL_LITERALS = new Set([
  "SPIKE",
  "SPIKE Dev",
  "SPIKE Motion ·",
  "Forge",
  "⌘ / Ctrl K",
  ": JSON",
  "SQL",
  "Python",
  "· Godot",
  "whisper.cpp:",
  "· Piper:",
  "· ffmpeg:",
  "· ffprobe:",
  "SHA-256",
  "stdio",
  "Streamable HTTP",
  "ID",
  "· KV",
  ", KV",
  ", ctx",
  "· ctx",
  "GB RAM ·",
  "· Metal",
  "RSS",
  "MB ·",
  "KB",
  "KB ·",
  "GiB",
  "fps ·",
  "boe.es",
  "npx",
  "https://…/mcp",
  "staging.example.test",
  "BTC/USDT, ETH/USDT",
  "http://localhost:5173/",
  "index.html",
  "~/.spike/models/Qwen3.5-4B-Q4_K_M.gguf",
  '{"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}',
]);

const USER_FACING_ATTRS = new Set(["aria-label", "title", "placeholder", "alt"]);

function walkSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkSourceFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.includes(".test.")) out.push(full);
  }
  return out.sort();
}

function extractPlaceholders(text: string): string[] {
  const braces = [...text.matchAll(/\{\{?[a-zA-Z0-9_]+\}?\}/g)].map((m) => m[0]);
  const single = [...text.matchAll(/\{[a-zA-Z0-9_]+\}/g)].map((m) => m[0]);
  const interp = [...text.matchAll(/\$\{[^}]+\}/g)].map((m) => m[0]);
  return [...new Set([...braces, ...single, ...interp])].sort();
}

function compareRuntimeTrees(
  baseLocale: string,
  otherLocale: string,
  a: unknown,
  b: unknown,
  keyPath: string,
  issues: string[],
): void {
  if (typeof a !== typeof b) {
    issues.push(`${keyPath}: type mismatch (${baseLocale}=${typeof a}, ${otherLocale}=${typeof b})`);
    return;
  }
  if (typeof a === "string" && typeof b === "string") {
    if (!a.trim()) issues.push(`${keyPath}: empty string in ${baseLocale}`);
    if (!b.trim()) issues.push(`${keyPath}: empty string in ${otherLocale}`);
    const pa = extractPlaceholders(a);
    const pb = extractPlaceholders(b);
    if (JSON.stringify(pa) !== JSON.stringify(pb)) {
      issues.push(`${keyPath}: placeholder mismatch (${baseLocale}=${JSON.stringify(pa)}, ${otherLocale}=${JSON.stringify(pb)})`);
    }
    return;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) {
      issues.push(`${keyPath}: array length mismatch (${baseLocale}=${a.length}, ${otherLocale}=${b.length})`);
      return;
    }
    for (let i = 0; i < a.length; i++) {
      compareRuntimeTrees(baseLocale, otherLocale, a[i], b[i], `${keyPath}[${i}]`, issues);
    }
    return;
  }
  if (a && b && typeof a === "object" && typeof b === "object") {
    const objA = a as Record<string, unknown>;
    const objB = b as Record<string, unknown>;
    for (const k of Object.keys(objA)) {
      if (!(k in objB)) issues.push(`${keyPath}.${k}: missing in ${otherLocale}`);
    }
    for (const k of Object.keys(objB)) {
      if (!(k in objA)) issues.push(`${keyPath}.${k}: missing in ${baseLocale}`);
    }
    for (const k of Object.keys(objA)) {
      if (k in objB) {
        compareRuntimeTrees(baseLocale, otherLocale, objA[k], objB[k], `${keyPath}.${k}`, issues);
      }
    }
  }
}

function parseObjectNode(node: ts.Node, sf: ts.SourceFile): Map<string, ts.Expression> | null {
  if (ts.isAsExpression(node) || ts.isParenthesizedExpression(node)) return parseObjectNode(node.expression, sf);
  if (!ts.isObjectLiteralExpression(node)) return null;
  const map = new Map<string, ts.Expression>();
  for (const prop of node.properties) {
    if (ts.isPropertyAssignment(prop)) {
      const key = ts.isIdentifier(prop.name) || ts.isStringLiteral(prop.name) ? prop.name.text : prop.name.getText(sf);
      map.set(key, prop.initializer);
    } else if (ts.isShorthandPropertyAssignment(prop)) {
      map.set(prop.name.text, prop.name);
    }
  }
  return map;
}

function extractStringNode(node: ts.Node, sf: ts.SourceFile): string | null {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isTemplateExpression(node)) return node.getText(sf);
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const left = extractStringNode(node.left, sf);
    const right = extractStringNode(node.right, sf);
    if (left !== null && right !== null) return left + right;
  }
  return null;
}

function compareAstObjects(nodeA: ts.Node, nodeB: ts.Node, sf: ts.SourceFile, prefix: string, issues: string[]): void {
  const mapA = parseObjectNode(nodeA, sf);
  const mapB = parseObjectNode(nodeB, sf);
  if (!mapA || !mapB) return;
  for (const k of mapA.keys()) {
    if (!mapB.has(k)) issues.push(`${prefix}.${k}: missing in en`);
  }
  for (const k of mapB.keys()) {
    if (!mapA.has(k)) issues.push(`${prefix}.${k}: missing in es`);
  }
  for (const [k, valA] of mapA.entries()) {
    const valB = mapB.get(k);
    if (!valB) continue;
    const cur = `${prefix}.${k}`;
    const subA = parseObjectNode(valA, sf);
    const subB = parseObjectNode(valB, sf);
    if (subA || subB) {
      if (!subA || !subB) issues.push(`${cur}: object/non-object mismatch`);
      else compareAstObjects(valA, valB, sf, cur, issues);
      continue;
    }
    const strA = extractStringNode(valA, sf);
    const strB = extractStringNode(valB, sf);
    if (strA !== null && strB !== null) {
      if (!strA.trim()) issues.push(`${cur}: empty es string`);
      if (!strB.trim()) issues.push(`${cur}: empty en string`);
      const pa = extractPlaceholders(strA);
      const pb = extractPlaceholders(strB);
      if (JSON.stringify(pa) !== JSON.stringify(pb)) {
        issues.push(`${cur}: placeholder mismatch (es=${JSON.stringify(pa)}, en=${JSON.stringify(pb)})`);
      }
    }
  }
}

describe("G17 full i18n audit", () => {
  it("keeps identical keys, value types and placeholders across all locales in i18n.ts and desktop.ts", () => {
    const issues: string[] = [];
    const locales = Object.keys(dicts) as (keyof typeof dicts)[];
    expect(locales.length).toBeGreaterThanOrEqual(2);
    const base = locales[0];
    for (const other of locales.slice(1)) {
      compareRuntimeTrees(base, other, dicts[base], dicts[other], "i18n", issues);
    }

    const desktopLocales = Object.keys(DESKTOP_STRINGS) as (keyof typeof DESKTOP_STRINGS)[];
    for (const other of desktopLocales.slice(1)) {
      compareRuntimeTrees(desktopLocales[0], other, DESKTOP_STRINGS[desktopLocales[0]], DESKTOP_STRINGS[other], "desktop", issues);
    }

    expect(issues).toEqual([]);
  });

  it("keeps identical keys and placeholders in projectErrors and every inline component dictionary", () => {
    const issues: string[] = [];
    for (const file of walkSourceFiles(SRC_DIR)) {
      const rel = path.relative(SRC_DIR, file).replace(/\\/g, "/");
      const code = fs.readFileSync(file, "utf8");
      const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);

      const visit = (node: ts.Node) => {
        if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === "projectErrors" && node.initializer && ts.isObjectLiteralExpression(node.initializer)) {
          for (const prop of node.initializer.properties) {
            if (!ts.isPropertyAssignment(prop)) continue;
            const key = prop.name.getText(sf);
            const map = parseObjectNode(prop.initializer, sf);
            if (!map || !map.has("es") || !map.has("en")) {
              issues.push(`${rel}:projectErrors[${key}]: missing es or en`);
              continue;
            }
            const esStr = extractStringNode(map.get("es")!, sf);
            const enStr = extractStringNode(map.get("en")!, sf);
            if (!esStr?.trim() || !enStr?.trim()) {
              issues.push(`${rel}:projectErrors[${key}]: empty translation`);
            } else if (JSON.stringify(extractPlaceholders(esStr)) !== JSON.stringify(extractPlaceholders(enStr))) {
              issues.push(`${rel}:projectErrors[${key}]: placeholder mismatch`);
            }
          }
        }
        if (ts.isConditionalExpression(node) && node.condition.getText(sf).includes('lang === "es"')) {
          const line = sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
          compareAstObjects(node.whenTrue, node.whenFalse, sf, `${rel}:${line}`, issues);
        }
        ts.forEachChild(node, visit);
      };
      visit(sf);
    }
    expect(issues).toEqual([]);
  });

  it("leaves no untranslated visible UI literals or user-facing attributes in .tsx components", () => {
    const issues: string[] = [];
    for (const file of walkSourceFiles(SRC_DIR)) {
      if (!file.endsWith(".tsx")) continue;
      const rel = path.relative(SRC_DIR, file).replace(/\\/g, "/");
      const code = fs.readFileSync(file, "utf8");
      const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

      const checkLiteral = (raw: string, kind: string, pos: number) => {
        const text = raw.trim();
        if (!/[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}/.test(text)) return;
        if (ALLOWED_TECHNICAL_LITERALS.has(text)) return;
        const line = sf.getLineAndCharacterOfPosition(pos).line + 1;
        issues.push(`${rel}:${line} [${kind}] -> ${JSON.stringify(text)}`);
      };

      const visit = (node: ts.Node) => {
        if (ts.isJsxText(node)) {
          checkLiteral(node.getText(sf), "jsx-text", node.getStart());
        } else if (ts.isJsxAttribute(node)) {
          const attrName = node.name.getText(sf);
          if (USER_FACING_ATTRS.has(attrName) && node.initializer) {
            if (ts.isStringLiteral(node.initializer)) {
              checkLiteral(node.initializer.text, `attr:${attrName}`, node.initializer.getStart());
            } else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
              const expr = node.initializer.expression;
              if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) {
                checkLiteral(expr.text, `attr:${attrName}`, expr.getStart());
              } else if (ts.isConditionalExpression(expr)) {
                for (const branch of [expr.whenTrue, expr.whenFalse]) {
                  if (ts.isStringLiteral(branch) || ts.isNoSubstitutionTemplateLiteral(branch)) {
                    checkLiteral(branch.text, `attr:${attrName}`, branch.getStart());
                  }
                }
              }
            }
          }
        } else if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
          const expr = node.expression;
          if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) {
            checkLiteral(expr.text, "jsx-expr", expr.getStart());
          } else if (ts.isConditionalExpression(expr)) {
            for (const branch of [expr.whenTrue, expr.whenFalse]) {
              if (ts.isStringLiteral(branch) || ts.isNoSubstitutionTemplateLiteral(branch)) {
                checkLiteral(branch.text, "jsx-ternary", branch.getStart());
              }
            }
          }
        }
        ts.forEachChild(node, visit);
      };
      visit(sf);
    }
    expect(issues).toEqual([]);
  });
});
