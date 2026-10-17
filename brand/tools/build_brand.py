"""Build every SPIKE brand derivative from the generated masters.

Usage: python3 -I build_brand.py <src_dir> <out_dir> <fonts_dir>
"""
import json, shutil, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops
import numpy as np
import vtracer

SRC, OUT, FONTS = map(Path, sys.argv[1:4])
INK = (5, 46, 30); MINT = (227, 250, 218); MINT2 = (212, 245, 200); CREAM = (253, 253, 250)
DARK_BG = (11, 26, 18)
F900, F700 = FONTS / "Nunito-900.ttf", FONTS / "Nunito-700.ttf"
TAGLINE = "Open-source specialist AI that runs on your laptop"

RAW = {  # suffix of the ChatGPT export -> (brand id, file name)
    1: "a0-cactus-master.png", 2: "b0-app-icon-master.png", 3: "b2-icon-small.png",
    4: "b3-tray-template.png", 5: "c2-og-card.png", 6: "d1-github-social-preview.png",
    7: "d2-readme-banner-light.png", 8: "d2-readme-banner-dark.png",
    9: "e1-dmg-background.png", 10: "f1-splash.png",
}


def out(rel):
    p = OUT / rel; p.parent.mkdir(parents=True, exist_ok=True); return p


def trim(im, pad=0):
    bb = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    im = im.crop(bb)
    if pad:
        c = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
        c.paste(im, (pad, pad)); im = c
    return im


def fit_square(im, size, fill=0.9, bottom=False):
    """Scale RGBA art into a transparent square; optionally anchor to the bottom edge."""
    im = im.copy(); s = int(size * fill)
    im.thumbnail((s, s), Image.LANCZOS)
    c = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    y = size - im.height if bottom else (size - im.height) // 2
    c.paste(im, ((size - im.width) // 2, y), im)
    return c


def rr_mask(size, box, radius, ss=4):
    m = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle([v * ss for v in box], radius * ss, fill=255)
    return m.resize(size, Image.LANCZOS)


def vgradient(size, top, bottom):
    a = np.linspace(0, 1, size[1])[:, None, None]
    arr = (np.array(top) * (1 - a) + np.array(bottom) * a).repeat(size[0], 1)
    return Image.fromarray(arr.astype("uint8"), "RGB").convert("RGBA")


def save_svg(png, svg, **kw):
    if kw.get("colormode") == "binary":   # vtracer binary mode needs an opaque image
        im = Image.open(png).convert("RGBA"); flat = Image.new("RGBA", im.size, (255, 255, 255, 255))
        flat.alpha_composite(im); tmp = Path(str(svg) + ".tmp.png"); flat.convert("RGB").save(tmp)
        vtracer.convert_image_to_svg_py(str(tmp), str(svg), **kw); tmp.unlink()
        Path(svg).write_text(Path(svg).read_text().replace('fill="#000000"', 'fill="#052E1E"'))
        return
    vtracer.convert_image_to_svg_py(str(png), str(svg), **kw)


def resize(im, w, h=None):
    return im.resize((w, h or w), Image.LANCZOS)


# --- 0. sources ---------------------------------------------------------------
src = {}
for f in SRC.glob("Imagen de ChatGPT 17 oct 2026*.png"):
    n = int(f.stem.rsplit("-", 1)[1])
    if n in RAW:
        shutil.copy2(f, out("source/" + RAW[n]))
        src[n] = Image.open(f).convert("RGBA")
shutil.copy2(OUT / "spike-logo-original.png", out("source/spike-logo-original.png"))

# --- A. logo ------------------------------------------------------------------
mark = trim(src[1])                                     # A0: cactus, flat bottom
mark_sq = fit_square(mark, 2048, 0.94)
mark_sq.save(out("logo/spike-mark-2048.png"))
resize(mark_sq, 1024).save(out("logo/spike-mark-1024.png"))
resize(mark_sq, 512).save(out("logo/spike-mark-512.png"))
save_svg(out("logo/spike-mark-1024.png"), out("logo/spike-mark.svg"),
         colormode="color", hierarchical="stacked", mode="spline", filter_speckle=8,
         color_precision=6, layer_difference=24, corner_threshold=60, path_precision=3)

# A1: wordmark cut from the original logo (dark text on cream -> alpha)
logo = Image.open(OUT / "spike-logo-original.png").convert("RGB")
wm = np.array(logo.crop((140, 750, 850, 950))).astype(float)
alpha = np.clip((235 - wm.mean(2)) / (235 - 60) * 255, 0, 255).astype("uint8")
wm_rgba = Image.new("RGBA", (wm.shape[1], wm.shape[0]), INK + (0,)); wm_rgba.putalpha(Image.fromarray(alpha))
wordmark = trim(wm_rgba)
wordmark.save(out("logo/spike-wordmark.png"))
save_svg(out("logo/spike-wordmark.png"), out("logo/spike-wordmark.svg"),
         colormode="binary", mode="spline", filter_speckle=8, corner_threshold=60)
wm_white = wordmark.copy(); wm_white.paste((255, 255, 255, 255), mask=wordmark.getchannel("A"))
wm_white.save(out("logo/spike-wordmark-white.png"))


def lockup(text_img, h=600):
    m = mark.copy(); m.thumbnail((h, h), Image.LANCZOS)
    t = text_img.copy(); t.thumbnail((10_000, int(h * 0.42)), Image.LANCZOS)
    gap = int(h * 0.12)
    c = Image.new("RGBA", (m.width + gap + t.width, h), (0, 0, 0, 0))
    c.paste(m, (0, h - m.height), m); c.paste(t, (m.width + gap, (h - t.height) // 2 + int(h * 0.06)), t)
    return c


lockup(wordmark).save(out("logo/spike-lockup-horizontal.png"))
lockup(wm_white).save(out("logo/spike-lockup-horizontal-white.png"))

# A3: monochrome from the B3 silhouette
sil = trim(src[4])
sil_sq = fit_square(sil, 1024, 0.94)
ink = Image.new("RGBA", sil_sq.size, INK + (0,)); ink.putalpha(sil_sq.getchannel("A")); ink.save(out("logo/spike-mono-ink.png"))
wht = Image.new("RGBA", sil_sq.size, (255, 255, 255, 0)); wht.putalpha(sil_sq.getchannel("A")); wht.save(out("logo/spike-mono-white.png"))
save_svg(out("logo/spike-mono-ink.png"), out("logo/spike-mono.svg"), colormode="binary", mode="spline", filter_speckle=8)

# --- B. app icon --------------------------------------------------------------
def app_icon(size=1024, inset=0.0, radius_k=0.2237, art=0.78, shadow=False):
    """Mint squircle with the cactus rising from its bottom edge (design of B0)."""
    S = size; pad = int(S * inset); box = (pad, pad, S - pad - 1, S - pad - 1); w = S - 2 * pad
    tile = vgradient((S, S), MINT, MINT2)
    m = mark.copy(); m.thumbnail((int(w * art), int(w * art)), Image.LANCZOS)
    tile.paste(m, ((S - m.width) // 2, S - pad - m.height + int(w * 0.005)), m)
    mask = rr_mask((S, S), box, w * radius_k)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0)); icon.paste(tile, (0, 0), mask)
    if shadow:
        sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        sh.putalpha(mask.point(lambda v: int(v * 0.30)).filter(ImageFilter.GaussianBlur(S * 0.012)))
        sh = ImageChops.offset(sh, 0, int(S * 0.012)); sh.alpha_composite(icon); icon = sh
    return icon


icon_full = app_icon(1024)                                   # full-bleed (Windows/Linux/web)
icon_mac = app_icon(1024, inset=100 / 1024, shadow=True)     # Apple grid: 824 px tile + shadow
icon_full.save(out("icons/spike-icon-1024.png")); icon_mac.save(out("icons/macos/spike-icon-macos-1024.png"))

small = trim(src[3])                                         # B2: readable at 16-32 px


def small_icon(s):
    return fit_square(small, s, 1.0 if s <= 24 else 0.96)


def best(s):
    return small_icon(s) if s <= 32 else resize(icon_full, s)


# macOS .iconset + .icns
iconset = out("icons/macos/spike.iconset/x").parent
for base in (16, 32, 128, 256, 512):
    for k in (1, 2):
        px = base * k
        img = small_icon(px) if px <= 32 else resize(icon_mac, px)
        img.save(iconset / (f"icon_{base}x{base}" + ("@2x" if k == 2 else "") + ".png"))
icon_mac.save(out("icons/macos/spike.icns"), sizes=[(s, s) for s in (16, 32, 64, 128, 256, 512, 1024)])

# Windows .ico (small sizes use B2)
win = [16, 24, 32, 48, 64, 128, 256]
icon_full.save(out("icons/windows/spike.ico"), sizes=[(s, s) for s in win],
               append_images=[best(s) for s in win])
for s in win:
    best(s).save(out(f"icons/windows/png/spike-{s}.png"))

# Linux hicolor
for s in (16, 22, 24, 32, 48, 64, 128, 256, 512):
    best(s).save(out(f"icons/linux/hicolor/{s}x{s}/apps/spike.png"))
shutil.copy2(out("logo/spike-mark.svg"), out("icons/linux/hicolor/scalable/apps/spike.svg"))

# Tray / menu bar
traysil = fit_square(sil, 1024, 1.0)
black = Image.new("RGBA", traysil.size, (0, 0, 0, 0)); black.putalpha(traysil.getchannel("A"))
for s, name in ((18, "spikeTemplate.png"), (36, "spikeTemplate@2x.png"), (54, "spikeTemplate@3x.png")):
    resize(black, s).save(out("icons/tray/macos/" + name))
for s in (16, 20, 24, 32):
    resize(icon_full, s).save(out(f"icons/tray/windows/spike-tray-{s}.png"))
resize(icon_full, 256).save(out("icons/tray/windows/spike-tray.ico"), sizes=[(16, 16), (20, 20), (24, 24), (32, 32)],
                            append_images=[small_icon(s) for s in (16, 20, 24, 32)])

# --- C. favicon & web -----------------------------------------------------------
fav = [16, 32, 48]
small_icon(256).save(out("web/favicon.ico"), sizes=[(s, s) for s in fav], append_images=[small_icon(s) for s in fav])
for s in (16, 32):
    small_icon(s).save(out(f"web/favicon-{s}.png"))
small_icon(512).save(out("web/_b2-512.png"))
save_svg(out("web/_b2-512.png"), out("web/favicon.svg"), colormode="color", hierarchical="stacked",
         mode="spline", filter_speckle=10, color_precision=5, layer_difference=32)
(OUT / "web/_b2-512.png").unlink()
apple = vgradient((180, 180), MINT, MINT2); m = mark.copy(); m.thumbnail((150, 150), Image.LANCZOS)
apple.paste(m, ((180 - m.width) // 2, 180 - m.height), m); apple.convert("RGB").save(out("web/apple-touch-icon.png"))
resize(icon_full, 192).save(out("web/icon-192.png")); resize(icon_full, 512).save(out("web/icon-512.png"))
mk = vgradient((512, 512), MINT, MINT2); m = mark.copy(); m.thumbnail((300, 300), Image.LANCZOS)   # 80% safe zone
mk.paste(m, ((512 - m.width) // 2, (512 - m.height) // 2), m); mk.convert("RGB").save(out("web/icon-maskable-512.png"))
save_svg(out("logo/spike-mono-ink.png"), out("web/safari-pinned-tab.svg"), colormode="binary", mode="spline", filter_speckle=8)
json.dump({"name": "SPIKE", "short_name": "SPIKE", "theme_color": "#88D445", "background_color": "#FDFDFA",
           "display": "standalone", "icons": [
               {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
               {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
               {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
          open(out("web/site.webmanifest"), "w"), indent=2)


# --- text helpers ---------------------------------------------------------------
def font(p, size):
    return ImageFont.truetype(str(p), size)


def place_wordmark(canvas, x, y_center, height, white=False):
    w = (wm_white if white else wordmark).copy(); w.thumbnail((10_000, height), Image.LANCZOS)
    canvas.alpha_composite(w, (int(x), int(y_center - w.height / 2))); return w


def text(canvas, xy, s, size, fill, weight=F700):
    ImageDraw.Draw(canvas).text(xy, s, font=font(weight, size), fill=fill)


def wrap(s, f, width):
    words, lines, cur = s.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if f.getlength(t) <= width: cur = t
        else: lines.append(cur); cur = wd
    return lines + [cur]


def title_block(canvas, x, y_center, max_w, wm_h, tag_size, white=False, tag=TAGLINE):
    f = font(F700, tag_size); lines = wrap(tag, f, max_w)
    lh = int(tag_size * 1.3); total = wm_h + int(wm_h * 0.35) + lh * len(lines)
    top = y_center - total / 2
    place_wordmark(canvas, x, top + wm_h / 2, wm_h, white)
    col = (227, 250, 218) if white else (42, 86, 58)
    for i, ln in enumerate(lines):
        text(canvas, (x, top + wm_h + int(wm_h * 0.35) + i * lh), ln, tag_size, col)


def cover(im, w, h):
    r = max(w / im.width, h / im.height); im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


# --- C2 Open Graph 1200x630 ------------------------------------------------------
og = cover(src[5], 1200, 630)
title_block(og, 640, 315, 500, 110, 34)
og.convert("RGB").save(out("web/og-image.png"), optimize=True)
cover(src[5], 1200, 630).convert("RGB").save(out("web/og-image-notext.png"), optimize=True)

# --- D. GitHub ---------------------------------------------------------------------
sp = cover(src[6], 1280, 640)
title_block(sp, 760, 320, 460, 120, 34)
sp.convert("RGB").save(out("github/social-preview.png"), optimize=True)
cover(src[6], 1280, 640).convert("RGB").save(out("github/social-preview-notext.png"), optimize=True)

for n, name, white in ((7, "readme-banner-light", False), (8, "readme-banner-dark", True)):
    b = cover(src[n], 1600, 533)
    title_block(b, 700, 255, 900, 150, 34, white=white)
    b.convert("RGB").save(out(f"github/{name}.png"), optimize=True)
    cover(src[n], 1600, 533).convert("RGB").save(out(f"github/{name}-notext.png"), optimize=True)

resize(icon_full, 500).save(out("github/avatar-500.png"))
av = vgradient((500, 500), MINT, MINT2); m = mark.copy(); m.thumbnail((420, 420), Image.LANCZOS)
av.paste(m, ((500 - m.width) // 2, 500 - m.height), m); av.convert("RGB").save(out("github/avatar-500-square.png"))

# --- E. installers -------------------------------------------------------------------
dmg = src[9].convert("RGB")
resize(dmg, 1320, 800).save(out("installers/macos/dmg-background@2x.png"))
resize(dmg, 660, 400).save(out("installers/macos/dmg-background.png"))
# Icon/Applications slots measured on the 660x400 version, for create-dmg / appdmg
json.dump({"window": [660, 400], "icon_size": 112, "app_icon_xy": [165, 175], "applications_xy": [480, 175],
           "note": "slot centres approximated from the light-mint circles; adjust after a real DMG test"},
          open(out("installers/macos/dmg-layout.json"), "w"), indent=2)
# Windows headers from the lockup (NSIS 150x57, WiX banner 493x58, WiX dialog 493x312)
for w, h, name in ((150, 57, "nsis-header.bmp"), (493, 58, "wix-banner.bmp")):
    c = Image.new("RGBA", (w, h), CREAM + (255,)); l = lockup(wordmark, 400); l.thumbnail((w - 12, h - 12), Image.LANCZOS)
    c.alpha_composite(l, (w - l.width - 6, (h - l.height) // 2)); c.convert("RGB").save(out("installers/windows/" + name))
c = vgradient((493, 312), MINT, (136, 212, 69)); m = mark.copy(); m.thumbnail((150, 150), Image.LANCZOS)
c.alpha_composite(m, (20, 312 - m.height)); c.convert("RGB").save(out("installers/windows/wix-dialog.bmp"))
c = vgradient((164, 314), MINT, (136, 212, 69)); m = mark.copy(); m.thumbnail((140, 140), Image.LANCZOS)
c.alpha_composite(m, ((164 - m.width) // 2, 314 - m.height)); c.convert("RGB").save(out("installers/windows/nsis-welcome.bmp"))
shutil.copy2(out("icons/windows/spike.ico"), out("installers/windows/spike-installer.ico"))

# --- F. app --------------------------------------------------------------------------
splash = trim(src[10])
for s in (1024, 512, 256):
    fit_square(splash, s, 0.96).save(out(f"app/splash-{s}.png"))
# chat avatar: head + upper trunk inside a mint circle
head = mark.crop((0, 0, mark.width, int(mark.height * 0.72)))
for s in (64, 128, 256):
    S = s * 4; c = Image.new("RGBA", (S, S), MINT + (255,)); h = head.copy(); h.thumbnail((int(S * 0.92), int(S * 0.92)), Image.LANCZOS)
    c.alpha_composite(h, ((S - h.width) // 2, S - h.height + int(S * 0.02)))
    m = Image.new("L", (S, S), 0); ImageDraw.Draw(m).ellipse((0, 0, S - 1, S - 1), fill=255)
    o = Image.new("RGBA", (S, S), (0, 0, 0, 0)); o.paste(c, (0, 0), m); resize(o, s).save(out(f"app/avatar-{s}.png"))

print("done")
