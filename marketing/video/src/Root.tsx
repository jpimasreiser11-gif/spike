import { Composition, Folder, Still } from 'remotion';
import { Film } from './Film';

export const Root = () => <>
  <Composition id="Spike-Master" component={Film} width={1920} height={1080} fps={30} durationInFrames={5400}
    defaultProps={{variant:'master', language:'es' as const}} />
  <Composition id="Spike-Master-EN-Captions" component={Film} width={1920} height={1080} fps={30} durationInFrames={5400}
    defaultProps={{variant:'master', language:'en' as const}} />
  <Folder name="Promos">
    <Composition id="Spike-30" component={Film} width={1920} height={1080} fps={30} durationInFrames={900}
      defaultProps={{variant:'promo30', language:'es' as const}} />
    <Composition id="Spike-60" component={Film} width={1920} height={1080} fps={30} durationInFrames={1800}
      defaultProps={{variant:'promo60', language:'es' as const}} />
    <Composition id="Spike-Vertical-30" component={Film} width={1080} height={1920} fps={30} durationInFrames={900}
      defaultProps={{variant:'vertical30', language:'es' as const}} />
  </Folder>
  <Folder name="Clips">
    {Array.from({length:10},(_,i) => String(i+1).padStart(2,'0')).map(id =>
      <Composition key={id} id={`Spike-Scene-${id}`} component={Film} width={1920} height={1080} fps={30}
        durationInFrames={300} defaultProps={{variant:`scene${id}`,language:'es' as const}} />)}
  </Folder>
  <Folder name="References">
    {Array.from({length:10},(_,i) => String(i+1).padStart(2,'0')).map(id =>
      <Still key={id} id={`Spike-Reference-${id}`} component={Film} width={1920} height={1080}
        defaultProps={{variant:`scene${id}`,language:'es' as const, reference:true}} />)}
  </Folder>
</>;
