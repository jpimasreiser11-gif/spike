import checks from '../../spike/dev/visual_checks.js?raw';
import { afterEach, describe, expect, it, vi } from 'vitest';


function fixture(markup: string) {
  document.body.innerHTML = markup;
  Object.defineProperty(document.documentElement, 'clientWidth', { value: 800, configurable: true });
  const computed = window.getComputedStyle.bind(window);
  vi.stubGlobal('getComputedStyle', (el: Element) => {
    const style = computed(el);
    return new Proxy(style, { get(target, key) {
      const defaults: Record<string, string> = { opacity: '1', backgroundImage: 'none', filter: 'none', mixBlendMode: 'normal', color: 'rgb(0, 0, 0)', fontSize: '16px', fontWeight: '400' };
      return Reflect.get(target, key) || defaults[String(key)] || '';
    } });
  });
  vi.stubGlobal('CSS', { escape: (s: string) => s });
  for (const el of document.querySelectorAll('body *')) {
    const style = (el as HTMLElement).style;
    const left = Number.parseFloat(style.left) || 0;
    const width = Number.parseFloat(style.width) || 100;
    const height = Number.parseFloat(style.height) || 30;
    el.getBoundingClientRect = () => ({ left, right: left + width, width, height, top: 0, bottom: height, x: left, y: 0, toJSON: () => ({}) });
  }
  return (window.eval(`(${checks})`)() as { issues: { code: string; selector: string; ratio?: number; required?: number }[] }).issues;
}

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ''; });

describe('original in-page visual checks on fixture DOM (explicit layout rectangles)', () => {
  it('finds all five planted issue types and ignores correctly named and decorative elements', () => {
    const issues = fixture(`<p id="contrast" style="color:#aaa;background:white">Text</p>
      <img id="photo"><img id="decorative" alt=""><input id="unnamed"><input id="named" aria-label="Name">
      <div id="overflow" style="left:810px"></div>
      <button id="tiny" aria-label="Close" style="width:15px;height:15px"></button>
      <button id="good" style="color:black;background:white">OK</button><div hidden><button id="hidden"></button></div>`);
    for (const [code, selector] of [['contrast', '#contrast'], ['alt', '#photo'], ['label', '#unnamed'], ['overflow', '#overflow'], ['tap', '#tiny']])
      expect(issues).toContainEqual(expect.objectContaining({ code, selector }));
    expect(issues.filter(i => ['#good', '#hidden', '#decorative', '#named'].includes(i.selector))).toEqual([]);
  });
  it('uses WCAG luminance, alpha compositing, large text and labels; marks complex backgrounds unmeasured', () => {
    const issues = fixture(`<div style="background:black"><span id="alpha" style="color:rgba(255,255,255,0.1)">Alpha</span></div>
      <p id="large" style="font-size:24px;color:#aaa;background:white">Large</p>
      <p id="bold" style="font-size:19px;font-weight:700;color:#aaa;background:white">Bold</p>
      <p id="black" style="color:black;background:white">Good</p>
      <div style="background-image:linear-gradient(black,white)"><span id="gradient">Unknown</span></div>
      <label for="with-label">Name</label><input id="with-label">
      <span id="name">Name</span><button id="with-ref" aria-labelledby="name"></button>`);
    expect(issues.find(i => i.selector === '#alpha')?.ratio).toBeCloseTo(1.2, 1);
    expect(issues.find(i => i.selector === '#large')?.required).toBe(3);
    expect(issues.find(i => i.selector === '#bold')?.required).toBe(3);
    expect(issues).toContainEqual({ code: 'contrast_unchecked', selector: '#gradient' });
    expect(issues.filter(i => ['#black', '#with-label', '#with-ref'].includes(i.selector))).toEqual([]);
  });
});
