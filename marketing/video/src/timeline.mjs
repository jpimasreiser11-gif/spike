/** Pure timeline and draft caption helpers. No downloads, provider calls, publication or invented capture evidence. */
export const localAsset = value => typeof value === 'string' && value.length > 0 &&
  !/[:\\?#\x00-\x1f]/.test(value) && !value.startsWith('/') && value.split('/').every(p => p && p !== '.' && p !== '..');
const selections = { promo30: ['01', '05', '10'], promo60: ['01', '02', '04', '05', '07', '10'], vertical30: ['01', '05', '10'] };
export function buildTimeline(content, variant) {
  const ids = variant === 'master' ? content.scenes.map(s => s.id) : selections[variant] ||
    (/^scene(0[1-9]|10)$/.test(variant) ? [variant.slice(5)] : null);
  if (!ids) throw new Error(`Unknown composition: ${variant}`);
  let from = 0;
  return ids.map(id => {
    const scene = content.scenes.find(s => s.id === id);
    if (!scene) throw new Error(`Missing scene: ${id}`);
    const frames = (variant === 'master' ? scene.seconds : 10) * content.fps;
    const row = { scene, from, frames, kind: variant === 'master' ? 'master' : 'clip' };
    from += frames;
    return row;
  });
}
function chunks(text) {
  const words = text.trim().split(/\s+/), result = [];
  let line = '';
  for (const word of words) {
    if (line && (line.length + word.length > 85 || /[.!?;]$/.test(line))) { result.push(line); line = ''; }
    line += (line ? ' ' : '') + word;
  }
  if (line) result.push(line);
  return result;
}
export function captions(content, variant, language) {
  if (!['es', 'en'].includes(language)) throw new Error('Unknown caption language');
  return buildTimeline(content, variant).flatMap(row => {
    const locked = row.scene[row.kind === 'master' ? 'captions' : 'clipCaptions'][language];
    if (locked.length) return locked.map(c => ({ ...c, from: c.from + row.from, to: c.to + row.from }));
    const lines = chunks(row.scene[row.kind === 'master' ? 'narration' : 'clipNarration'][language]);
    const total = lines.reduce((sum, line) => sum + line.length, 0);
    let consumed = 0;
    return lines.map(line => {
      const from = row.from + Math.round(consumed / total * row.frames);
      consumed += line.length;
      return { from, to: row.from + Math.round(consumed / total * row.frames), text: line, draft: true };
    });
  });
}
export function srt(lines, fps) {
  const time = frame => {
    let ms = Math.round(frame / fps * 1000);
    const h = Math.floor(ms / 3600000); ms %= 3600000;
    const m = Math.floor(ms / 60000); ms %= 60000;
    const s = Math.floor(ms / 1000); ms %= 1000;
    return [h,m,s].map(n => String(n).padStart(2,'0')).join(':') + ',' + String(ms).padStart(3,'0');
  };
  return lines.map((line,i) => `${i+1}\n${time(line.from)} --> ${time(line.to)}\n${line.text.replace(/-->/g, '→')}\n`).join('\n');
}
export function validateContent(c, final = false, variant = 'master') {
  const errors = [];
  if (!c || c.version !== 1 || c.fps !== 30 || !Array.isArray(c.scenes) || c.scenes.length !== 10) return ['Invalid version, fps or scenes'];
  if (typeof c.licenseReviewed !== 'boolean' || typeof c.captionsReviewed !== 'boolean') errors.push('review flags must be booleans');
  if (!localAsset(c.brand?.mascot)) errors.push('Invalid mascot asset');
  if (final && !c.licenseReviewed) errors.push('license: eligibility review missing');
  if (final && !c.captionsReviewed) errors.push('captions: timing review missing');
  let required = new Set();
  try { required = new Set(buildTimeline(c, variant).map(row => row.scene.id)); }
  catch { errors.push('Invalid variant or missing scenes'); }
  const seen = new Set();
  for (const scene of c.scenes) {
    if (!scene || typeof scene !== 'object') { errors.push('Invalid scene'); continue; }
    const fail = reason => errors.push(`${scene.id}: ${reason}`);
    if (!/^(0[1-9]|10)$/.test(scene.id) || seen.has(scene.id)) fail('duplicate or invalid id');
    seen.add(scene.id);
    if (!Number.isInteger(scene.seconds) || scene.seconds < 1) fail('invalid duration');
    if (!['vision', 'verified'].includes(scene.status)) fail('invalid claim status');
    if (scene.status === 'verified' && (!/^[a-f0-9]{40}$/.test(c.releaseRevision || '') ||
        !localAsset(scene.evidence?.path) || !/^[a-f0-9]{64}$/.test(scene.evidence?.sha256 || '') || scene.capture?.reviewed !== true)) fail('evidence required for verified claims');
    if (final && required.has(scene.id) && scene.capture?.reviewed !== true) fail('capture: missing reviewed media');
    if (scene.capture && (!localAsset(scene.capture.path) || !['video', 'image'].includes(scene.capture.kind) ||
        typeof scene.capture.reviewed !== 'boolean' ||
        !/^[a-f0-9]{64}$/.test(scene.capture.sha256 || '') || !Number.isFinite(scene.capture.speed) || scene.capture.speed < 1 ||
        (scene.capture.kind === 'video' && (!Number.isInteger(scene.capture.frames) || scene.capture.frames / scene.capture.speed < scene.seconds * c.fps)))) fail('capture path, checksum, speed or duration invalid');
    for (const kind of ['master','clip']) {
      const duration = (kind === 'master' ? scene.seconds : 10) * c.fps;
      const voice = scene.voice?.[kind];
      const needed = final && required.has(scene.id) && kind === (variant === 'master' ? 'master' : 'clip');
      if (needed && voice?.reviewed !== true) fail(`voice: ${kind} audio not reviewed`);
      if (voice && (!localAsset(voice.path) || !Number.isInteger(voice.frames) || voice.frames < 1 || voice.frames > duration ||
                    typeof voice.reviewed !== 'boolean' || !/^[a-f0-9]{64}$/.test(voice.sha256 || ''))) fail('voice path, checksum or duration invalid');
      for (const lang of ['es','en']) {
        const text = scene[kind === 'master' ? 'narration' : 'clipNarration']?.[lang];
        if (typeof scene.title?.[lang] !== 'string' || !scene.title[lang].trim() || typeof text !== 'string' || !text.trim()) fail('missing bilingual copy');
        const lines = scene[kind === 'master' ? 'captions' : 'clipCaptions']?.[lang];
        if (!Array.isArray(lines)) { fail('captions invalid'); continue; }
        if (needed && !lines.length) fail(`captions: ${lang} must have locked timings`);
        let end = 0;
        for (const line of lines) {
          if (!Number.isInteger(line.from) || !Number.isInteger(line.to) || line.from < end || line.to <= line.from ||
              line.to > duration || typeof line.text !== 'string' || !line.text.trim() || line.text.length > 90) fail('captions invalid or outside duration');
          end = line.to;
        }
      }
    }
  }
  if (c.scenes.reduce((n,s) => n+(s?.seconds || 0),0) !== 180) errors.push('master duration must be 180 seconds');
  return errors;
}
