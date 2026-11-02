import { describe, expect, it } from 'vitest';

const fsSpec = 'node:' + 'fs';
const { readFileSync } = await (import(/* @vite-ignore */ fsSpec) as Promise<{
  readFileSync(path: string, encoding: string): string;
}>);
const styles = readFileSync('src/styles.css', 'utf-8');

type Vars = Record<string, string>;

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

function extractVars(block: string): Vars {
  const vars: Vars = {};
  const re = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let match: RegExpExecArray | null;
  while ((match = re.exec(block)) !== null) {
    vars[match[1]] = match[2].trim();
  }
  return vars;
}

function findBlock(css: string, headerPattern: RegExp): string {
  const match = headerPattern.exec(css);
  if (!match) return '';
  let depth = 0;
  let start = -1;
  for (let i = match.index; i < css.length; i++) {
    if (css[i] === '{') {
      if (depth === 0) start = i + 1;
      depth++;
    } else if (css[i] === '}') {
      depth--;
      if (depth === 0 && start !== -1) return css.slice(start, i);
    }
  }
  return '';
}

function parseThemes(rawCss: string): { light: Vars; darkExplicit: Vars; darkSystem: Vars; clean: string } {
  const clean = stripComments(rawCss);
  const baseBlock = findBlock(clean, /(?:^|\})\s*:root\s*\{/);
  const mediaDarkOuter = findBlock(clean, /@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)\s*\{/);
  const systemDarkBlock = findBlock(mediaDarkOuter, /:root:not\(\[data-theme="light"\]\)\s*\{/);
  const explicitDarkBlock = findBlock(clean, /:root\[data-theme="dark"\]\s*\{/);

  const base = extractVars(baseBlock);
  const sysOverrides = extractVars(systemDarkBlock);
  const expOverrides = extractVars(explicitDarkBlock);

  return {
    light: { ...base },
    darkExplicit: { ...base, ...expOverrides },
    darkSystem: { ...base, ...sysOverrides },
    clean,
  };
}

function hexToRgb(hex: string): [number, number, number] {
  const raw = hex.trim().replace(/^#/, '');
  const full = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw;
  if (!/^[0-9a-f]{6}$/i.test(full)) {
    throw new Error(`Unsupported color literal: ${hex}`);
  }
  return [
    Number.parseInt(full.slice(0, 2), 16),
    Number.parseInt(full.slice(2, 4), 16),
    Number.parseInt(full.slice(4, 6), 16),
  ];
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  return '#' + [r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('');
}

function resolveColor(expr: string, vars: Vars, depth = 0): string {
  if (depth > 12) throw new Error(`Circular CSS variable resolution: ${expr}`);
  const trimmed = expr.trim();
  if (trimmed.startsWith('#')) return rgbToHex(hexToRgb(trimmed));

  const varMatch = /^var\(\s*(--[a-z0-9-]+)(?:\s*,\s*([^)]+))?\s*\)$/i.exec(trimmed);
  if (varMatch) {
    const val = vars[varMatch[1]] ?? varMatch[2];
    if (!val) throw new Error(`Missing CSS variable: ${varMatch[1]}`);
    return resolveColor(val, vars, depth + 1);
  }

  const mixMatch = /^color-mix\(\s*in\s+srgb\s*,\s*(.+?)\s+(\d+(?:\.\d+)?)%\s*,\s*(.+)\s*\)$/i.exec(trimmed);
  if (mixMatch) {
    const c1 = hexToRgb(resolveColor(mixMatch[1], vars, depth + 1));
    const pct = Number.parseFloat(mixMatch[2]) / 100;
    const c2 = hexToRgb(resolveColor(mixMatch[3], vars, depth + 1));
    return rgbToHex([
      c1[0] * pct + c2[0] * (1 - pct),
      c1[1] * pct + c2[1] * (1 - pct),
      c1[2] * pct + c2[2] * (1 - pct),
    ]);
  }

  throw new Error(`Cannot resolve color expression: ${expr}`);
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(fgHex: string, bgHex: string): number {
  const l1 = relativeLuminance(fgHex);
  const l2 = relativeLuminance(bgHex);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

type Mode = 'light' | 'darkExplicit' | 'darkSystem';

function splitTopLevelRules(css: string): { selector: string; body: string; media?: string }[] {
  const rules: { selector: string; body: string; media?: string }[] = [];
  let i = 0;
  while (i < css.length) {
    while (i < css.length && /\s/.test(css[i])) i++;
    if (i >= css.length) break;
    const brace = css.indexOf('{', i);
    if (brace === -1) break;
    const header = css.slice(i, brace).trim();
    let depth = 1;
    let j = brace + 1;
    while (j < css.length && depth > 0) {
      if (css[j] === '{') depth++;
      else if (css[j] === '}') depth--;
      j++;
    }
    const inner = css.slice(brace + 1, j - 1);
    if (header.startsWith('@media')) {
      for (const nested of splitTopLevelRules(inner)) {
        rules.push({ ...nested, media: header });
      }
    } else if (!header.startsWith('@keyframes')) {
      rules.push({ selector: header, body: inner });
    }
    i = j;
  }
  return rules;
}

function propFromBody(body: string, prop: string): string | undefined {
  const re = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, 'gi');
  let match: RegExpExecArray | null;
  let last: string | undefined;
  while ((match = re.exec(body)) !== null) {
    last = match[1].trim();
  }
  return last;
}

function selectorMatches(ruleSelector: string, target: string, mode: Mode): boolean {
  const parts = ruleSelector.split(',').map((s) => s.trim().replace(/\s+/g, ' '));
  const candidates = [target];
  if (mode === 'darkExplicit') candidates.push(`:root[data-theme="dark"] ${target}`);
  if (mode === 'darkSystem') candidates.push(`:root:not([data-theme="light"]) ${target}`);
  return parts.some((p) => candidates.includes(p));
}

function effectiveProp(cleanCss: string, target: string, prop: string, mode: Mode): string | undefined {
  const rules = splitTopLevelRules(cleanCss);
  let value: string | undefined;
  for (const r of rules) {
    if (r.media) {
      const isDarkMedia = /prefers-color-scheme\s*:\s*dark/i.test(r.media);
      if (!isDarkMedia || mode !== 'darkSystem') continue;
    }
    if (selectorMatches(r.selector, target, mode)) {
      const found = propFromBody(r.body, prop);
      if (found !== undefined) value = found;
    }
  }
  return value;
}

describe('SPIKE stylesheet WCAG 2.1/2.2 AA contrast, focus and motion accessibility', () => {
  const { light, darkExplicit, darkSystem, clean } = parseThemes(styles);
  const modes: [Mode, Vars][] = [
    ['light', light],
    ['darkExplicit', darkExplicit],
    ['darkSystem', darkSystem],
  ];

  it('keeps explicit dark theme and OS prefers-color-scheme dark tokens in exact parity', () => {
    expect(darkSystem).toEqual(darkExplicit);
  });

  it('meets WCAG 2.1 AA (4.5:1) for positive, verified, link and active status selectors in all theme modes', () => {
    const onAccentSoft = [
      '.badge.ok',
      '.badge.status-trained',
      '.badge.status-evaluated',
      '.badge.status-placed',
      '.skill-chip',
      '.flash-box',
      '.trust-chip.ok',
      '.claim-badge.verified',
      '.role-execute',
      '.minds-toggle.on',
    ];
    const onSurface = [
      '.markdown a',
      '.link',
      '.link-btn',
      '.tune-rows li.best',
      '.evo-checks li.ok b',
      '.ok-text',
      '.criteria li.ok > span:first-child',
      '.side-buy',
    ];

    for (const [mode, vars] of modes) {
      for (const sel of onAccentSoft) {
        const fgExpr = effectiveProp(clean, sel, 'color', mode);
        const bgExpr = effectiveProp(clean, sel, 'background', mode) ?? 'var(--accent-soft)';
        expect(fgExpr, `${sel} color in ${mode}`).toBeDefined();
        const ratio = contrastRatio(resolveColor(fgExpr!, vars), resolveColor(bgExpr, vars));
        expect(ratio, `${sel} (${fgExpr} on ${bgExpr}) in ${mode}`).toBeGreaterThanOrEqual(4.5);
      }
      for (const sel of onSurface) {
        const fgExpr = effectiveProp(clean, sel, 'color', mode);
        expect(fgExpr, `${sel} color in ${mode}`).toBeDefined();
        const ratio = contrastRatio(resolveColor(fgExpr!, vars), resolveColor('var(--surface)', vars));
        expect(ratio, `${sel} (${fgExpr} on --surface) in ${mode}`).toBeGreaterThanOrEqual(4.5);
      }
      const flashFg = effectiveProp(clean, '.flash', 'color', mode);
      expect(flashFg).toBeDefined();
      expect(
        contrastRatio(resolveColor(flashFg!, vars), resolveColor('var(--bg)', vars)),
        `.flash in ${mode}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('meets WCAG 2.1 AA (4.5:1) for primary, secondary and muted text across surfaces in light and dark modes', () => {
    const surfaces = ['--bg', '--bg-sidebar', '--surface', '--surface-2', '--code-bg', '--user-bubble', '--accent-soft'];
    const textTokens = ['--text', '--text-2', '--text-3'];
    for (const [mode, vars] of modes) {
      for (const fg of textTokens) {
        for (const bg of surfaces) {
          const ratio = contrastRatio(resolveColor(`var(${fg})`, vars), resolveColor(`var(${bg})`, vars));
          expect(ratio, `${fg} on ${bg} in ${mode}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it('meets WCAG 2.1 AA (4.5:1) for warning, danger and network risk indicators in light and dark modes', () => {
    for (const [mode, vars] of modes) {
      for (const bg of ['var(--bg)', 'var(--surface)', 'var(--surface-2)']) {
        expect(
          contrastRatio(resolveColor('var(--warn)', vars), resolveColor(bg, vars)),
          `--warn on ${bg} in ${mode}`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrastRatio(resolveColor('var(--danger)', vars), resolveColor(bg, vars)),
          `--danger on ${bg} in ${mode}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      for (const [sel, fg] of [
        ['.error-box', 'var(--danger)'],
        ['.warn-box', 'var(--warn)'],
        ['.permission', 'var(--warn)'],
        ['.role-verify', 'var(--warn)'],
      ] as const) {
        const bgExpr = effectiveProp(clean, sel, 'background', mode)!;
        expect(
          contrastRatio(resolveColor(fg, vars), resolveColor(bgExpr, vars)),
          `${sel} in ${mode}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      const netFg = effectiveProp(clean, '.risk-network', 'color', mode)!;
      expect(
        contrastRatio(resolveColor(netFg, vars), resolveColor('var(--surface-2)', vars)),
        `.risk-network in ${mode}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('meets WCAG 2.1 AA (4.5:1) for all highlight.js syntax classes in light, explicit dark and OS dark modes', () => {
    const hlClasses = [
      '.hljs-keyword',
      '.hljs-selector-tag',
      '.hljs-built_in',
      '.hljs-string',
      '.hljs-attr',
      '.hljs-number',
      '.hljs-literal',
      '.hljs-title',
      '.hljs-function',
      '.hljs-type',
      '.hljs-class',
      '.hljs-comment',
    ];
    for (const [mode, vars] of modes) {
      const codeBg = resolveColor('var(--code-bg)', vars);
      for (const cls of hlClasses) {
        const fgExpr = effectiveProp(clean, cls, 'color', mode);
        expect(fgExpr, `${cls} color in ${mode}`).toBeDefined();
        const ratio = contrastRatio(resolveColor(fgExpr!, vars), codeBg);
        expect(ratio, `${cls} (${fgExpr}) on --code-bg in ${mode}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('meets WCAG 2.2 AA (3.0:1) non-text contrast for keyboard focus rings, template icons and dark positive borders', () => {
    for (const [mode, vars] of modes) {
      const outline = effectiveProp(clean, ':focus-visible', 'outline', mode) ?? '';
      const outlineColorExpr = outline.replace(/^\d+px\s+\w+\s+/, '').trim();
      const composerBorder = effectiveProp(clean, '.composer:focus-within', 'border-color', mode)!;
      for (const bg of ['var(--bg)', 'var(--surface)', 'var(--surface-2)', 'var(--accent-soft)']) {
        expect(
          contrastRatio(resolveColor(outlineColorExpr, vars), resolveColor(bg, vars)),
          `:focus-visible outline on ${bg} in ${mode}`,
        ).toBeGreaterThanOrEqual(3.0);
        expect(
          contrastRatio(resolveColor(composerBorder, vars), resolveColor(bg, vars)),
          `.composer:focus-within border on ${bg} in ${mode}`,
        ).toBeGreaterThanOrEqual(3.0);
      }
      const iconFg = effectiveProp(clean, '.template-icon', 'color', mode)!;
      expect(
        contrastRatio(resolveColor(iconFg, vars), resolveColor('var(--accent-soft)', vars)),
        `.template-icon in ${mode}`,
      ).toBeGreaterThanOrEqual(3.0);
    }

    for (const mode of ['darkExplicit', 'darkSystem'] as const) {
      const vars = mode === 'darkExplicit' ? darkExplicit : darkSystem;
      const borderExpr = effectiveProp(clean, '.badge.ok', 'border-color', mode)!;
      const resolvedBorder = resolveColor(borderExpr, vars);
      expect(resolvedBorder).not.toBe(resolveColor('var(--ground)', light));
      expect(
        contrastRatio(resolvedBorder, resolveColor('var(--surface)', vars)),
        `.badge.ok border on dark --surface in ${mode}`,
      ).toBeGreaterThanOrEqual(3.0);
    }
  });

  it('reveals the sidebar conversation delete button on keyboard focus and touch devices', () => {
    const rules = splitTopLevelRules(clean);
    const focusVisibleRule = rules.find(
      (r) =>
        !r.media &&
        propFromBody(r.body, 'opacity') === '1' &&
        (r.selector.includes('.conv:focus-within .conv-del') || r.selector.includes('.conv-del:focus-visible')),
    );
    expect(focusVisibleRule, 'keyboard focus-within / focus-visible rule for .conv-del').toBeDefined();

    const touchRule = rules.find(
      (r) =>
        r.media &&
        /hover\s*:\s*none/i.test(r.media) &&
        r.selector.includes('.conv-del') &&
        propFromBody(r.body, 'opacity') === '1',
    );
    expect(touchRule, '@media (hover: none) rule for .conv-del').toBeDefined();
  });

  it('prevents screen-reader word splitting in .sr-only and disables animations/transitions under prefers-reduced-motion', () => {
    expect(effectiveProp(clean, '.sr-only', 'white-space', 'light')).toBe('nowrap');
    expect(effectiveProp(clean, '.sr-only', 'clip-path', 'light')).toBe('inset(50%)');

    const rules = splitTopLevelRules(clean);
    const cascadedProp = (target: string, prop: string): string | undefined => {
      let val: string | undefined;
      for (const r of rules) {
        if (r.media && !/prefers-reduced-motion\s*:\s*reduce/i.test(r.media)) continue;
        if (r.selector.split(',').map((s) => s.trim().replace(/\s+/g, ' ')).includes(target)) {
          const found = propFromBody(r.body, prop);
          if (found !== undefined) val = found;
        }
      }
      return val;
    };

    for (const sel of ['.welcome-mark', '.trace-item.live .trace-title::after', '.typing .dot', '.modal-backdrop']) {
      expect(cascadedProp(sel, 'animation'), `cascaded reduced-motion animation for ${sel}`).toBe('none');
    }
    for (const sel of ['.sidebar', '.composer', '.msg.user .edit-btn']) {
      expect(cascadedProp(sel, 'transition'), `cascaded reduced-motion transition for ${sel}`).toBe('none');
    }
  });
});
