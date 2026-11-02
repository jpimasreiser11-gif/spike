(opts) => {
  // Reverse Studio: the structure and computed styles of the visible page, for a model to rebuild. Original code.
  // It never returns the page's text, image sources or links: only how long each text is, and a few names
  // (title, logo labels, copyright) that the server later removes from the answer.
  const W = innerWidth, H = innerHeight, MAX = (opts && opts.maxNodes) || 500;
  const INLINE = new Set(['a', 'span', 'b', 'i', 'em', 'strong', 'small', 'label', 'code', 'abbr', 'sub', 'sup', 'mark',
    'u', 's', 'time', 'cite', 'q', 'kbd', 'img', 'svg']);
  const DEFAULT_DISPLAY = {li: 'list-item', table: 'table', thead: 'table-header-group', tbody: 'table-row-group',
    tfoot: 'table-footer-group', tr: 'table-row', td: 'table-cell', th: 'table-cell', button: 'inline-block',
    input: 'inline-block', select: 'inline-block', textarea: 'inline-block', img: 'inline'};
  const REPLACED = new Set(['img', 'svg', 'video', 'canvas', 'iframe', 'embed', 'object', 'audio', 'input', 'select', 'textarea', 'button']);
  // tags the browser gives a margin or padding by default: an author's zero is said out loud, or it would come back
  const MARGIN = new Set(['body', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'dl', 'blockquote', 'pre', 'figure', 'hr', 'fieldset', 'menu']);
  const PADDING = new Set(['ul', 'ol', 'menu']);
  const MEDIA = new Set(['video', 'canvas', 'iframe', 'embed', 'object', 'audio']);
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'link', 'meta', 'head', 'title', 'base', 'option',
    'optgroup', 'source', 'track', 'br', 'wbr', 'datalist']);
  let count = 0, truncated = false;

  const color = v => {
    if (!v || v === 'transparent' || v === 'rgba(0, 0, 0, 0)') return null;
    const m = /^rgba?\(([^)]+)\)$/.exec(v);
    if (!m) return v.slice(0, 60);
    const n = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (n.length < 3 || n.some(x => !Number.isFinite(x))) return v.slice(0, 60);
    const a = n.length > 3 ? n[3] : 1;
    if (a === 0) return null;
    const h = x => Math.round(x).toString(16).padStart(2, '0');
    return a < 1 ? `rgba(${n[0]},${n[1]},${n[2]},${+a.toFixed(2)})` : '#' + h(n[0]) + h(n[1]) + h(n[2]);
  };
  const zero = v => !v || parseFloat(v) === 0;
  const box4 = (t, r, b, l) => {
    if ([t, r, b, l].every(zero)) return null;
    if (t === r && r === b && b === l) return t;
    if (t === b && r === l) return `${t} ${r}`;
    return `${t} ${r} ${b} ${l}`;
  };
  const styleOf = (el, tag, cs, pcs, parentFlexish) => {
    const s = {};
    const put = (k, v) => { if (v !== undefined && v !== null && v !== '') s[k] = v; };
    const d = cs.display;
    const dflt = DEFAULT_DISPLAY[tag] || (INLINE.has(tag) ? 'inline' : 'block');
    if (d !== dflt) put('display', d);
    if (cs.position !== 'static') {
      put('position', cs.position);
      for (const k of ['top', 'right', 'bottom', 'left']) if (cs[k] !== 'auto') put(k, cs[k]);
    }
    if (cs.zIndex !== 'auto') put('z-index', cs.zIndex);
    if (d.includes('flex')) {
      if (cs.flexDirection !== 'row') put('flex-direction', cs.flexDirection);
      if (cs.flexWrap !== 'nowrap') put('flex-wrap', cs.flexWrap);
      if (cs.justifyContent !== 'normal') put('justify-content', cs.justifyContent);
      if (cs.alignItems !== 'normal') put('align-items', cs.alignItems);
    }
    if (d.includes('flex') || d.includes('grid')) {
      const rg = cs.rowGap, cg = cs.columnGap;
      if (rg !== 'normal' || cg !== 'normal') put('gap', rg === cg ? rg : `${rg} ${cg}`);
    }
    if (d.includes('grid') && cs.gridTemplateColumns !== 'none') put('grid-template-columns', cs.gridTemplateColumns.slice(0, 120));
    if (parentFlexish) {
      if (cs.flexGrow !== '0') put('flex-grow', cs.flexGrow);
      if (cs.flexShrink !== '1') put('flex-shrink', cs.flexShrink);
      if (cs.flexBasis !== 'auto') put('flex-basis', cs.flexBasis);
      if (cs.alignSelf !== 'auto') put('align-self', cs.alignSelf);
    }
    put('padding', box4(cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft) || (PADDING.has(tag) ? '0' : null));
    put('margin', box4(cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft) || (MARGIN.has(tag) ? '0' : null));
    if ((tag === 'ul' && cs.listStyleType !== 'disc') || (tag === 'ol' && cs.listStyleType !== 'decimal')) put('list-style-type', cs.listStyleType);
    const sides = ['Top', 'Right', 'Bottom', 'Left'].map(x => [cs['border' + x + 'Width'], cs['border' + x + 'Style'], color(cs['border' + x + 'Color'])]);
    const drawn = sides.map(x => parseFloat(x[0]) > 0 && x[1] !== 'none');
    if (drawn.every(Boolean) && sides.every(x => x.join() === sides[0].join())) {
      put('border', `${sides[0][0]} ${sides[0][1]} ${sides[0][2] || 'transparent'}`);
    } else {
      ['top', 'right', 'bottom', 'left'].forEach((n, i) => { if (drawn[i]) put('border-' + n, `${sides[i][0]} ${sides[i][1]} ${sides[i][2] || 'transparent'}`); });
    }
    if (!zero(cs.borderTopLeftRadius) || !zero(cs.borderTopRightRadius) || !zero(cs.borderBottomRightRadius) || !zero(cs.borderBottomLeftRadius)) put('border-radius', cs.borderRadius || cs.borderTopLeftRadius);
    put('background-color', color(cs.backgroundColor));
    const bi = cs.backgroundImage;
    if (bi && bi !== 'none') put('background-image', /gradient/.test(bi) ? bi.replace(/url\([^)]*\)/g, 'image').slice(0, 200) : 'image');
    if (cs.boxShadow !== 'none') put('box-shadow', cs.boxShadow.slice(0, 120));
    if (cs.opacity !== '1') put('opacity', cs.opacity);
    if (!REPLACED.has(tag) && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible')) put('overflow', cs.overflowX === cs.overflowY ? cs.overflowX : `${cs.overflowX} ${cs.overflowY}`);
    // inherited text properties: only what differs from the parent
    const same = k => !pcs || cs[k] === pcs[k];
    if (!same('color')) put('color', color(cs.color));
    if (!same('fontFamily')) put('font-family', cs.fontFamily.slice(0, 200));
    if (!same('fontSize')) put('font-size', cs.fontSize);
    if (!same('fontWeight')) put('font-weight', cs.fontWeight);
    if (!same('fontStyle')) put('font-style', cs.fontStyle);
    if (!same('lineHeight')) put('line-height', cs.lineHeight);
    if (!same('letterSpacing')) put('letter-spacing', cs.letterSpacing);
    if (!same('textAlign')) put('text-align', cs.textAlign);
    if (!same('textTransform')) put('text-transform', cs.textTransform);
    if (!same('textDecorationLine') && cs.textDecorationLine !== 'none') put('text-decoration', cs.textDecorationLine);
    return s;
  };

  const walk = (el, pcs, parentFlexish, out) => {
    if (count >= MAX) { truncated = true; return; }
    const tag = el.localName;
    if (SKIP.has(tag)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    if (cs.display === 'contents') { for (const c of el.children) walk(c, cs, false, out); return; }
    const r = el.getBoundingClientRect();
    if (r.width <= 0 && r.height <= 0) return;
    if (r.bottom <= 0 || r.top >= H || r.right <= 0 || r.left >= W) return;
    count++;
    const node = {t: tag, r: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      s: styleOf(el, tag, cs, pcs, parentFlexish)};
    if (tag === 'img' || tag === 'picture') node.k = 'img';
    else if (tag === 'svg') node.k = 'svg';
    else if (MEDIA.has(tag)) node.k = 'media';
    else if (tag === 'input') node.k = 'input:' + (el.type || 'text');
    else if (tag === 'textarea') node.k = 'input:textarea';
    else if (tag === 'select') node.k = 'input:select';
    let chars = 0;
    for (const c of el.childNodes) if (c.nodeType === 3) chars += c.nodeValue.replace(/\s+/g, ' ').trim().length;
    if (tag === 'input' || tag === 'textarea') chars = (el.placeholder || el.value || '').length;
    if (tag === 'select' && el.selectedOptions[0]) chars = el.selectedOptions[0].text.trim().length;
    if (chars) node.c = chars;
    if (!node.k) {
      const flexish = /flex|grid/.test(cs.display);
      const kids = [];
      for (const c of el.children) walk(c, cs, flexish, kids);
      if (kids.length) node.n = kids;
    }
    out.push(node);
  };

  const roots = [];
  walk(document.body, getComputedStyle(document.documentElement), false, roots);
  const html = getComputedStyle(document.documentElement);
  const page = color(html.backgroundColor) || color(getComputedStyle(document.body).backgroundColor) || '#ffffff';

  // names the page uses for itself; the server removes them from what the model writes
  const names = new Set();
  const add = v => { v = (v || '').replace(/\s+/g, ' ').trim(); if (v.length >= 3 && v.length <= 60) names.add(v); };
  (document.title || '').split(/\s+[|\-–—·•:]\s+|\s*[|•·]\s*/).forEach(add);
  for (const m of document.querySelectorAll('meta[property="og:site_name"],meta[name="application-name"],meta[name="apple-mobile-web-app-title"],meta[name="author"]')) add(m.content);
  for (const el of document.querySelectorAll('img[alt],img[title]')) { add(el.getAttribute('alt')); add(el.getAttribute('title')); }
  const logoish = /logo|brand|wordmark|site-?name|marca/i;
  for (const el of document.querySelectorAll('[class],[id],[src],[href]')) {
    const probe = (typeof el.className === 'string' ? el.className : '') + ' ' + el.id + ' ' + (el.getAttribute('src') || '') + ' ' + (el.getAttribute('href') || '');
    if (!logoish.test(probe)) continue;
    add(el.getAttribute('alt')); add(el.getAttribute('aria-label')); add(el.getAttribute('title'));
    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (text.length <= 60) add(text);
  }
  for (const el of document.querySelectorAll('svg[aria-label],svg title')) add(el.getAttribute('aria-label') || el.textContent);
  const home = document.querySelector('a[rel~="home"]');
  if (home) add(home.textContent);
  const body = (document.body.innerText || '').slice(0, 20000);
  for (const m of body.matchAll(/©\s*(?:\d{4}(?:\s*[-–]\s*\d{4})?\s*)?([^.|\n©]{2,50})/g)) add(m[1]);

  return {viewport: {width: W, height: H}, page, nodes: count, truncated, root: roots[0] || null, names: [...names].slice(0, 40)};
}
