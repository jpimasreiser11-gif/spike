/** Offline asset integrity and editorial preflight. It does not grant permission to publish or run a renderer. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { validateContent, localAsset } from '../src/timeline.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const content=JSON.parse(fs.readFileSync(path.join(root,'src/content.json'),'utf8'));
const final=process.argv.includes('--final'), variant=process.argv.find(arg=>arg.startsWith('--variant='))?.slice(10)||'master';
const errors=validateContent(content,final,variant);
const assets=[{path:content.brand.mascot}, {path:'inter-latin-400-normal.woff2'}, {path:'inter-latin-700-normal.woff2'}];
for(const scene of content.scenes) for(const asset of [scene.capture,scene.evidence,scene.voice.master,scene.voice.clip]) if(asset) assets.push(asset);
const base=path.join(root,'public');
for(const asset of assets){
  if(!localAsset(asset.path)){errors.push(`Unsafe asset path: ${asset.path}`);continue;}
  let cursor=base;
  try{
    for(const part of asset.path.split('/')){cursor=path.join(cursor,part);if(fs.lstatSync(cursor).isSymbolicLink()) throw new Error('symlinks refused');}
    const info=fs.statSync(cursor);
    if(!info.isFile()||info.size>512*1024*1024) throw new Error('not a regular bounded file');
    if(asset.sha256){
      const hash=createHash('sha256'), buffer=Buffer.alloc(1024*1024), fd=fs.openSync(cursor,'r');
      try{let count;while((count=fs.readSync(fd,buffer,0,buffer.length,null))>0)hash.update(buffer.subarray(0,count));}finally{fs.closeSync(fd);}
      if(hash.digest('hex')!==asset.sha256)throw new Error('checksum mismatch');
    }
  }catch(error){errors.push(`${asset.path}: ${error.message}`);}
}
if(errors.length){console.error(errors.join('\n'));process.exitCode=1;}
else console.log(final?'FINAL PREFLIGHT PASSED: still requires full playback and human release authorization':'DRAFT PREFLIGHT OK: placeholder capture, no final audio; not ready for release');
