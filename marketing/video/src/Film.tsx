import { AbsoluteFill, Img, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { Audio, Video } from '@remotion/media';
import content from './content.json';
import { buildTimeline, captions } from './timeline.mjs';

export type FilmProps = {variant: string; language: 'es' | 'en'; reference?: boolean};
type Voice = {path:string; frames:number; reviewed:boolean};
type Capture = {path:string;kind:'video'|'image';speed:number;frames:number;reviewed:boolean};
type Row = {from:number;frames:number;kind:'master'|'clip';scene:{id:string;title:Record<'es'|'en',string>;
  beats:string[];beatsEn:string[];status:'vision'|'verified';capture:Capture|null;voice:Record<'master'|'clip',Voice|null>}};
type Caption = {from:number;to:number;text:string};
const palette = content.brand;
const clamp = {extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const};

function Chapter({row, language, reference}: {row: Row; language:'es'|'en'; reference:boolean}) {
  const current = useCurrentFrame();
  const {fps,width,height} = useVideoConfig();
  const frame = reference ? Math.round(fps*2) : current;
  const portrait = height > width;
  const {scene,frames,kind} = row;
  const dark = scene.id === '01' || scene.id === '10';
  const ink = dark ? palette.cream : palette.ink;
  const entrance = spring({frame, fps, config:{damping:200}, durationInFrames:Math.round(fps*.8)});
  const fade = reference ? 1 : interpolate(frame,[0,8,frames-9,frames-1],[0,1,1,0],clamp);
  const voice = scene.voice[kind];
  const capture = scene.capture;
  const label = scene.status === 'verified' ? (language === 'es' ? 'Demostración comprobada' : 'Verified demonstration') :
    (language === 'es' ? 'Visión del producto' : 'Product vision');
  return <AbsoluteFill style={{background:dark?palette.ink:palette.cream,color:ink,overflow:'hidden',fontFamily:'Inter, system-ui, sans-serif'}}>
    <div style={{position:'absolute',width:900,height:900,borderRadius:'50%',background:palette.green,opacity:dark?.13:.08,
      right:-350,top:-400,transform:`scale(${1+frame/frames*.05})`}} />
    <AbsoluteFill style={{padding:portrait?'100px 72px':'64px 88px',opacity:fade,transform:`translateY(${(1-entrance)*20}px)`}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',fontSize:22,letterSpacing:2}}>
        <span style={{fontWeight:800}}>SPIKE</span><span>{scene.id} / 10 · {label}</span>
      </div>
      <div style={{display:'flex',flexDirection:portrait?'column':'row',gap:portrait?60:72,flex:1,alignItems:portrait?'stretch':'center',paddingTop:portrait?100:36,paddingBottom:140}}>
        <div style={{width:portrait?'100%':'42%'}}>
          <p style={{fontSize:18,letterSpacing:3,textTransform:'uppercase',opacity:.8}}>{language==='es'?'Un espacio para tu trabajo':'One workspace for your work'}</p>
          <h1 style={{fontSize:portrait?72:74,lineHeight:1.07,fontWeight:750,letterSpacing:-3,margin:'28px 0'}}>{scene.title[language]}</h1>
          <div style={{width:90,height:5,background:palette.green,margin:'32px 0'}} />
          {(language==='es'?scene.beats:scene.beatsEn).map((beat:string,i:number) => {
            const reveal = interpolate(frame,[12+i*8,24+i*8],[0,1],clamp);
            return <div key={beat} style={{display:'flex',gap:18,alignItems:'center',marginTop:20,fontSize:26,opacity:reference?1:reveal}}>
              <span style={{display:'inline-flex',alignItems:'center',justifyContent:'center',width:36,height:36,border:'1px solid',borderColor:dark?'#6b997e':'#bdd6c0',borderRadius:12,fontSize:18}}>{i+1}</span>
              <span>{beat}</span>
            </div>;
          })}
        </div>
        <div style={{flex:1,minHeight:portrait?600:520,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:32,
          background:dark?'#174a34':'#e3fada',border:'1px solid '+(dark?'#42765a':'#b7d6b4'),padding:24,overflow:'hidden',position:'relative'}}>
          {capture ? (capture.kind === 'video' ?
            <Video src={staticFile(capture.path)} muted playbackRate={capture.speed} style={{width:'100%',height:portrait?610:520,objectFit:'contain',borderRadius:18}} /> :
            <Img src={staticFile(capture.path)} style={{width:'100%',height:portrait?610:520,objectFit:'contain',borderRadius:18}} />) :
            <div style={{width:'100%',textAlign:'center'}}>
              <Img src={staticFile(palette.mascot)} style={{width:'100%',height:portrait?440:340,objectFit:'contain',borderRadius:24}} />
              <p style={{fontSize:24,lineHeight:1.5,margin:'24px 18px 6px'}}>{language==='es'?'Aquí irá la captura de este recorrido':'The recorded workflow belongs here'}</p>
              <p style={{fontSize:17,opacity:.75}}>{language==='es'?'Referencia de montaje · no es una pantalla de la app':'Editing reference · not an app screenshot'}</p>
            </div>}
          {capture && capture.speed > 1 && <div style={{position:'absolute',right:28,bottom:28,background:palette.ink,color:palette.cream,padding:'10px 16px',borderRadius:12,fontSize:22}}>
            {language==='es'?'Secuencia acelerada':'Sped-up sequence'} ×{capture.speed}</div>}
        </div>
      </div>
      <div style={{position:'absolute',bottom:36,left:portrait?72:88,right:portrait?72:88,display:'flex',justifyContent:'space-between',alignItems:'center',fontSize:18,opacity:.8}}>
        <span>{language==='es'?'Tus modelos. Tus proyectos. Tus decisiones.':'Your models. Your projects. Your decisions.'}</span>
        <span>{voice ? (language==='es'?'Voz ES':'Spanish voice') : (language==='es'?'BORRADOR · SIN VOZ':'DRAFT · NO VOICE')}</span>
      </div>
    </AbsoluteFill>
    {voice && !reference && <Audio src={staticFile(voice.path)} />}
  </AbsoluteFill>;
}

export function Film({variant,language,reference=false}: FilmProps) {
  const frame=useCurrentFrame(), {width,height}=useVideoConfig();
  const rows: Row[]=buildTimeline(content,variant);
  const lines: Caption[]=captions(content,variant,language);
  const subtitle=lines.find(line=>frame>=line.from&&frame<line.to);
  const portrait=height>width;
  return <AbsoluteFill style={{background:palette.ink}}>
    <style>{`@font-face{font-family:Inter;src:url('${staticFile('inter-latin-400-normal.woff2')}') format('woff2');font-weight:400}
      @font-face{font-family:Inter;src:url('${staticFile('inter-latin-700-normal.woff2')}') format('woff2');font-weight:700 900}`}</style>
    {rows.map(row=><Sequence key={row.scene.id} from={row.from} durationInFrames={row.frames}>
      <Chapter row={row} language={language} reference={reference}/>
    </Sequence>)}
    {!reference && subtitle && <div style={{position:'absolute',bottom:portrait?150:104,left:portrait?72:200,right:portrait?72:200,textAlign:'center',fontFamily:'Inter, sans-serif'}}>
      <span style={{display:'inline-block',background:'#052e1eef',color:palette.cream,border:'1px solid #43795d',padding:'14px 28px',borderRadius:14,fontSize:portrait?36:30,lineHeight:1.4}}>{subtitle.text}</span>
      {!content.captionsReviewed && <div style={{color:palette.cream,background:palette.ink,fontSize:15,padding:4,width:'fit-content',margin:'auto'}}>
        {language==='es'?'Tiempos de subtítulos provisionales':'Provisional subtitle timing'}</div>}
    </div>}
    {!reference && <div style={{position:'absolute',bottom:0,left:0,height:4,width:`${(frame+1)/rows.reduce((n,r)=>n+r.frames,0)*100}%`,background:palette.green}}/>}
  </AbsoluteFill>;
}
