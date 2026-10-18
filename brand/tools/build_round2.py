"""Second batch: specialists (icon, avatar, Hugging Face banner), app states, onboarding, doc headers, launch, 404.

Usage: python3 -I build_round2.py <folder with the 28 ChatGPT exports> <brand dir> <fonts dir>
The 28 exports are taken in generation order (timestamp, then -N suffix), matching IMAGENES-Y-PROMPTS.md.
"""
import re, shutil, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

SRC, OUT, FONTS = map(Path, sys.argv[1:4])
INK = (5, 46, 30); CREAM = (253, 253, 250); MINT = (227, 250, 218)
F900, F700 = FONTS / "Nunito-900.ttf", FONTS / "Nunito-700.ttf"

SPECS = [  # id, name, domain (catalog.yaml), pastel background, accent
    ("core", "Spike Core", "General reasoning, planning and synthesis", "#E3FADA", "#3FA34D"),
    ("code", "Spike Code", "Software engineering", "#DCEBFF", "#3E7BFA"),
    ("finance", "Spike Finance", "Finance, accounting and investing", "#FFF1C2", "#E0A800"),
    ("medicine", "Spike Medicine", "Medicine and health sciences", "#FFE1E1", "#E5484D"),
    ("law", "Spike Law", "Law and regulation", "#E6E8F0", "#5B6478"),
    ("marketing", "Spike Marketing", "Marketing, growth and communication", "#FFE0F0", "#E93D82"),
    ("science", "Spike Science", "Natural sciences", "#D6F5F2", "#12A594"),
    ("data", "Spike Data", "Data analysis and databases", "#D8F3FC", "#0090C7"),
    ("math", "Spike Math", "Mathematics", "#E4E2FF", "#6E56CF"),
    ("education", "Spike Education", "Teaching and learning", "#FFE8D6", "#F76B15"),
    ("writing", "Spike Writing", "Writing and editing", "#F1E4FA", "#9D5BD2"),
    ("business", "Spike Business", "Business strategy and operations", "#F2E8DE", "#A0703C"),
    ("security", "Spike Security", "Cybersecurity", "#D9EDE0", "#1B6B3A"),
]
REST = ["state-empty-chat", "state-no-models", "state-error", "state-thinking", "state-working", "state-cloud",
        "onboard-local", "onboard-specialists", "onboard-privacy",
        "doc-quickstart", "doc-specialists", "doc-architecture", "doc-training",
        "launch-hero", "page-404"]
DOC_TITLES = {"doc-quickstart": "Quickstart", "doc-specialists": "Specialists",
              "doc-architecture": "Architecture", "doc-training": "Training"}


def hexrgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def out(rel):
    p = OUT / rel; p.parent.mkdir(parents=True, exist_ok=True); return p


def trim(im, pad=0):
    a = im.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    im = im.crop(a.getbbox())
    if pad:
        c = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0)); c.paste(im, (pad, pad)); im = c
    return im


def fit(im, w, h, fill=0.94, bottom=False):
    im = im.copy(); im.thumbnail((int(w * fill), int(h * fill)), Image.LANCZOS)
    c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c.paste(im, ((w - im.width) // 2, h - im.height if bottom else (h - im.height) // 2), im); return c


def vgrad(size, top, bottom):
    a = np.linspace(0, 1, size[1])[:, None, None]
    arr = (np.array(top) * (1 - a) + np.array(bottom) * a).repeat(size[0], 1)
    return Image.fromarray(arr.astype("uint8"), "RGB").convert("RGBA")


def hgrad(size, left, right):
    a = np.linspace(0, 1, size[0])[None, :, None]
    arr = (np.array(left) * (1 - a) + np.array(right) * a).repeat(size[1], 0)
    return Image.fromarray(arr.astype("uint8"), "RGB").convert("RGBA")


def darker(c, k): return tuple(int(v * k) for v in c)


def rr(size, radius, ss=4):
    m = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * ss - 1, size * ss - 1), radius * ss, fill=255)
    return m.resize((size, size), Image.LANCZOS)


def body_only(im):
    """Drop the soft ground shadow (pale, low-alpha band under the cactus) so it can sit on the tile edge."""
    a = np.array(im)
    rgb, al = a[..., :3].astype(int), a[..., 3]
    pale = (rgb.min(2) > 170) & (rgb[..., 1] > rgb[..., 0]) & (np.arange(a.shape[0])[:, None] > a.shape[0] * 0.8)
    a[..., 3] = np.where(pale, 0, al)
    return trim(Image.fromarray(a))


def font(p, s): return ImageFont.truetype(str(p), s)


def cover(im, w, h):
    r = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


# --- order the exports -----------------------------------------------------------
def key(f):
    m = re.search(r"(\d\d)_(\d\d)_(\d\d)-(\d+)\.png$", f.name)
    return (m.group(1), m.group(2), int(m.group(4))) if m else None


files = sorted([f for f in SRC.glob("Imagen de ChatGPT*.png") if key(f)], key=key)
files = files[-28:]
assert len(files) == 28, len(files)
names = [f"spec-{s[0]}" for s in SPECS] + REST
src = {}
for f, n in zip(files, names):
    shutil.copy2(f, out(f"source/{n}.png"))
    src[n] = Image.open(f).convert("RGBA")

wordmark = Image.open(OUT / "logo/spike-wordmark.png").convert("RGBA")

# --- specialists -------------------------------------------------------------------
for sid, name, domain, bg_hex, acc_hex in SPECS:
    bg, acc = hexrgb(bg_hex), hexrgb(acc_hex)
    art = trim(src[f"spec-{sid}"])
    d = f"specialists/{sid}/"
    fit(art, 1024, 1024).save(out(d + f"spike-{sid}.png"))
    # app icon: pastel squircle, cactus rising from the bottom edge like the main icon
    S = 1024; tile = vgrad((S, S), bg, darker(bg, 0.93)); b = body_only(art); b.thumbnail((int(S * 0.86), int(S * 0.86)), Image.LANCZOS)
    tile.alpha_composite(b, ((S - b.width) // 2, S - b.height))
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0)); icon.paste(tile, (0, 0), rr(S, int(S * 0.2237)))
    for s in (1024, 512, 256, 128, 64, 32):
        icon.resize((s, s), Image.LANCZOS).save(out(d + f"icon-{sid}-{s}.png"))
    # chat avatar: circle, head and upper trunk
    side = int(min(b.width, b.height * 0.8)); l = (b.width - side) // 2
    head = b.crop((l, 0, l + side, side))   # square around the face, accessories may be clipped
    A = 1024; c = Image.new("RGBA", (A, A), bg + (255,)); h = head.resize((int(A * 0.9), int(A * 0.9)), Image.LANCZOS)
    c.alpha_composite(h, ((A - h.width) // 2, A - h.height + int(A * 0.04)))
    m = Image.new("L", (A, A), 0); ImageDraw.Draw(m).ellipse((0, 0, A - 1, A - 1), fill=255)
    av = Image.new("RGBA", (A, A), (0, 0, 0, 0)); av.paste(c, (0, 0), m)
    for s in (256, 128, 64):
        av.resize((s, s), Image.LANCZOS).save(out(d + f"avatar-{sid}-{s}.png"))
    # Hugging Face model card banner 1280x640
    W, H = 1280, 640; ban = hgrad((W, H), CREAM, bg)
    a2 = art.copy(); a2.thumbnail((560, 560), Image.LANCZOS); ban.alpha_composite(a2, (60 + (560 - a2.width) // 2, H - a2.height - 30))
    dr = ImageDraw.Draw(ban); x = 660
    wm = wordmark.copy(); wm.thumbnail((10_000, 46), Image.LANCZOS); ban.alpha_composite(wm, (x, 200))
    title = name.replace("Spike ", ""); f1 = font(F900, 96)
    while f1.getlength(title) > W - x - 50: f1 = font(F900, f1.size - 4)
    dr.text((x, 252), title, font=f1, fill=INK)
    dr.rounded_rectangle((x, 380, x + 70, 388), 4, fill=acc)
    f2 = font(F700, 32); words, lines, cur = domain.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if f2.getlength(t) <= W - x - 60: cur = t
        else: lines.append(cur); cur = wd
    lines.append(cur)
    for i, ln in enumerate(lines): dr.text((x, 410 + i * 44), ln, font=f2, fill=(42, 86, 58))
    ban.convert("RGB").save(out(d + f"hf-banner-{sid}.png"), optimize=True)

# specialists overview sheet for docs/SPECIALISTS.md and the README
cols, cell = 5, 240; rows = -(-len(SPECS) // cols)
grid = Image.new("RGBA", (cols * cell, rows * (cell + 50)), (0, 0, 0, 0)); dr = ImageDraw.Draw(grid); f = font(F700, 24)
for i, (sid, name, *_rest) in enumerate(SPECS):
    ic = Image.open(out(f"specialists/{sid}/icon-{sid}-256.png")).resize((180, 180), Image.LANCZOS)
    x, y = (i % cols) * cell, (i // cols) * (cell + 50)
    grid.alpha_composite(ic, (x + 30, y + 20)); label = name.replace("Spike ", "")
    dr.text((x + cell / 2 - f.getlength(label) / 2, y + 210), label, font=f, fill=INK)
grid.save(out("specialists/specialists-grid.png"))

# --- app states & onboarding (transparent, trimmed, padded) ----------------------------
for n in REST[:9] + ["page-404"]:
    im = trim(src[n], pad=24)
    folder = "app/states/" if n.startswith(("state", "page")) else "app/onboarding/"
    im.save(out(folder + f"{n}.png"), optimize=True)
    w = im.copy(); w.thumbnail((800, 800), Image.LANCZOS); w.save(out(folder + f"{n}.webp"), quality=90, method=6)

# --- doc headers 1600x500 with title on the left -------------------------------------
for n, title in DOC_TITLES.items():
    base = cover(src[n].convert("RGBA"), 1600, 500)
    base.convert("RGB").save(out(f"docs/{n}-notext.png"), optimize=True)
    t = base.copy(); dr = ImageDraw.Draw(t)
    wm = wordmark.copy(); wm.thumbnail((10_000, 44), Image.LANCZOS); t.alpha_composite(wm, (110, 150))
    dr.text((106, 205), title, font=font(F900, 110), fill=INK)
    t.convert("RGB").save(out(f"docs/{n}.png"), optimize=True)

# --- launch image 1920x1080 ----------------------------------------------------------
L = cover(src["launch-hero"], 1920, 1080)
L.convert("RGB").save(out("launch/launch-hero-notext.png"), optimize=True)
dr = ImageDraw.Draw(L); x = 1060
wm = wordmark.copy(); wm.thumbnail((10_000, 170), Image.LANCZOS); L.alpha_composite(wm, (x, 330))
f2 = font(F700, 52)
for i, ln in enumerate(["Open-source specialist AI", "that runs on your laptop"]):
    dr.text((x, 560 + i * 70), ln, font=f2, fill=(42, 86, 58))
L.convert("RGB").save(out("launch/launch-hero.png"), optimize=True)
print("ok", len(list(OUT.rglob("*"))))
