import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { dicts, t } from "./i18n";
import { encodeWav, resizeImage } from "./media";
import { MediaControls } from "./components/MediaControls";

it("encodes mono PCM16 WAV at 16kHz", () => {
  const bytes = encodeWav(new Float32Array([0, 1, -1, 0]), 16000);
  const view = new DataView(bytes);
  expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe("RIFF");
  expect(view.getUint32(24, true)).toBe(16000);
  expect(view.getInt16(46, true)).toBe(32767);
  expect(view.getInt16(48, true)).toBe(-32768);
});

it("rejects non raster files and large inputs before decoding", async () => {
  await expect(resizeImage(new File(["svg"], "x.svg", { type: "image/svg+xml" }))).rejects.toThrow();
  await expect(resizeImage(new File([new Uint8Array(11_000_000)], "x.png", { type: "image/png" }))).rejects.toThrow();
});

it("shrinks images to at most 1536px and uses raster JPEG content parts", async () => {
  const close = vi.fn();
  vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 3000, height: 1500, close })));
  const draw = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: draw, fillRect: vi.fn() } as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,abc");
  expect(await resizeImage(new File(["x"], "x.png", { type: "image/png" }))).toBe("data:image/jpeg;base64,abc");
  expect(draw.mock.calls[0].slice(1)).toEqual([0, 0, 1536, 768]);
  expect(close).toHaveBeenCalled();
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it("has matching translations and never executes speech on opening settings", async () => {
  expect(Object.keys(dicts.es.media).sort()).toEqual(Object.keys(dicts.en.media).sort());
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async (_path: string) => new Response(JSON.stringify({ enabled: false, whisper: false, piper: false,
    whisper_model: "", piper_model: "", piper_license: "", license: "" })));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<MediaControls images={[]} setImages={() => {}} onDictation={() => {}} busy={false} />));
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => host.querySelector<HTMLButtonElement>("[data-voice-settings]")!.click());
  expect(fetcher.mock.calls.map((c) => String(c[0]))).toEqual(["/api/media"]);
  expect(host.textContent).toContain(t.media.missing);
  await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals();
});

it("pastes and drops images locally, removes them, and does not send before submit", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 10, height: 10, close: vi.fn() })));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn(), fillRect: vi.fn() } as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,abc");
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  let images: string[] = [];
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const render = () => root.render(<MediaControls images={images} setImages={(value) => { images = value; render(); }} busy={false} onDictation={() => {}} />);
  await act(async () => render());
  const paste = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(paste, "clipboardData", { value: { files: [new File(["x"], "x.png", { type: "image/png" })] } });
  await act(async () => host.querySelector(".composer")!.dispatchEvent(paste));
  expect(paste.defaultPrevented).toBe(true); expect(images).toHaveLength(1);
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [new File(["x"], "x.png", { type: "image/png" })] } });
  await act(async () => host.querySelector(".composer")!.dispatchEvent(drop));
  expect(images).toHaveLength(2); expect(fetcher).not.toHaveBeenCalled();
  await act(async () => host.querySelector<HTMLButtonElement>(`button[aria-label="${t.media.remove} 1"]`)!.click());
  expect(images).toHaveLength(1);
  await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it("shows the voice license before a separate synthesis click", async () => {
  const { VoiceOutput } = await import("./components/VoiceOutput");
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async (_path: string) => new Response(JSON.stringify({ enabled: true, piper: true, license: "CC0-1.0 test voice" })));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  await act(async () => root.render(<VoiceOutput text="Hello" />));
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => host.querySelector("button")!.click());
  expect(host.textContent).toContain("CC0-1.0 test voice");
  expect(fetcher.mock.calls.map((c) => c[0])).toEqual(["/api/media"]);
  await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals();
});

it("sends image-only messages from the composer and clears attachments", async () => {
  const { Composer } = await import("./components/Composer");
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 10, height: 10, close: vi.fn() })));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn(), fillRect: vi.fn() } as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,abc");
  const onSend = vi.fn(), host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  await act(async () => root.render(<Composer onSend={onSend} onStop={() => {}} busy={false} mode="auto" setMode={() => {}}
    providerId={null} setProviderId={() => {}} specialists={[]} providers={[]} followUp={false} />));
  const paste = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(paste, "clipboardData", { value: { files: [new File(["x"], "x.png", { type: "image/png" })] } });
  await act(async () => host.querySelector("textarea")!.dispatchEvent(paste));
  const send = host.querySelector<HTMLButtonElement>(".send-btn")!;
  expect(send.disabled).toBe(false);
  await act(async () => send.click());
  expect(onSend).toHaveBeenCalledWith(t.media.describe, undefined, undefined, ["data:image/jpeg;base64,abc"]);
  expect(host.querySelectorAll("img")).toHaveLength(0);
  await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it("declares vision explicitly without overwriting other provider overrides", async () => {
  const { VisionSetting } = await import("./components/VisionSetting");
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const save = vi.fn(), host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  await act(async () => root.render(<VisionSetting capabilities={{ native_tools: false }} effective={false} save={save} />));
  await act(async () => host.querySelector<HTMLInputElement>("input")!.click());
  expect(save).toHaveBeenCalledWith({ native_tools: false, vision: true });
  await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals();
});

it("stops microphone tracks and closes the audio context on finish or cancel", async () => {
  const { recordWav } = await import("./media");
  const stop = vi.fn(), close = vi.fn(), disconnect = vi.fn();
  const processor = { connect: vi.fn(), disconnect, onaudioprocess: null as ((event: unknown) => void) | null };
  class Context {
    sampleRate = 48000; destination = {};
    createMediaStreamSource() { return { connect: vi.fn(), disconnect }; }
    createScriptProcessor() { return processor; }
    close = close;
  }
  vi.stubGlobal("AudioContext", Context);
  const getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop }] }));
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  const recorder = await recordWav();
  processor.onaudioprocess!({ inputBuffer: { getChannelData: () => new Float32Array(4800) } });
  const blob = await recorder.stop();
  expect(blob.type).toBe("audio/wav"); expect(blob.size).toBe(44 + 1600 * 2);
  expect(stop).toHaveBeenCalledTimes(1); expect(close).toHaveBeenCalledTimes(1);
  recorder.cancel(); expect(stop).toHaveBeenCalledTimes(1);
  vi.unstubAllGlobals();
});

it("generates audio only after license review and releases its object URL", async () => {
  const { VoiceOutput } = await import("./components/VoiceOutput");
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn(async (path: string, _options?: RequestInit) => path.endsWith("/speak") ? new Response(new Uint8Array([1, 2])) :
    new Response(JSON.stringify({ enabled: true, piper: true, license: "CC0-1.0 test" })));
  vi.stubGlobal("fetch", fetcher);
  const revoke = vi.fn(); vi.stubGlobal("URL", { createObjectURL: () => "blob:test", revokeObjectURL: revoke });
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  await act(async () => root.render(<VoiceOutput text="Read me" />));
  await act(async () => host.querySelector("button")!.click());
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => host.querySelector("button")!.click());
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ text: "Read me" });
  expect(host.querySelector("audio")?.src).toBe("blob:test");
  await act(async () => root.unmount()); expect(revoke).toHaveBeenCalledWith("blob:test");
  host.remove(); vi.unstubAllGlobals();
});

it("discards microphone capture after the two minute limit", async () => {
  vi.useFakeTimers(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const stop = vi.fn();
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop }] }) } });
  class Context {
    sampleRate = 48000; destination = {};
    createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn() }; }
    createScriptProcessor() { return { connect: vi.fn(), disconnect: vi.fn() }; }
    close = vi.fn();
  }
  vi.stubGlobal("AudioContext", Context);
  const fetcher = vi.fn(async (_path: string) => new Response(JSON.stringify({ enabled: true, whisper: true, piper: false,
    whisper_model: "model.bin", piper_model: "", piper_license: "", license: "" })));
  vi.stubGlobal("fetch", fetcher);
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  await act(async () => root.render(<MediaControls images={[]} setImages={() => {}} onDictation={() => {}} busy={false} />));
  await act(async () => host.querySelector<HTMLButtonElement>("[data-voice-settings]")!.click());
  const dictate = [...host.querySelectorAll("button")].find((b) => b.textContent === t.media.dictate)!;
  await act(async () => dictate.click());
  expect(host.textContent).toContain(t.media.stop);
  await act(async () => vi.advanceTimersByTime(120_000));
  expect(stop).toHaveBeenCalled(); expect(host.textContent).toContain(t.media.limit);
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals();
});
