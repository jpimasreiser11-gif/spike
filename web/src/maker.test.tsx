import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ArtifactContext, type ArtifactDoc } from './components/Artifact';
import { BlenderCard, GodotCard, MakerCard, blenderDocument, godotDocument } from './components/Maker';
import { dicts, t } from './i18n';
import type { BlenderUi, GodotUi } from './types';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const blender: BlenderUi = { kind: 'blender_render', script: 'blender/vase.py', preview: 'blender/vase.preview.png', width: 640, height: 360,
  engine: 'Cycles (CPU)', samples: 32, seconds: 4.2, bytes: 1234, version: '4.2.0', log: 'Blender 4.2.0\n<b>log</b>' };
const godot: GodotUi = { kind: 'godot_check', project: 'games/runner', passed: false, version: '4.2.1.stable', scripts: 2, not_checked: 1, seconds: 3.1,
  checks: [{ kind: 'script', name: 'player.gd', ok: false, problems: ['SCRIPT ERROR: Parse Error: <img src=x onerror=alert(1)>'] },
    { kind: 'scene', name: 'main.tscn', ok: true, problems: [] }] };
const PNG = 'data:image/png;base64,cG5n';

const mount = (node: React.ReactNode) => {
  const el = document.createElement('div');
  const root = createRoot(el);
  act(() => root.render(node));
  return { el, unmount: () => act(() => root.unmount()) };
};
const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)); });

afterEach(() => vi.unstubAllGlobals());

describe('Blender preview in the artifacts panel', () => {
  it('shows the picture and escapes everything the script and Blender printed', () => {
    const doc = blenderDocument(blender, PNG, 'print("<script>alert(1)</script>")');
    const parsed = new DOMParser().parseFromString(doc.html, 'text/html');
    expect(parsed.querySelector('img')?.getAttribute('src')).toBe(PNG);
    expect(parsed.querySelector('script')).toBeNull();
    expect(parsed.body.textContent).toContain('print("<script>alert(1)</script>")');
    expect(parsed.body.textContent).toContain('<b>log</b>');
    expect(parsed.querySelector('pre b')).toBeNull();
    expect(parsed.body.textContent).toContain('640×360');
    expect(doc.title).toBe(t.maker.blender);
    expect(doc.filename).toBe('vase-preview.html');
  });
  it('uses nothing but a PNG data URL as the picture', () => {
    for (const bad of ['javascript:alert(1)', 'https://example.com/x.png', 'data:text/html;base64,PHNjcmlwdD4=', PNG + '"onerror="x', '']) {
      expect(new DOMParser().parseFromString(blenderDocument(blender, bad, '').html, 'text/html').querySelector('img')).toBeNull();
    }
  });
  it('fetches the preview and the script from the workspace on click and opens them in the panel', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url);
      return url.endsWith('.png') ? new Response(new Uint8Array([137, 80, 78, 71]), { status: 200 }) : new Response('import bpy\n', { status: 200 });
    }));
    let opened: ArtifactDoc | null = null;
    const view = mount(<ArtifactContext.Provider value={doc => { opened = doc; }}><BlenderCard ui={blender} projectId="p1" /></ArtifactContext.Provider>);
    expect(view.el.querySelector('img')?.getAttribute('src')).toBe('/api/projects/p1/files/blender/vase.preview.png');
    expect(view.el.textContent).toContain('Cycles (CPU)');
    await act(async () => { view.el.querySelector('button')!.click(); });
    await flush();
    expect(urls).toEqual(['/api/projects/p1/files/blender/vase.preview.png', '/api/projects/p1/files/blender/vase.py']);
    expect(opened).not.toBeNull();
    expect(opened!.html).toMatch(/<img alt="[^"]*" src="data:image\/png;base64,/);
    expect(opened!.html).toContain('import bpy');
    view.unmount();
  });
  it('uses the workspace route outside a project and says so when the file cannot be opened', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('gone', { status: 404 })));
    let opened: ArtifactDoc | null = null;
    const view = mount(<ArtifactContext.Provider value={doc => { opened = doc; }}><MakerCard ui={blender} /></ArtifactContext.Provider>);
    expect(view.el.querySelector('img')?.getAttribute('src')).toBe('/api/workspace/files/blender/vase.preview.png');
    await act(async () => { view.el.querySelector('button')!.click(); });
    await flush();
    expect(opened).toBeNull();
    expect(view.el.querySelector('[role=alert]')?.textContent).toBe(t.maker.loadError);
    view.unmount();
  });
});

describe('Godot check in the artifacts panel', () => {
  it('lists every check with its errors as escaped text', () => {
    const doc = godotDocument(godot);
    const parsed = new DOMParser().parseFromString(doc.html, 'text/html');
    expect(parsed.querySelector('img')).toBeNull();
    expect(parsed.body.textContent).toContain('SCRIPT ERROR: Parse Error: <img src=x onerror=alert(1)>');
    expect(parsed.querySelectorAll('li')).toHaveLength(2);
    expect(parsed.body.textContent).toContain(t.maker.failed);
    expect(parsed.body.textContent).toContain(`1 ${t.maker.notChecked}`);
    expect(godotDocument({ ...godot, passed: true, not_checked: 0, checks: [godot.checks[1]] }).html).toContain(t.maker.passed);
  });
  it('shows the verdict and the first error of each failed check, and opens the whole result on click', () => {
    let opened: ArtifactDoc | null = null;
    const view = mount(<ArtifactContext.Provider value={doc => { opened = doc; }}><GodotCard ui={godot} /></ArtifactContext.Provider>);
    expect(view.el.textContent).toContain(t.maker.failed);
    expect(view.el.textContent).toContain('player.gd');
    expect(view.el.textContent).not.toContain('main.tscn');
    act(() => view.el.querySelector('button')!.click());
    expect(opened!.html).toContain('main.tscn');
    view.unmount();
    const ok = mount(<ArtifactContext.Provider value={() => {}}><GodotCard ui={{ ...godot, passed: true, checks: [] }} /></ArtifactContext.Provider>);
    expect(ok.el.textContent).toContain(t.maker.passed);
    ok.unmount();
  });
});

describe('Blender and Godot strings', () => {
  it('exist in Spanish and English with the same keys, and the permission reasons are translated', () => {
    const keys = (lang: 'es' | 'en') => Object.keys(dicts[lang].maker).sort();
    expect(keys('es')).toEqual(keys('en'));
    for (const lang of ['es', 'en'] as const) {
      for (const value of Object.values(dicts[lang].maker)) expect(value.length).toBeGreaterThan(0);
      for (const code of ['blender_render', 'godot_check']) expect(dicts[lang].review[code]).toBeTruthy();
    }
    expect(dicts.es.maker.blender).not.toBe(dicts.en.maker.blender);
    expect(dicts.es.review.blender_render).not.toBe(dicts.en.review.blender_render);
  });
});
