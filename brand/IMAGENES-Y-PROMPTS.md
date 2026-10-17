# SPIKE · Imágenes necesarias y prompts de generación

Logo oficial: [`spike-logo-original.png`](spike-logo-original.png) (copia exacta del archivo original, 1448×1086). **El logo no se reemplaza**: todo lo de abajo se deriva de él o lo acompaña.

---

## 1. Análisis del logo

| Elemento | Descripción |
|---|---|
| Personaje | Cactus saguaro kawaii: tronco central redondeado, dos brazos levantados (gesto de saludo), ojos ovalados verticales, sonrisa pequeña en forma de "w" suave, sin mejillas. |
| Espinas | Trazos cortos y rectos, color contorno, salen perpendiculares del borde (≈12 en el logo grande). Son el guiño al nombre *SPIKE*. |
| Marcas del cuerpo | Pequeños trazos verticales en verde oscuro sobre el cuerpo y los brazos (textura de cactus). |
| Contorno | Grueso, uniforme, redondeado, verde casi negro. Estilo *flat* con un único sombreado suave a la izquierda y un brillo claro arriba a la izquierda. |
| Base | El cactus sale del suelo cortado en línea recta; sombra elíptica verde pálido debajo. Sin maceta. |
| Tipografía | "SPIKE" en mayúsculas, sans-serif geométrica redondeada y muy gruesa (tipo *Nunito Black / Baloo / Fredoka Bold*), color verde casi negro. |
| Icono app | Versión reducida del cactus dentro de un *squircle* verde muy claro con sombra suave. |
| Fondo | Blanco cálido, casi crema. |
| Tono | Amistoso, accesible, confiable; nada agresivo pese al nombre. |

### Paleta (muestreada del PNG)

| Token | HEX | Uso |
|---|---|---|
| `spike-ink` | `#052E1E` | Contorno, texto, ojos |
| `spike-green` | `#88D445` | Cuerpo (color principal) |
| `spike-green-shade` | `#5FBB47` | Sombra lateral |
| `spike-green-dark` | `#2A7B20` | Marcas del cuerpo |
| `spike-highlight` | `#BFE39E` | Brillo superior |
| `spike-mint` | `#E3FADA` | Fondo del icono / superficies |
| `spike-ground` | `#C9E4C2` | Sombra en el suelo |
| `spike-cream` | `#FDFDFA` | Fondo general |

Modo oscuro sugerido: fondo `#0B1A12`, superficie `#12261A`, el cactus sin cambios (el contorno `#052E1E` se mantiene; si no contrasta, añadir un halo `#E3FADA` de 2 px).

---

## 2. Cómo usar los prompts

- Los prompts están en **inglés** porque los generadores (ChatGPT/DALL·E, Midjourney, Ideogram, Flux, Recraft) responden mejor así. Cada uno es autocontenido: cópialo tal cual.
- **Adjunta siempre `spike-logo-original.png` como imagen de referencia** (en ChatGPT: súbela con el prompt; en Midjourney: `--sref <url> --cref <url>`). Es lo que garantiza que el cactus sea *el mismo*.
- Pide fondo transparente o fondo plano y luego recorta. Para iconos, genera a **1024×1024** y yo derivo todos los tamaños (no hay que generar cada tamaño por separado).
- Ideal a medio plazo: vectorizar el cactus a SVG (Recraft o Illustrator *Image Trace*) para que todos los tamaños salgan nítidos. Ver imagen **A0**.

Bloque de estilo que llevan todos los prompts (ya incluido en cada uno):

> *Style: exact same character as the reference image — a kawaii saguaro cactus mascot named SPIKE with a rounded trunk, two raised arms, short straight spikes, vertical oval eyes and a small gentle smile. Flat vector illustration, thick uniform rounded outline #052E1E, body #88D445, left-side shade #5FBB47, small vertical texture marks #2A7B20, soft highlight #BFE39E top-left. Clean, friendly, minimal, no gradients except the soft shading, no text unless specified.*

---

## 3. Lista completa

Leyenda: **🎨 Generar** = necesita IA · **⚙️ Derivar** = se obtiene recortando/escalando el logo o un master, sin IA.

### A. Masters (lo primero)

**A0 · Cactus aislado en vector (master)** · 🎨/⚙️ · SVG + PNG 2048×2048 transparente
Base de todo lo demás. Mejor vectorizar el logo original; si se genera:
```
Recreate the cactus character from the reference image exactly, isolated on a fully transparent background, centered, no text, no ground shadow, no app-icon container. Flat vector illustration suitable for SVG tracing, clean closed shapes, thick uniform rounded outline #052E1E, body #88D445, left-side shade #5FBB47, small vertical texture marks #2A7B20, soft highlight #BFE39E top-left, short straight spikes in #052E1E, vertical oval eyes and a small gentle smile. Square 1:1, 2048x2048.
```

**A1 · Wordmark "SPIKE" solo** · ⚙️ · SVG. Recortar del logo o rehacer con fuente *Nunito Black* en `#052E1E`. No generar con IA (deforma letras).

**A2 · Lockup horizontal (cactus + SPIKE a la derecha)** · ⚙️ · SVG/PNG. Montaje de A0 + A1 para cabeceras de la app y la web.

**A3 · Versión monocromo** · ⚙️ · SVG en `#052E1E` y en blanco (para fondos oscuros, marcas de agua, sellos en documentos).

### B. Icono de la aplicación

**B0 · Icono master 1024×1024** · 🎨
```
App icon, 1024x1024, square canvas. A rounded squircle tile with soft mint background #E3FADA and a very subtle inner gradient to #D4F5C8 at the bottom, gentle drop shadow. Inside, the exact cactus character from the reference image, centered, filling about 70% of the tile, cut off flat at the bottom edge of the tile like in the reference app icon. Style: kawaii saguaro cactus mascot, rounded trunk, two raised arms, short straight spikes, vertical oval eyes, small gentle smile. Flat vector, thick uniform rounded outline #052E1E, body #88D445, shade #5FBB47, texture marks #2A7B20, highlight #BFE39E. No text. Crisp edges, readable at 16 px.
```

**B1 · Icono de app en todos los tamaños** · ⚙️ (desde B0)
- macOS `.icns`: 16, 32, 64, 128, 256, 512, 1024 (con @2x).
- Windows `.ico`: 16, 24, 32, 48, 64, 128, 256.
- Linux (PNG hicolor): 16, 22, 24, 32, 48, 64, 128, 256, 512.
- PWA/web: 192, 512, y *maskable* 512 (cactus al 60 % con margen de seguridad).
- iOS/Android si algún día hay app móvil: 180, 167, 152, 120 / adaptive icon 432 (foreground A0 + background `#E3FADA`).

**B2 · Icono simplificado para tamaños pequeños (16–32 px)** · 🎨
A 16 px los ojos y espinas se empastan; conviene una versión reducida.
```
Ultra-simplified pixel-friendly version of the cactus character from the reference image, designed to be readable at 16x16 and 32x32 pixels. Only the trunk and two raised arms, 4 short spikes total, two dot eyes, no smile, no texture marks, no shading. Thick outline #052E1E, flat fill #88D445, on transparent background. 1:1, render at 512x512.
```

**B3 · Icono de barra de menú / bandeja del sistema** · 🎨 · plantilla monocroma (macOS *template image*, Windows tray)
```
Monochrome template icon of the cactus character silhouette from the reference image: trunk with two raised arms and 4 short spikes, solid single color black on transparent background, no inner details except two small eye cut-outs. Must read clearly at 18x18 px. 1:1, 512x512.
```

### C. Favicon y web

**C1 · Favicon** · ⚙️ (desde B2): `favicon.ico` (16/32/48), `favicon.svg`, `apple-touch-icon.png` 180, `safari-pinned-tab.svg` (desde B3).

**C2 · Open Graph / tarjeta al compartir el sitio de docs** · 🎨 · 1200×630
```
Social share card, 1200x630, warm cream background #FDFDFA with a very subtle mint grid pattern #E3FADA. Left side: the exact cactus character from the reference image, large, waving with both arms, small soft ground shadow #C9E4C2. Right side: empty space reserved for a title (leave it clean, no text). A few small floating rounded chips in mint and green suggesting AI specialists (tiny icons: chart, stethoscope, megaphone, code brackets). Flat vector, thick rounded outlines #052E1E, body #88D445, shade #5FBB47. Friendly, professional, uncluttered.
```
Después yo añado el texto real ("SPIKE · Open-source specialist AI that runs on your laptop") con la tipografía de marca.

### D. GitHub

**D1 · Social preview del repositorio** · 🎨 · 1280×640 (GitHub recomienda margen de 40 px)
```
GitHub social preview image, 1280x640, keep all important content inside a centered 1200x560 safe area. Background: soft gradient from cream #FDFDFA to mint #E3FADA. Center-left: the exact cactus character from the reference image, confident and friendly, standing on a small soft shadow #C9E4C2. Around it, in a gentle arc, 8 small round badges each with a tiny line icon (chart, stethoscope, megaphone, code, scales of justice, atom, graduation cap, shield), outlined #052E1E on mint fill. Right side left empty for title text. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47, texture marks #2A7B20. No text.
```

**D2 · Banner de cabecera del README** · 🎨 · 1600×400 (tema claro) + variante oscura
```
Wide README header banner, 1600x400, background cream #FDFDFA. On the left third, the exact cactus character from the reference image waving. The rest of the banner is clean empty space for the SPIKE wordmark and tagline (no text in the image). A faint row of tiny cactus-spike shapes along the bottom edge as a decorative border in #C9E4C2. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. Minimal and professional.
```
Variante oscura: mismo prompt cambiando `background cream #FDFDFA` por `background deep forest #0B1A12` y `#C9E4C2` por `#1E3A28`, y añadiendo `thin light mint #E3FADA halo around the character outline for contrast`. Se sirven con `<picture>` + `prefers-color-scheme`.

**D3 · Diagrama de arquitectura del README** · ⚙️ — lo hago en SVG/Mermaid con la paleta (orquestador al centro, especialistas alrededor). No generar con IA: debe ser exacto.

**D4 · GIF/captura de demo** · ⚙️ — grabación real de la app cuando exista. Nada inventado.

**D5 · Avatar de la organización/usuario GitHub y de redes** · ⚙️ (desde B0, 500×500).

### E. Instaladores

**E1 · Fondo de ventana DMG (macOS)** · 🎨 · 660×400 (y @2x 1320×800)
```
macOS DMG installer window background, 1320x800, cream #FDFDFA background. Left area: empty spot for the app icon (leave a soft mint circle #E3FADA, 260 px). Right area: empty spot for the Applications folder (another soft mint circle). Between them a hand-drawn style curved arrow in #052E1E pointing right. Bottom-left corner: the small cactus character from the reference image peeking up and waving. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text.
```

**E2 · Instalador Windows (NSIS/MSI)** · 🎨
- Imagen lateral de bienvenida 164×314 (NSIS) / 493×312 (WiX dialog):
```
Vertical installer side panel image, 164x314 aspect, background gradient from mint #E3FADA (top) to green #88D445 (bottom). The exact cactus character from the reference image at the bottom center, waving upward, cut off flat at the bottom edge. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text. Render at 4x (656x1256).
```
- Cabecera 150×57 / banner WiX 493×58: ⚙️ desde A2.
- `.ico` del instalador: ⚙️ desde B1.

**E3 · Linux (AppImage/.deb/Flatpak)** · ⚙️ — iconos hicolor de B1 + captura para la ficha de Flathub.

### F. Aplicación

**F1 · Splash / pantalla de carga** · 🎨 · 1024×1024 transparente (se centra sobre el fondo de la app)
```
Splash screen illustration, 1:1, transparent background. The exact cactus character from the reference image, centered, with both arms raised in a cheerful "ready" pose, eyes slightly closed in a happy expression, tiny sparkle shapes around the top spikes in #88D445. Soft ground shadow #C9E4C2. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47, texture marks #2A7B20, highlight #BFE39E. No text.
```
Animación: las espinas aparecen una a una mientras se cargan los modelos (Lottie/CSS, lo hago yo sobre A0).

**F2 · Avatar del asistente en el chat** · ⚙️ (cara del cactus recortada de A0, círculo 64/128 px) — y estado "pensando":
```
Close-up avatar of the cactus character from the reference image, head and upper trunk only, inside a circle with mint background #E3FADA, eyes looking up thoughtfully, one arm raised touching its chin. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text. 1:1, 512x512.
```

**F3 · Estados vacíos (empty states)** · 🎨 · 3 ilustraciones 800×600 transparente
- Sin conversaciones:
```
Empty-state illustration, transparent background, 4:3. The exact cactus character from the reference image sitting next to an empty speech bubble outlined in #052E1E, waving hello. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47, highlight #BFE39E. Minimal, lots of whitespace. No text.
```
- Sin modelos descargados:
```
Empty-state illustration, transparent background, 4:3. The exact cactus character from the reference image holding a small download arrow box outlined #052E1E with mint fill #E3FADA, looking hopeful. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. Minimal. No text.
```
- Error / sin conexión:
```
Empty-state illustration, transparent background, 4:3. The exact cactus character from the reference image looking slightly confused, one arm scratching its head, a small unplugged cable next to it outlined #052E1E. Still friendly, not sad. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. Minimal. No text.
```

**F4 · Onboarding (3 pantallas)** · 🎨 · 1200×800 transparente
1. "Corre en tu ordenador":
```
Onboarding illustration, transparent background, 3:2. The exact cactus character from the reference image standing on top of a simple laptop outlined #052E1E with mint screen #E3FADA, waving. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text.
```
2. "Especialistas que colaboran":
```
Onboarding illustration, transparent background, 3:2. The main cactus character from the reference image in the center, slightly larger, surrounded by four smaller identical-style cactus characters each wearing a tiny accessory (glasses, stethoscope, headset, graduation cap), all connected by soft dotted lines #2A7B20 to the center one. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text.
```
3. "Tus datos se quedan contigo":
```
Onboarding illustration, transparent background, 3:2. The exact cactus character from the reference image hugging a small padlock outlined #052E1E with mint fill #E3FADA, content and protective. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text.
```

**F5 · Iconos de interfaz (UI)** · ⚙️ — usar un set libre (Lucide, MIT) con trazo 2 px redondeado en `#052E1E`. No generar con IA: hacen falta en SVG consistentes.

### G. Documentación

**G1 · Logo y favicon del sitio de docs** · ⚙️ (A2 + C1).
**G2 · Portadas de sección (Guía rápida, Modelos, API, Entrenamiento)** · 🎨 · 1600×500 — una por sección con este patrón:
```
Documentation section header, 1600x500, cream background #FDFDFA. On the right, the exact cactus character from the reference image [ACCIÓN]. Left two-thirds empty for a title. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47, texture marks #2A7B20. No text.
```
`[ACCIÓN]`: Guía rápida → `running forward with a small rocket outlined #052E1E`; Modelos → `standing next to a shelf of small labeled boxes in mint #E3FADA`; API → `holding a plug and a socket connecting them`; Entrenamiento → `lifting a tiny dumbbell, determined smile`.

---

## 4. Familia de especialistas

Regla común para que sean una familia y no otros personajes: **mismo cactus, mismo verde, mismo contorno**; cada especialista solo añade **un accesorio** y **un color de acento** en el fondo del squircle. El catálogo definitivo lo fija el hilo *Construir SPIKE* (aún no está cerrado); estos son los 12 que propongo y se actualizarán si cambia.

Plantilla (sustituye `[ACCESORIO]` y `[ACENTO]`):
```
App icon for a specialist AI model, 1024x1024. Rounded squircle tile with a soft pastel background in [ACENTO] and a subtle drop shadow. Inside, the exact cactus character from the reference image (same shape, same green #88D445, same thick outline #052E1E, same vertical oval eyes and small smile, same short spikes), centered, cut off flat at the bottom edge of the tile, [ACCESORIO]. The accessory is drawn in the same flat style with the same #052E1E outline and uses the accent color. Do not change the cactus color or proportions. No text. Readable at 32 px.
```

| # | Especialista | `[ACCESORIO]` | `[ACENTO]` (fondo) |
|---|---|---|---|
| 0 | **Spike** (orquestador / general) | `wearing a tiny conductor headset microphone and holding a small baton, confident` | `mint #E3FADA` |
| 1 | **Spike Finance** | `holding a small rising bar chart with an upward arrow, a tiny gold coin on one spike` | `soft gold #FFF1C2, accent #E0A800` |
| 2 | **Spike Medicine** | `wearing a stethoscope around its trunk, a small white cross badge on one arm` | `soft red #FFE1E1, accent #E5484D` |
| 3 | **Spike Marketing** | `holding a small megaphone, little sparkle lines coming out` | `soft pink #FFE0F0, accent #E93D82` |
| 4 | **Spike Code** | `wearing small round glasses, a pair of code brackets </> floating beside it` | `soft blue #DCEBFF, accent #3E7BFA` |
| 5 | **Spike Legal** | `holding a small balanced scales of justice` | `soft slate #E6E8F0, accent #5B6478` |
| 6 | **Spike Science** | `holding a small round flask with bubbling liquid, a tiny atom orbit above its head` | `soft teal #D6F5F2, accent #12A594` |
| 7 | **Spike Math** | `holding a small pencil, tiny symbols π and ∑ floating around` | `soft indigo #E4E2FF, accent #6E56CF` |
| 8 | **Spike Education** | `wearing a small graduation cap with tassel, holding an open book` | `soft orange #FFE8D6, accent #F76B15` |
| 9 | **Spike Data** | `holding a small pie chart, a tiny magnifying glass on one arm` | `soft cyan #D8F3FC, accent #0090C7` |
| 10 | **Spike Writing** | `holding a large fountain pen like a staff, a small paper scroll at its base` | `soft lilac #F1E4FA, accent #9D5BD2` |
| 11 | **Spike Business** | `wearing a tiny necktie, holding a small briefcase` | `soft brown #F2E8DE, accent #A0703C` |
| 12 | **Spike Security** | `holding a small shield with a keyhole` | `soft dark green #D9EDE0, accent #1B6B3A` |

Por cada especialista se derivan (⚙️): icono 1024 → tamaños 16–512, avatar circular de chat 128, y badge para la tarjeta del modelo en Hugging Face.

**H · Model card de Hugging Face (portada por modelo)** · 🎨 · 1280×640
```
Hugging Face model card banner, 1280x640, background soft gradient from cream #FDFDFA to [ACENTO]. Left side: the specialist cactus character from the reference image, [ACCESORIO], standing on a soft ground shadow #C9E4C2. Right side empty for the model name. Flat vector, thick rounded outline #052E1E, body #88D445, shade #5FBB47. No text.
```

---

## 5. Orden recomendado

1. A0 (vectorizar) y B0 → con eso derivo B1, C1, D5, F2, A2, A3.
2. D1 y D2 para que el repo se vea bien desde el primer push.
3. Los 13 iconos de especialista (misma sesión del generador, misma referencia, para que no varíe el estilo).
4. F1, F3, F4, E1, E2, G2, H.

Total a generar con IA: **A0 (opcional), B0, B2, B3, C2, D1, D2 (+oscura), E1, E2, F1, F2, F3 ×3, F4 ×3, G2 ×4, 13 especialistas, 13 portadas H** ≈ 45 imágenes. Todo lo demás (≈60 archivos de tamaños, favicons, .icns/.ico) se deriva automáticamente.

Cuando tengas imágenes generadas, súbelas al proyecto y las proceso a todos los formatos en `spike/brand/`.
