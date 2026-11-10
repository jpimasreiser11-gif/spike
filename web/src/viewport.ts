/** On-screen keyboard handling (G41). Chrome on Android resizes the layout viewport itself when the page asks for
 * `interactive-widget=resizes-content` (index.html). iOS Safari ignores that hint and only shrinks the *visual* viewport,
 * so the fixed-height app shell would stay full height and the composer would sit behind the keyboard. This publishes the
 * visual viewport's height as `--vvh` (CSS: `.app { height: var(--vvh, 100%) }`) and keeps the page scrolled to the top so
 * the shell follows the keyboard. Without the VisualViewport API nothing is set and the CSS falls back to 100%. */
export function trackVisualViewport(win: Window = window): () => void {
  const vv = win.visualViewport;
  if (!vv) return () => {};
  const root = win.document.documentElement;
  const update = () => {
    // Only react when the visual viewport is clearly shorter than the layout viewport (a keyboard), not on pinch zoom.
    const keyboard = vv.scale <= 1.01 && win.innerHeight - vv.height > 80;
    if (keyboard) {
      root.style.setProperty("--vvh", `${Math.round(vv.height)}px`);
      root.dataset.keyboard = "";
      if (vv.offsetTop > 0) win.scrollTo(0, 0);
    } else {
      root.style.removeProperty("--vvh");
      delete root.dataset.keyboard;
    }
  };
  vv.addEventListener("resize", update);
  vv.addEventListener("scroll", update);
  update();
  return () => {
    vv.removeEventListener("resize", update);
    vv.removeEventListener("scroll", update);
    root.style.removeProperty("--vvh");
    delete root.dataset.keyboard;
  };
}
