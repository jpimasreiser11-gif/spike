import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { ReverseStudio } from "./components/ReverseStudio";
import { t } from "./i18n";
import * as media from "./media";

let host: HTMLDivElement, root: Root;
const providers = [
  { id: "spike-local", name: "SPIKE local", local: true, vision: false, receives_files: true },
  { id: "openai", name: "OpenAI", local: false, vision: true, receives_files: true },
];
const status = { browser: true, providers, default_provider: "spike-local", statement: "I own this" };
const quote = (over = {}) => ({ id: "q1", sends: "structure", egress: false, blocked: null, estimated_cost: null, source: "url",
  provider: { id: "spike-local", name: "SPIKE local", model: "m", local: true }, ...over });
const result = { html: "<!doctype html><title>Page</title><p>Lorem</p>", title: "Page", filename: "reverse-1.html", path: "reverse/reverse-1.html",
  project_id: null, size: { width: 1280, height: 800 }, authorization: { at: "2026-11-02T10:00:00+00:00", statement: "I own this" },
  removed: { scripts: 1, links: 2, images_and_graphics: 3 }, names_removed: ["Acme Cloud"],
  fidelity: { measured: true, score: 0.8123, width: 1280, height: 800, metric: "m", against: "page" } };
let post: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  vi.spyOn(api, "get").mockImplementation(async (path: string) => (path === "/api/reverse" ? status : []) as any);
  post = vi.fn(async (path: string) => (path.endsWith("preview") ? quote() : result));
  vi.spyOn(api, "post").mockImplementation(post as any);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<ReverseStudio />));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); });

const generate = () => host.querySelector<HTMLButtonElement>('[data-testid="reverse-generate"]')!;
const box = () => host.querySelector<HTMLInputElement>('[name="reverse-authorized"]')!;
function setValue(el: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  act(() => { Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value); el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); });
}
const choose = (kind: "image" | "url" | "file") =>
  act(() => Array.from(host.querySelectorAll<HTMLInputElement>('input[name="reverse-source"]'))[["image", "url", "file"].indexOf(kind)].click());

it("nothing happens until the ownership box is ticked, and the confirmation is sent with the request", async () => {
  expect(generate().disabled).toBe(true);
  await act(async () => generate().click());
  expect(post).not.toHaveBeenCalled();
  act(() => box().click());
  expect(generate().disabled).toBe(false);
  await act(async () => generate().click());
  expect(post).toHaveBeenNthCalledWith(1, "/api/reverse/preview", expect.objectContaining({ authorized: true, source: "url", url: "http://localhost:5173/" }));
  expect(post).toHaveBeenNthCalledWith(2, "/api/reverse/generate", { preview_id: "q1" }); // a local model: nothing leaves, no extra click
  expect(host.querySelector('[data-testid="reverse-score"]')!.textContent).toContain("0.8123");
  expect(host.textContent).toContain("reverse/reverse-1.html");
});

it("changing the reference revokes the confirmation", () => {
  act(() => box().click());
  expect(box().checked).toBe(true);
  setValue(host.querySelector<HTMLInputElement>('[name="reverse-url"]')!, "http://localhost:3000/");
  expect(box().checked).toBe(false);
  expect(generate().disabled).toBe(true);
});

it("an image for a provider without vision says it needs vision or a URL and cannot be sent", async () => {
  vi.spyOn(media, "resizeImage").mockResolvedValue("data:image/jpeg;base64,/9j/AAA=");
  choose("image");
  expect(host.querySelector('[data-testid="reverse-needs-vision"]')!.textContent).toBe(t.reverse.needsVision);
  const file = new File([new Uint8Array(4)], "shot.png", { type: "image/png" });
  const input = host.querySelector<HTMLInputElement>('[data-testid="reverse-image"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  act(() => box().click());
  expect(generate().disabled).toBe(true);
  expect(post).not.toHaveBeenCalled();
  setValue(host.querySelector<HTMLSelectElement>('select[aria-label]')!, "openai"); // a provider with vision
  expect(host.querySelector('[data-testid="reverse-needs-vision"]')).toBeNull();
});

it("an external provider gets the image only after the user has seen where it goes and clicked send", async () => {
  vi.spyOn(media, "resizeImage").mockResolvedValue("data:image/jpeg;base64,/9j/AAA=");
  post.mockImplementation(async (path: string) => (path.endsWith("preview")
    ? quote({ sends: "image", egress: true, provider: { id: "openai", name: "OpenAI", model: "gpt", local: false } }) : result));
  choose("image");
  setValue(host.querySelector<HTMLSelectElement>('select[aria-label]')!, "openai");
  const input = host.querySelector<HTMLInputElement>('[data-testid="reverse-image"]')!;
  Object.defineProperty(input, "files", { value: [new File([new Uint8Array(4)], "shot.png", { type: "image/png" })], configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  act(() => box().click());
  await act(async () => generate().click());
  expect(post).toHaveBeenCalledTimes(1); // the preview only: nothing sent yet
  expect(post).toHaveBeenCalledWith("/api/reverse/preview", expect.objectContaining({ source: "image", provider_id: "openai", image: "data:image/jpeg;base64,/9j/AAA=" }));
  expect(host.querySelector('[data-testid="reverse-confirm"]')!.textContent).toContain("OpenAI (gpt)");
  await act(async () => host.querySelector<HTMLButtonElement>('[data-testid="reverse-send"]')!.click());
  expect(post).toHaveBeenLastCalledWith("/api/reverse/generate", { preview_id: "q1" });
});

it("a blocked preview shows why and never generates", async () => {
  post.mockImplementation(async () => quote({ egress: true, blocked: "images_private" }));
  act(() => box().click());
  await act(async () => generate().click());
  expect(host.querySelector('[role="alert"]')!.textContent).toContain(t.reverse.blocked);
  expect(post).toHaveBeenCalledTimes(1);
});
