import { t } from "./i18n";

const S = t.palette.shortcuts;

/** Cmd on a Mac, Ctrl elsewhere. */
export const modKey = () => (/Mac|iPhone|iPad/i.test(typeof navigator === "undefined" ? "" : navigator.platform || "") ? "⌘" : "Ctrl");

/** The keyboard shortcuts SPIKE really handles (each is checked against the code in helpSettings.test.tsx). */
export function shortcutList(): { keys: string; what: string }[] {
  return [
    { keys: `${modKey()}+K`, what: S.palette },
    { keys: `↑ ↓ ${S.enter} ${S.esc}`, what: S.paletteNav },
    { keys: S.enter, what: S.send },
    { keys: `${S.shift}+${S.enter}`, what: S.newline },
    { keys: S.esc, what: S.stop },
    { keys: S.esc, what: S.close },
    { keys: "← →", what: S.replay },
  ];
}
