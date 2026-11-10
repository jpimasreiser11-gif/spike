import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { HelpSettings } from "./components/HelpSettings";
import { t } from "./i18n";

const fsSpec = "node:" + "fs";
const { readFileSync } = await (import(/* @vite-ignore */ fsSpec) as Promise<{ readFileSync(path: string, encoding: string): string }>);

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("lists the shortcuts and has a button that opens the tour again", async () => {
  const onTour = vi.fn();
  const el = document.createElement("div"); document.body.append(el);
  const root = createRoot(el);
  await act(async () => root.render(<HelpSettings onTour={onTour} />));
  expect(el.querySelector("h3")!.textContent).toBe(t.palette.shortcuts.title);
  const rows = [...el.querySelectorAll("dl > div")].map((r) => [r.querySelector("kbd,dt")!.textContent, r.querySelector("dd")!.textContent]);
  expect(rows.length).toBe(7);
  expect(rows[0][1]).toBe(t.palette.shortcuts.palette);
  expect(rows[0][0]).toMatch(/^(Ctrl|⌘)\+?K$/);
  await act(async () => (el.querySelector("button") as HTMLButtonElement).click());
  expect(onTour).toHaveBeenCalledTimes(1);
  expect(el.querySelector("button")!.textContent).toBe(t.tour.again);
  await act(async () => root.unmount()); el.remove();
});

it("only lists shortcuts that the code really handles", () => {
  const read = (p: string) => readFileSync(p, "utf-8");
  expect(read("src/App.tsx")).toMatch(/key\.toLowerCase\(\) !== "k"/);
  const composer = read("src/components/Composer.tsx");
  expect(composer).toMatch(/e\.key === "Enter" && !e\.shiftKey/);
  expect(composer).toMatch(/e\.key === "Escape" && busy/);
  const replay = read("src/components/Replay.tsx");
  expect(replay).toMatch(/"ArrowRight"/);
  expect(replay).toMatch(/"ArrowLeft"/);
  expect(read("src/components/SettingsDialog.tsx")).toMatch(/e\.key === "Escape"/);
  const palette = read("src/components/CommandPalette.tsx");
  for (const k of ["ArrowDown", "ArrowUp", "Enter", "Escape"]) expect(palette).toContain(`"${k}"`);
});
