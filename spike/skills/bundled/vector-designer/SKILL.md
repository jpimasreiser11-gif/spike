---
name: vector-designer
description: Use for SVG icons and vector illustrations rendered in the artifacts panel.
license: Apache-2.0
allowed-tools:
- write_file
metadata:
  author: SPIKE contributors
  spike-specialists:
  - design
  - writing
  spike-keywords: svg, icono, icon, ilustración vectorial, vector illustration, vectorial, vector
---

# Vector designer

1. Establish purpose, dimensions, viewBox, palette, background and accessibility needs. Use the project design
   system when supplied and reply in the user's language. Preserve user-owned logos; draw original shapes.
2. Produce self-contained SVG using simple paths, groups and geometric primitives. Include a title and description;
   use meaningful contrast and readable shapes at the requested size. Avoid scripts, event handlers, foreignObject,
   external URLs, embedded credentials, remote fonts and linked images.
3. Return the complete SVG in a fenced code block labelled svg so SPIKE's existing artifacts panel can preview it.
   If a file is requested, write a .svg in the workspace only through the normal write_file permission flow.
4. Check XML structure, unique IDs, viewBox bounds and references. Explain any unverified rendering detail.
   Offer the palette and sizing assumptions in prose outside the SVG; never claim a preview was inspected if not.
