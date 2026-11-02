import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { ArtifactPanel } from './components/Artifact';
import { api } from './api';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.restoreAllMocks());

it('accepts drafts only from its iframe, reviews outside it, and writes only on explicit approval', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({ token: 'receipt', changes: [{ row: 0, column: 1, before: '5', after: '12' }] });
  const el = document.createElement('div'); document.body.append(el);
  const root = createRoot(el);
  await act(async () => root.render(<ArtifactPanel doc={{ title: 'Stock', html: '<p>Table</p>', filename: 'app.html', dataAppId: 'session' }} onClose={() => {}} />));
  const data = { type: 'spike-data-edits', edits: [{ row: 0, column: 1, value: '12' }] };
  await act(async () => window.dispatchEvent(new MessageEvent('message', { data, source: window })));
  expect(post).not.toHaveBeenCalled();
  await act(async () => window.dispatchEvent(new MessageEvent('message', { data, source: el.querySelector('iframe')!.contentWindow })));
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith('/api/creator/data-app/session/preview', { edits: data.edits });
  expect(el.textContent).toContain('5 → 12');
  expect(el.querySelector('iframe')?.getAttribute('sandbox')).toBe('allow-scripts');
  const buttons = [...el.querySelectorAll('button')];
  await act(async () => buttons.find(b => b.textContent?.includes('Aprobar escritura') || b.textContent?.includes('Approve write'))!.click());
  expect(post).toHaveBeenLastCalledWith('/api/creator/data-app/session/approve', { token: 'receipt', approved: true });
  await act(async () => root.unmount()); el.remove();
});

it('Creator builds the local app in the selected project and opens it in the artifact panel', async () => {
  const { Creator } = await import('./components/Creator');
  const { ArtifactContext } = await import('./components/Artifact');
  const get = vi.spyOn(api, 'get').mockImplementation(async path => path.includes('templates') ? [{
    id: 'data_app', name: 'Data to app', icon: 'table', description: 'Edit a local table', design: true,
    skills: [], deliverables: ['app.html'], fields: [{ id: 'file', label: 'File', kind: 'file', required: true, default: 'stock.xlsx', placeholder: '' }],
  }] : []);
  const post = vi.spyOn(api, 'post').mockResolvedValue({ id: 'session', html: '<p>Stock</p>', filename: 'app.html', title: 'Stock' });
  const open = vi.fn();
  const el = document.createElement('div'); const root = createRoot(el);
  await act(async () => root.render(<ArtifactContext.Provider value={open}><Creator specialists={[]} providers={[]} designs={[]} projectId="p1" onRun={vi.fn()} onClose={() => {}} /></ArtifactContext.Provider>));
  await act(async () => el.querySelector<HTMLButtonElement>('.template-card')!.click());
  await act(async () => el.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(get).toHaveBeenCalledWith('/api/creator/data-files?project_id=p1');
  expect(post).toHaveBeenCalledWith('/api/creator/data-app', expect.objectContaining({ file: 'stock.xlsx', project_id: 'p1', approved: true }));
  expect(open).toHaveBeenCalledWith(expect.objectContaining({ dataAppId: 'session', html: '<p>Stock</p>' }));
  await act(async () => root.unmount());
});

it('discarding a review and a failed review never write the original', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ token: 'receipt', changes: [{ row: 0, column: 0, before: 'a', after: 'b' }] }).mockRejectedValueOnce(new Error('expired'));
  const el = document.createElement('div'); document.body.append(el); const root = createRoot(el);
  await act(async () => root.render(<ArtifactPanel doc={{ title: 'Stock', html: '', filename: 'app.html', dataAppId: 'session' }} onClose={() => {}} />));
  const data = { type: 'spike-data-edits', edits: [{ row: 0, column: 0, value: 'b' }] };
  const send = () => window.dispatchEvent(new MessageEvent('message', { data, source: el.querySelector('iframe')!.contentWindow }));
  await act(async () => { send(); });
  await act(async () => [...el.querySelectorAll('button')].find(b => /Descartar propuesta|Discard proposal/.test(b.textContent ?? ''))!.click());
  expect(el.textContent).not.toContain('a → b');
  expect(post).toHaveBeenCalledTimes(1);
  await act(async () => { send(); });
  expect(el.querySelector('[role="alert"]')).not.toBeNull();
  expect(post.mock.calls.every(([path]) => path.endsWith('/preview'))).toBe(true);
  await act(async () => root.unmount()); el.remove();
});
