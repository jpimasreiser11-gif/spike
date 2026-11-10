import { expect, it } from "vitest";
import { trackVisualViewport } from "./viewport";

const fsSpec = "node:" + "fs";
const { readFileSync } = await (import(/* @vite-ignore */ fsSpec) as Promise<{ readFileSync(path: string, encoding: string): string }>);

/** G41: the app shell follows the visual viewport while the on-screen keyboard is up. */
function fakeWindow(innerHeight: number) {
  const vv = Object.assign(new EventTarget(), { height: innerHeight, scale: 1, offsetTop: 0 });
  const scrolled: number[][] = [];
  const win = { visualViewport: vv, innerHeight, document, scrollTo: (...a: number[]) => scrolled.push(a) } as unknown as Window;
  return { vv, win, scrolled };
}

it("publishes --vvh and a keyboard flag when the visual viewport shrinks, and clears them again", () => {
  const { vv, win, scrolled } = fakeWindow(800);
  const stop = trackVisualViewport(win);
  const root = document.documentElement;
  expect(root.style.getPropertyValue("--vvh")).toBe("");
  vv.height = 440; vv.offsetTop = 30;
  vv.dispatchEvent(new Event("resize"));
  expect(root.style.getPropertyValue("--vvh")).toBe("440px");
  expect("keyboard" in root.dataset).toBe(true);
  expect(scrolled).toEqual([[0, 0]]);
  vv.height = 800; vv.offsetTop = 0;
  vv.dispatchEvent(new Event("resize"));
  expect(root.style.getPropertyValue("--vvh")).toBe("");
  expect("keyboard" in root.dataset).toBe(false);
  stop();
});

it("ignores pinch zoom and browsers without VisualViewport", () => {
  const { vv, win } = fakeWindow(800);
  const stop = trackVisualViewport(win);
  vv.height = 400; vv.scale = 2;
  vv.dispatchEvent(new Event("resize"));
  expect(document.documentElement.style.getPropertyValue("--vvh")).toBe("");
  stop();
  expect(() => trackVisualViewport({ visualViewport: null } as unknown as Window)()).not.toThrow();
});

it("the viewport meta asks Chrome to resize the layout for the keyboard", () => {
  expect(readFileSync("index.html", "utf-8")).toContain("interactive-widget=resizes-content");
});
