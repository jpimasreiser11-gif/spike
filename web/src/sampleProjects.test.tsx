import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { SampleProjects } from './components/SampleProjects';
import { api } from './api';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.restoreAllMocks());

const rows = ['expenses', 'report', 'webpage', 'handbook', 'workflow', 'finance'].map((id) => (
  { id, name: `Sample ${id}`, description: `About ${id}`, feature: 'X', files: 2, bytes: 100 }));

it('lists the samples and imports one with a single click', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue(rows);
  const post = vi.spyOn(api, 'post').mockResolvedValue({ id: 'p1', name: 'Sample finance' });
  const onImported = vi.fn();
  const el = document.createElement('div'); document.body.append(el);
  const root = createRoot(el);
  await act(async () => root.render(<SampleProjects onClose={() => {}} onImported={onImported} />));
  expect(get).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/samples\?lang=(es|en)$/));
  const cards = el.querySelectorAll('[data-testid^="sample-"]:not([data-testid^="sample-import"])');
  expect(cards.length).toBe(6);
  await act(async () => (el.querySelector('[data-testid="sample-import-finance"]') as HTMLButtonElement).click());
  expect(post).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/samples\/finance\/import\?lang=(es|en)$/), {});
  expect(onImported).toHaveBeenCalledWith({ id: 'p1', name: 'Sample finance' });
  await act(async () => root.unmount()); el.remove();
});

it('shows the error when the import fails and stays open', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(rows);
  vi.spyOn(api, 'post').mockRejectedValue(new Error('boom'));
  const onImported = vi.fn();
  const el = document.createElement('div'); document.body.append(el);
  const root = createRoot(el);
  await act(async () => root.render(<SampleProjects onClose={() => {}} onImported={onImported} />));
  await act(async () => (el.querySelector('[data-testid="sample-import-expenses"]') as HTMLButtonElement).click());
  expect(onImported).not.toHaveBeenCalled();
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('boom');
  await act(async () => root.unmount()); el.remove();
});
