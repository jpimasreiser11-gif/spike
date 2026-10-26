() => {
  // Original, deterministic checks on the light DOM. This is a partial review, not WCAG certification.
  const issues = [];
  const selector = el => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    while (el && el.nodeType === 1) {
      const tag = el.localName;
      const peers = el.parentElement ? [...el.parentElement.children].filter(e => e.localName === tag) : [];
      parts.unshift(tag + (peers.length > 1 ? `:nth-of-type(${peers.indexOf(el) + 1})` : ''));
      el = el.parentElement;
    }
    return parts.join(' > ');
  };
  const add = (code, el, details = {}) => issues.push({code, selector: selector(el), ...details});
  const rgba = value => {
    const m = value.match(/^rgba?\(([^)]+)\)$/);
    if (!m) return null;
    const n = m[1].split(/[,\s/]+/).map(Number);
    return n.length >= 3 && n.every(Number.isFinite) ? [...n.slice(0, 3), n[3] ?? 1] : null;
  };
  const over = (fg, bg) => fg.slice(0, 3).map((v, i) => v * fg[3] + bg[i] * (1 - fg[3]));
  const luminance = rgb => rgb.map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
    .reduce((v, c, i) => v + c * [0.2126, 0.7152, 0.0722][i], 0);
  const name = el => {
    const refs = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (refs.some(id => document.getElementById(id)?.textContent.trim())) return true;
    if ((el.getAttribute('aria-label') || '').trim() || (el.getAttribute('title') || '').trim()) return true;
    if (el.labels && [...el.labels].some(label => label.textContent.trim())) return true;
    if (el.matches('input[type=button],input[type=submit],input[type=reset]')) return !!el.value.trim();
    if (el.matches('input[type=image]')) return !!el.alt.trim();
    return !el.matches('input,select,textarea') && (!!el.textContent.trim() ||
      [...el.querySelectorAll('img[alt]')].some(img => img.alt.trim()));
  };
  for (const el of document.querySelectorAll('body *')) {
    const style = getComputedStyle(el), rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height || style.visibility !== 'visible' || el.closest('[hidden],[inert]')) continue;
    const chain = [];
    for (let p = el; p; p = p.parentElement) chain.push(getComputedStyle(p));
    if (chain.some(s => s.display === 'none' || Number(s.opacity) === 0)) continue;
    if (el.matches('img') && !el.hasAttribute('alt')) add('alt', el);
    const control = el.matches('button,input:not([type=hidden]),select,textarea,a[href],[role=button],[role=checkbox],[role=switch],[role=textbox]');
    if (control && !name(el)) add('label', el);
    if (control && (rect.width < 24 || rect.height < 24)) add('tap', el, {width: rect.width, height: rect.height});
    if (rect.left < -1 || rect.right > document.documentElement.clientWidth + 1)
      add('overflow', el, {left: rect.left, right: rect.right});
    const hasText = [...el.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
    if (!hasText) continue;
    // Gradients, images, opacity and filters need pixel analysis; never invent a contrast ratio for these.
    if (chain.some(s => s.backgroundImage !== 'none' || Number(s.opacity) !== 1 || s.filter !== 'none') ||
        style.mixBlendMode !== 'normal') { add('contrast_unchecked', el); continue; }
    let bg = [255, 255, 255];
    let valid = true;
    for (const s of [...chain].reverse()) {
      const color = rgba(s.backgroundColor);
      if (!color) { valid = false; break; }
      bg = over(color, bg);
    }
    const fg = rgba(style.color);
    if (!valid || !fg) { add('contrast_unchecked', el); continue; }
    const a = luminance(over(fg, bg)), b = luminance(bg);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const large = parseFloat(style.fontSize) >= 24 ||
      (parseFloat(style.fontSize) >= 18.6667 && parseInt(style.fontWeight, 10) >= 700);
    const required = large ? 3 : 4.5;
    if (ratio < required) add('contrast', el, {ratio, required});
  }
  return {url: location.origin === 'null' ? 'about:blank' : location.origin + location.pathname,
    viewport: {width: innerWidth, height: innerHeight}, issues};
}
