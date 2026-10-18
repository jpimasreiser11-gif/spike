---
name: motion-scene
description: Use when the user wants a video, an animation, a motion graphic, an animated ad or an explainer clip, so it is written as an HTML scene that SPIKE renders to MP4 with render_video, frame-exact and offline.
license: Apache-2.0
metadata:
  spike-specialists: code, core
  spike-keywords: vídeo, video, animación, animation, animado, animated, motion, motion graphics, clip, anuncio animado, animated ad, intro, reel, explainer, gif animado, mp4
---

# Motion scene

A video here is code: one HTML file that plays the animation, then `render_video` turns it into MP4, WebM or GIF.

## The scene file

- One self-contained `.html` file. No links to the internet: scripts, styles, fonts and images go inline
  (images and fonts as `data:` URLs, or drawn with SVG/CSS). Anything loaded from outside is blocked.
- The stage is the whole viewport at the video size (16:9 = 1280x720, 9:16 = 720x1280, 1:1 = 1080x1080).
  Set `html, body { margin: 0; width: 100%; height: 100%; overflow: hidden }` and lay out in px for that size.
- Declare the length: `<meta name="spike-duration" content="8">` (seconds, at most 60).
- Animate with CSS `@keyframes`, `transition`, `element.animate()`, SVG `<animate>`, or a `requestAnimationFrame`
  loop that reads its timestamp. Time is exact: frame N is at N/fps seconds, `setTimeout` fires on time and
  `Math.random()` gives the same numbers each render.
- Sequence with `animation-delay` and `animation-fill-mode: both` (or `forwards`), not with `animationend`
  events: those do not fire while frames are rendered. `<video>` and `<audio>` are not supported.

## Storyboard first

Before writing, list the shots with their times: for example 0–2 s title in, 2–5 s three points one by one,
5–8 s call to action and logo. One idea per shot; leave each text on screen at least 1.5 s.

## Craft

- Ease every move (`cubic-bezier(.2,.8,.2,1)` for entrances, `ease-in` for exits); avoid linear motion except
  for constant drifts.
- Animate `transform` and `opacity`; keep text large (at least 48 px at 1280x720) with strong contrast.
- Stagger related elements by 80–150 ms. End on a still frame of about 1 s.
- Use the brand or design system colours when the user gave them.

## Render and check

Call `render_video` with the scene, the output (`video.mp4` unless asked otherwise), the size and fps (30).
If the result lists JavaScript errors or blocked addresses, fix the scene and render again. Report the file,
its length and size.
