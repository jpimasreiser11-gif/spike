import { describe, expect, it } from 'vitest';

// G26: views opened on demand stay out of the main bundle. A static (non-type) import from App.tsx or from the chat
// would pull the whole module back into the main chunk, so these guard the split; the browser smoke opens each view.
const fsSpec = 'node:' + 'fs';
const { readFileSync } = await (import(/* @vite-ignore */ fsSpec) as Promise<{
  readFileSync(path: string, encoding: string): string;
}>);

/** The modules a file imports with a value (not `import type`) import statement. */
function valueImports(path: string): string[] {
  const source = readFileSync(path, 'utf-8');
  return [...source.matchAll(/^import\s+(?!type\b)[^;]*?from\s+"([^"]+)"/gms)].map((m) => m[1]);
}

const ON_DEMAND = ['Forge', 'Research', 'Replay', 'DeviceLab', 'HistorySearch', 'WorkspacePanel', 'SetupWizard', 'Desktop',
  'Creator', 'Lab', 'SettingsDialog', 'SubtitleStudio'];

describe('bundle split', () => {
  it('App loads the on-demand views lazily', () => {
    const source = readFileSync('src/App.tsx', 'utf-8');
    const imports = valueImports('src/App.tsx');
    for (const name of ON_DEMAND) {
      expect(imports, name).not.toContain(`./components/${name}`);
      expect(source, name).toContain(`import("./components/${name}")`);
    }
  });

  it('the chat does not import the large modules for their small cards', () => {
    const imports = valueImports('src/components/AssistantMessage.tsx');
    for (const name of ['./Finance', './DeviceLab', './Desktop', './Forge', './Memory']) expect(imports, name).not.toContain(name);
    expect(imports).toEqual(expect.arrayContaining(['./LiveOrderCard', './DeviceLabCard', './DesktopRecordView']));
  });

  it('what the main chunk draws is not styled only by a lazily loaded stylesheet', () => {
    const lazyCss = ['HistorySearch', 'Research', 'SetupWizard', 'DeviceLab', 'ForgeSkills']
      .map((name) => readFileSync(`src/components/${name}.css`, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')).join('\n');
    const classesOf = (css: string) => new Set([...css.matchAll(/\.([a-z][a-z0-9-]*)/g)].map((m) => m[1]));
    const shared = classesOf(readFileSync('src/styles.css', 'utf-8'));
    const classes = new Set([...classesOf(lazyCss)].filter((c) => !shared.has(c)));
    for (const file of ['src/App.tsx', 'src/components/AssistantMessage.tsx', 'src/components/LiveOrderCard.tsx',
      'src/components/DeviceLabCard.tsx', 'src/components/DesktopRecordView.tsx']) {
      // every word of every string literal, so a class chosen in an expression (`a ? "x" : undefined`) counts too
      const used = [...readFileSync(file, 'utf-8').matchAll(/["`]([a-z][a-z0-9 -]*)["`]/g)].flatMap((m) => m[1].split(/\s+/));
      expect([...new Set(used.filter((c) => classes.has(c)))], file).toEqual([]);
    }
  });
});
