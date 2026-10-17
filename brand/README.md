# SPIKE brand assets

Generated from joan's logo (`spike-logo-original.png`) and the AI images in `source/`, using `tools/build_brand.py`. To regenerate after changing a source image, run:

`python3 -I tools/build_brand.py <folder with the ChatGPT exports> <this folder> <folder with Nunito-700/900.ttf>` (first batch)

`python3 -I tools/build_round2.py <folder with the ChatGPT exports> <this folder> <fonts folder>` (specialists, states, onboarding, docs, launch; takes the last 28 exports in generation order)

Taglines use Nunito (SIL OFL, `tools/Nunito-OFL.txt`). The "SPIKE" wordmark is cut from the original logo.

| Folder | Contents |
|---|---|
| `source/` | Originals renamed by ID from `IMAGENES-Y-PROMPTS.md` (A0, B0, B2, B3, C2, D1, D2 light/dark, E1, F1) |
| `logo/` | Transparent cactus at 2048/1024/512, `spike-mark.svg`, wordmark (PNG, SVG, white), horizontal lockup (dark/white), monochrome (ink, white, SVG) |
| `icons/` | `spike-icon-1024.png` (full bleed), `macos/` (`.icns`, `.iconset`, 1024 on Apple grid), `windows/` (`.ico` 16–256 + PNGs), `linux/hicolor/` (16–512 + scalable SVG), `tray/` (macOS template 18/36/54, Windows 16–32 + `.ico`) |
| `web/` | `favicon.ico`/`.svg`/16/32, `apple-touch-icon.png`, `icon-192/512`, `icon-maskable-512`, `safari-pinned-tab.svg`, `site.webmanifest`, `og-image.png` 1200×630 (with/without text) |
| `github/` | `social-preview.png` 1280×640, `readme-banner-light/dark.png` 1600×533 (with/without text), `avatar-500.png` |
| `installers/` | `macos/dmg-background.png` + `@2x`, `dmg-layout.json`; `windows/` NSIS header/welcome, WiX banner/dialog (`.bmp`), installer `.ico` |
| `app/` | `splash-1024/512/256.png`, chat avatar `avatar-64/128/256.png`, `states/` (empty chat, no models, error, thinking, working, cloud, 404; PNG + WebP), `onboarding/` (local, specialists, privacy; PNG + WebP) |
| `specialists/<id>/` | One folder per specialist in `spike/specialists/catalog.yaml`: transparent character `spike-<id>.png`, app icon `icon-<id>-32…1024.png` (pastel accent tile), chat avatar `avatar-<id>-64/128/256.png`, Hugging Face card banner `hf-banner-<id>.png` 1280×640. Plus `specialists-grid.png` with all 13 for docs |
| `docs/` | Section headers 1600×500 for Quickstart, Specialists, Architecture and Training (with title and `-notext`) |
| `launch/` | Announcement image 1920×1080 (with and without text) |

Small sizes (16–32 px) use the simplified B2 cactus; larger ones use the full icon.

The root files `spike-app-icon.png`, `spike-mark.png` and `spike-wordmark.png` were made earlier by the "Construir SPIKE" thread. `logo/` and `icons/` replace them.

README usage (light/dark):

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/github/readme-banner-dark.png">
  <img alt="SPIKE" src="brand/github/readme-banner-light.png">
</picture>
```
