import { t } from "./i18n";

/** Strip metadata by decoding and painting a bounded raster; no image leaves the browser before Send. */
export async function resizeImage(file: File): Promise<string> {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 10_000_000) throw new Error(t.media.invalid);
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, 1536 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error(t.media.invalid);
    ctx.fillStyle = "white"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/jpeg", 0.85);
    if (url.length > 2_800_000) throw new Error(t.media.invalid);
    return url;
  } finally { bitmap.close(); }
}

/** Resample mono audio to whisper.cpp's 16kHz PCM16 WAV input, bounded to two minutes. */
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const size = Math.floor(samples.length * 16000 / sampleRate);
  const buffer = new ArrayBuffer(44 + size * 2), view = new DataView(buffer);
  const word = (offset: number, value: string) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  word(0, "RIFF"); view.setUint32(4, 36 + size * 2, true); word(8, "WAVE"); word(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  word(36, "data"); view.setUint32(40, size * 2, true);
  for (let i = 0; i < size; i++) {
    const value = Math.max(-1, Math.min(1, samples[Math.floor(i * sampleRate / 16000)]));
    view.setInt16(44 + i * 2, value * (value < 0 ? 32768 : 32767), true);
  }
  return buffer;
}

export async function base64Audio(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** The browser owns microphone permission. Closing the control stops all tracks and discards the recording. */
export async function recordWav(): Promise<{ stop: () => Promise<Blob>; cancel: () => void }> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  let context: AudioContext;
  try { context = new AudioContext(); } catch (e) { stream.getTracks().forEach((track) => track.stop()); throw e; }
  const source = context.createMediaStreamSource(stream), processor = context.createScriptProcessor(4096, 1, 1);
  const chunks: Float32Array[] = [];
  let length = 0, ended = false;
  processor.onaudioprocess = (event) => {
    if (ended) return;
    const chunk = event.inputBuffer.getChannelData(0);
    const remaining = Math.max(0, context.sampleRate * 120 - length);
    const copy = chunk.slice(0, remaining); chunks.push(copy); length += copy.length;
    if (!remaining) { stream.getTracks().forEach((track) => track.stop()); }
  };
  source.connect(processor); processor.connect(context.destination);
  const cancel = () => {
    if (ended) return;
    ended = true; processor.disconnect(); source.disconnect(); stream.getTracks().forEach((track) => track.stop());
    void context.close();
  };
  return { cancel, stop: async () => {
    cancel();
    const samples = new Float32Array(length); let offset = 0;
    for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
    return new Blob([encodeWav(samples, context.sampleRate)], { type: "audio/wav" });
  } };
}

export type SpeechStatus = { enabled: boolean; whisper_model: string; piper_model: string; piper_license: string;
  whisper: boolean; piper: boolean; license: string };
