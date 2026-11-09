import { useEffect, useRef } from "react";

/** When a view or dialog closes, give focus back to what had it when it opened, unless focus moved somewhere else. */
export function useRestoreFocus() {
  const previous = useRef(typeof document !== "undefined" && document.activeElement instanceof HTMLElement ? document.activeElement : null);
  useEffect(() => {
    const prev = previous.current;
    return () => { if (prev?.isConnected && (!document.activeElement || document.activeElement === document.body)) prev.focus(); };
  }, []);
}
