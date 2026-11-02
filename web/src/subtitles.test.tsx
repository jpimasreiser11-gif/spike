import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { SubtitleStudio } from "./components/SubtitleStudio";
import { t } from "./i18n";

let host: HTMLDivElement, root: Root;
const cues = [{ start_ms: 0, end_ms: 1000, text: "Hola mundo" }];
const close = vi.fn();
beforeEach(async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  vi.spyOn(api, "get").mockResolvedValue({ enabled: true, whisper: true, ffmpeg: true, ffprobe: true, max_seconds: 600 });
  vi.spyOn(api, "post").mockResolvedValue({ cues });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<SubtitleStudio onClose={close} />));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); close.mockClear(); });
function setInput(selector: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(selector)!;
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true })); });
}
it("opening only checks availability; transcription needs an explicit approval", async () => {
  expect(api.post).not.toHaveBeenCalled();
  setInput('[name="media-path"]', "clip.wav");
  const run = host.querySelector<HTMLButtonElement>('[data-testid="subtitle-transcribe"]')!;
  expect(run.disabled).toBe(true);
  act(() => host.querySelector<HTMLInputElement>('[name="approve-media"]')!.click());
  await act(async () => run.click());
  expect(api.post).toHaveBeenCalledWith('/api/subtitles/transcribe', expect.objectContaining({ path: 'clip.wav', approved: true }));
  expect(host.querySelector('textarea')?.value).toBe('Hola mundo');
});
it("changing the source revokes the previous approval", () => {
  act(() => host.querySelector<HTMLInputElement>('[name="approve-media"]')!.click());
  setInput('[name="media-path"]', 'other.mp4');
  expect(host.querySelector<HTMLInputElement>('[name="approve-media"]')!.checked).toBe(false);
});
it("keeps imported text editable without binaries and warns before discarding", async () => {
  const file = new File(['1\n00:00:00,000 --> 00:00:01,000\nHola mundo\n'], 'test.srt');
  Object.defineProperty(file, 'text', { value: async () => 'subtitle fixture' });
  const upload = host.querySelector<HTMLInputElement>('[name="subtitle-import"]')!;
  Object.defineProperty(upload, 'files', { value: [file], configurable: true });
  await act(async () => upload.dispatchEvent(new Event('change', { bubbles: true })));
  expect(host.querySelector('textarea')).not.toBeNull();
  await act(async () => host.querySelector<HTMLButtonElement>('[data-testid="subtitle-close"]')!.click());
  expect(close).not.toHaveBeenCalled();
  expect(host.textContent).toContain(t.subtitles.unsaved);
});
