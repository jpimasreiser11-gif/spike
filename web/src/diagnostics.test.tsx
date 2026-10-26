import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { ArtifactContext, type ArtifactDoc } from './components/Artifact';
import { DiagnosticCard, diagnosticDocument } from './components/DevDiagnostics';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('developer diagnostic artifacts', () => {
  it('escapes hostile selectors and metadata, includes screenshot and localized limits', () => {
    const doc = diagnosticDocument({ kind: 'dev_diagnostic', report: 'visual', issues: [{ code: 'alt', selector: '<img src=x onerror=alert(1)>' }], screenshot: 'data:image/png;base64,cG5n' });
    const parsed = new DOMParser().parseFromString(doc.html, 'text/html');
    expect(parsed.querySelectorAll('img')).toHaveLength(1);
    expect(parsed.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,cG5n');
    expect(parsed.body.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(parsed.querySelector('script')).toBeNull();
    expect(parsed.body.textContent).toMatch(/WCAG/);
  });
  it('opens the complete report in the artifact panel on click', () => {
    const el = document.createElement('div');
    const root = createRoot(el);
    let opened: ArtifactDoc | null = null;
    act(() => root.render(<ArtifactContext.Provider value={doc => { opened = doc; }}><DiagnosticCard ui={{ kind: 'dev_diagnostic', report: 'dependencies', audits: [{ tool: 'npm', status: 'missing' }], licenses: [] }} /></ArtifactContext.Provider>));
    expect(el.textContent).toMatch(/npm/);
    act(() => el.querySelector('button')!.click());
    expect(opened).not.toBeNull();
    expect(opened!.html).toContain('npm');
    act(() => root.unmount());
  });
});
