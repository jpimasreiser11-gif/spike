// Export bilingual SRT. Timings remain explicitly draft until aligned with reviewed recorded voice.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { captions,srt,validateContent } from '../src/timeline.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const content=JSON.parse(fs.readFileSync(path.join(root,'src/content.json'),'utf8'));
const errors=validateContent(content);
if(errors.length)throw new Error(errors.join('\n'));
const out=path.join(root,'out/subtitles');fs.mkdirSync(out,{recursive:true});
for(const variant of ['master','promo30','promo60',...content.scenes.map(s=>'scene'+s.id)])for(const lang of ['es','en']){
  const lines=captions(content,variant,lang);
  const draft=!content.captionsReviewed||lines.some(line=>line.draft);
  fs.writeFileSync(path.join(out,`${variant}.${lang}.${draft?'draft':'reviewed'}.srt`),srt(lines,content.fps),'utf8');
}
console.log('Wrote 26 SRT files. Draft timing is not synchronized final narration.');
