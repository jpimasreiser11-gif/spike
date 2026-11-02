import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { buildTimeline, captions, srt, validateContent, localAsset } from '../src/timeline.mjs';
const content = JSON.parse(fs.readFileSync(new URL('../src/content.json', import.meta.url), 'utf8'));

test('ten chapters fill 180 seconds at 30 fps exactly', () => {
  const rows = buildTimeline(content, 'master');
  assert.equal(rows.length, 10);
  assert.equal(rows.at(-1).from + rows.at(-1).frames, 5400);
  assert.equal(new Set(rows.map(r => r.scene.id)).size, 10);
  assert.deepEqual(validateContent(content), []);
});
for (const [variant, frames] of [['promo30', 900], ['promo60', 1800], ['vertical30', 900], ['scene01', 300], ['scene10', 300]]) {
  test(`${variant}: no gaps, no overlap and correct duration`, () => {
    const rows = buildTimeline(content, variant);
    let cursor = 0;
    for (const row of rows) { assert.equal(row.from, cursor); assert.ok(row.frames > 0); cursor += row.frames; }
    assert.equal(cursor, frames);
  });
}
test('unknown variants do not silently produce a different video', () => {
  assert.throws(() => buildTimeline(content, 'wrong'));
});
test('asset paths must be local and portable', () => {
  for (const path of ['https://example.com/video.mp4', '../secrets', '/private', 'C:\\private', 'voice/../secret', 'voice//a.wav']) {
    assert.equal(localAsset(path), false, path);
  }
  assert.equal(localAsset('voice/01-es.wav'), true);
});
test('draft subtitles are ordered and bounded for both languages and variants', () => {
  for (const lang of ['es', 'en']) for (const variant of ['master', 'promo30', 'promo60', 'scene03']) {
    const lines = captions(content, variant, lang);
    let end = 0;
    for (const line of lines) {
      assert.ok(line.from >= end && line.to > line.from);
      assert.ok(line.text.length <= 90);
      end = line.to;
    }
    assert.ok(end <= buildTimeline(content, variant).reduce((n, r) => n + r.frames, 0));
    assert.match(srt(lines, 30), /00:00:00,000 -->/);
  }
});
test('publication preflight refuses missing footage and unreviewed narration', () => {
  const errors = validateContent(content, true);
  assert.ok(errors.some(x => x.includes('license')));
  assert.ok(errors.some(x => x.includes('voice')));
  assert.ok(errors.some(x => x.includes('captions')));
  assert.ok(errors.some(x => x.includes('capture')));
});
test('verified claim requires candidate and evidence; captions and voice cannot overrun', () => {
  const c = structuredClone(content);
  c.scenes[0].status = 'verified';
  c.scenes[0].voice.master = { path: 'voice/01.wav', frames: 99999, reviewed: true };
  assert.ok(validateContent(c).some(x => x.includes('evidence')));
  assert.ok(validateContent(c).some(x => x.includes('duration')));
  c.scenes[0].captions.es = [{ from: 0, to: 99999, text: 'too long' }];
  assert.ok(validateContent(c).some(x => x.includes('captions')));
});
test('invalid source structure, duplicate IDs and remote paths fail', () => {
  for (const change of [c => c.fps = 0, c => c.scenes[1].id = c.scenes[0].id,
    c => c.scenes[0].capture = {path: 'https://evil/a.mp4', kind: 'video', frames: 900, reviewed: true, speed: 1}]) {
    const c = structuredClone(content); change(c); assert.ok(validateContent(c).length > 0);
  }
});

test('promo final preflight checks its own clip narration, not the master track', () => {
  const errors=validateContent(content,true,'promo30');
  assert.ok(errors.some(x=>x.includes('voice: clip')));
  assert.ok(!errors.some(x=>x.includes('voice: master')));
});
test('every chapter points to real inventory IDs and keeps separate clip copy', () => {
  const catalog=JSON.parse(fs.readFileSync(new URL('../../../docs/release/catalog.json',import.meta.url),'utf8'));
  const ids=new Set(catalog.features.map(f=>f.id));
  for(const scene of content.scenes){
    assert.ok(scene.features.length>0&&scene.features.every(id=>ids.has(id)));
    assert.equal(scene.beats.length,3);assert.equal(scene.beatsEn.length,3);
    assert.notEqual(scene.clipNarration.es,scene.narration.es);
  }
});

test('text flags do not count as editorial approval and empty voice copy is rejected', () => {
  const c=structuredClone(content);c.licenseReviewed='false';c.captionsReviewed='false';
  c.scenes[0].narration.es='  ';
  const errors=validateContent(c,true);
  assert.ok(errors.some(x=>x.includes('booleans')));
  assert.ok(errors.some(x=>x.includes('bilingual copy')));
});
