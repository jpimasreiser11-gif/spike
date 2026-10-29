// Ten lightweight reference stills, serially, using an explicitly supplied existing browser. No browser download.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const browser=process.env.SPIKE_VIDEO_BROWSER;
if(!browser||!fs.statSync(browser,{throwIfNoEntry:false})?.isFile())throw new Error('Set SPIKE_VIDEO_BROWSER to an existing Chromium executable; no automatic download');
const check=spawnSync(process.execPath,['scripts/preflight.mjs'],{cwd:root,stdio:'inherit'});
if(check.status!==0)process.exit(check.status||1);
const out=path.join(root,'out/references');fs.mkdirSync(out,{recursive:true});
const cli=path.join(root,'node_modules/@remotion/cli/remotion-cli.js');
for(let i=1;i<=10;i++){
 const id=String(i).padStart(2,'0');
 const result=spawnSync(process.execPath,[cli,'still','src/index.tsx',`Spike-Reference-${id}`,`out/references/${id}.png`,
  `--browser-executable=${browser}`,'--log=error'],{cwd:root,stdio:'inherit',timeout:120000});
 if(result.status!==0)throw new Error(`Reference ${id} failed: ${result.error?.message||result.status}`);
 console.log(`Reference ${id}/10 written`);
}
const cards=Array.from({length:10},(_,i)=>{const id=String(i+1).padStart(2,'0');return `<a href="${id}.png"><img src="${id}.png" alt="Escena ${id}, referencia de montaje"><span>Escena ${id}</span></a>`;}).join('');
fs.writeFileSync(path.join(out,'index.html'),`<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>SPIKE · 10 referencias</title><style>body{margin:32px;background:#fdfdfa;color:#052e1e;font:18px system-ui}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}img{width:100%;border-radius:16px}a{color:inherit;text-decoration:none}span{display:block;margin:10px 0}</style><h1>SPIKE · Diez referencias de montaje</h1><p>Visión del producto. Capturas y voz pendientes; no son demostraciones de funciones verificadas.</p><main>${cards}</main></html>`,'utf8');
