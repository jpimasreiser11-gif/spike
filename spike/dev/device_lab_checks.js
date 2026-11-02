({minTap = 24, minFont = 12, limit = 20} = {}) => {
  // Original, deterministic checks of Device Lab (A21) on the light DOM of the page as laid out for one profile.
  // Geometry only: no model, no network, nothing is changed in the page. Partial by design (no iframes, no shadow DOM).
  const doc = document.documentElement, body = document.body;
  const vw = doc.clientWidth;
  const round = n => Math.round(n * 10) / 10;
  const selector = el => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    while (el && el.nodeType === 1 && el !== doc) {
      const tag = el.localName;
      const peers = el.parentElement ? [...el.parentElement.children].filter(e => e.localName === tag) : [];
      parts.unshift(tag + (peers.length > 1 ? `:nth-of-type(${peers.indexOf(el) + 1})` : ''));
      el = el.parentElement;
    }
    return parts.join(' > ').slice(0, 200);
  };
  const shown = el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility === 'visible' && !el.closest('[hidden],[inert]');
  };
  const all = body ? [...body.querySelectorAll('*')].filter(el => !el.closest('svg') || el.localName === 'svg') : [];

  // Overflow: the document is wider than the viewport. The culprits are the outermost boxes that stick out and are not
  // clipped by an ancestor that fits (a carousel with overflow-x: auto is not a problem). Text that spills out of a box
  // that fits (a long word) has no box of its own: it is the fallback when no box sticks out.
  const scrollW = Math.max(doc.scrollWidth, body ? body.scrollWidth : 0);
  const clipped = el => {
    for (let p = el.parentElement; p && p !== body && p !== doc; p = p.parentElement) {
      if (/hidden|auto|scroll|clip/.test(getComputedStyle(p).overflowX) && p.getBoundingClientRect().right <= vw + 1) return true;
    }
    return false;
  };
  const sticking = new Map();
  for (const el of all) {
    if (el.closest('svg') && el.localName !== 'svg') continue;
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    if (!rect.width || !rect.height || style.position === 'fixed' || style.visibility !== 'visible') continue;
    if (rect.right > vw + 1 && !clipped(el)) sticking.set(el, {right: rect.right, left: rect.left, width: rect.width});
  }
  let culprits = [...sticking.keys()].filter(el => !sticking.has(el.parentElement)).map(el => ({el, kind: 'box', ...sticking.get(el)}));
  if (!culprits.length && scrollW > vw + 1) {
    const spill = new Set(all.filter(el => {
      const rect = el.getBoundingClientRect();
      return rect.width && getComputedStyle(el).overflowX === 'visible' && el.scrollWidth > el.clientWidth + 1 &&
        rect.left + el.scrollWidth > vw + 1 && !clipped(el);
    }));
    culprits = [...spill].filter(el => ![...spill].some(o => o !== el && el.contains(o))).map(el => {
      const rect = el.getBoundingClientRect();
      return {el, kind: 'content', right: rect.left + el.scrollWidth, left: rect.left, width: el.scrollWidth};
    });
  }
  culprits.sort((a, b) => b.right - a.right);

  // Tap targets: controls whose box is smaller than minTap x minTap CSS px. A checkbox or radio counts with its label
  // (the label is what is tapped); a link inside running text is exempt, as in WCAG 2.2's inline exception.
  const CONTROLS = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[onclick],' +
    '[role=button],[role=link],[role=checkbox],[role=radio],[role=switch],[role=tab],[role=menuitem]';
  const name = el => (el.getAttribute('aria-label') || el.getAttribute('title') || el.value && el.type !== 'password' && el.value ||
    el.textContent || el.getAttribute('alt') || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 40);
  const small = [];
  for (const el of body ? body.querySelectorAll(CONTROLS) : []) {
    if (el.disabled || !shown(el)) continue;
    const style = getComputedStyle(el);
    if (el.localName === 'a' && style.display === 'inline' &&
        [...el.parentElement.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim())) continue;
    let rect = el.getBoundingClientRect();
    if (rect.width <= 1 || rect.height <= 1) continue; // visually hidden (a custom checkbox, a skip link)
    let w = rect.width, h = rect.height;
    if (el.matches('input[type=checkbox],input[type=radio]') && el.labels) {
      for (const label of el.labels) { const r = label.getBoundingClientRect(); w = Math.max(w, r.width); h = Math.max(h, r.height); }
    }
    if (w < minTap || h < minTap) small.push({selector: selector(el), tag: el.localName, width: round(w), height: round(h), label: name(el)});
  }

  // Text under minFont px: an element with text of its own (not its children's) rendered smaller than that.
  const tiny = [];
  for (const el of all) {
    if (el.closest('svg') && el.localName !== 'svg') continue;
    const own = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(' ').trim();
    if (!own || /^(script|style|noscript|template|option|title)$/.test(el.localName) || !shown(el)) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < minFont) tiny.push({selector: selector(el), tag: el.localName, font_size: round(size), text: own.replace(/\s+/g, ' ').slice(0, 40)});
  }

  return {
    title: (document.title || '').slice(0, 120),
    viewport: {width: vw, height: doc.clientHeight, inner_width: innerWidth, inner_height: innerHeight, scale: devicePixelRatio},
    document: {width: scrollW, height: Math.max(doc.scrollHeight, body ? body.scrollHeight : 0)},
    viewport_meta: !!document.querySelector('meta[name=viewport]'),
    touch_points: navigator.maxTouchPoints || 0,
    overflow: {px: Math.max(0, scrollW - vw), total: culprits.length, items: culprits.slice(0, limit).map(c => ({
      selector: selector(c.el), tag: c.el.localName, kind: c.kind, left: round(c.left), right: round(c.right), width: round(c.width)}))},
    tap_targets: {total: small.length, items: small.slice(0, limit)},
    small_text: {total: tiny.length, items: tiny.slice(0, limit)},
  };
}
