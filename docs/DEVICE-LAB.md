# SPIKE Device Lab (A21) / Laboratorio de dispositivos

Device Lab opens a web app that runs on this computer in six screen profiles (small and large phone, tablet in portrait
and landscape, laptop, desktop) plus the profiles you add, and tells you, per profile, what breaks: console errors,
failed requests, horizontal overflow (and which elements cause it), tap targets under 24 x 24 CSS px and text under 12 px,
with a screenshot, a pass or fail and the reason.

**What it is not.** It *emulates* viewports in the headless Chromium SPIKE already drives (the same launcher as Spike
Motion: `SPIKE_CHROMIUM`, else Playwright's Chromium, else an installed Chrome or Edge). A profile sets the viewport,
the device scale factor, touch, the mobile flag and a user agent of a generic class. It is **not a real-device test**:
phone and tablet browsers differ from this engine in fonts, form controls, scrolling, keyboards and more. The only
thing that comes from a real device is the optional Android screenshot below, and that is only a picture.

## Using it

- **Window**: the sidebar button *Device Lab*. Type the address, pick profiles (and add your own: name, width, height,
  scale, touch), tick the approval, run. The result table opens as a readable report in the artifacts panel
  (isolated page, with the screenshots and the JSON) and the JSON can be downloaded.
- **Agent**: the tool `device_lab` (the Code and Core specialists, and `spike dev`), so you can say "run Device Lab on
  http://localhost:5173/". It asks every time (risk `execute`, `once`; an "allow" policy never skips the question); the
  card shows the address and any extra host. The chat gets a card with the verdict per profile; the model reads a short
  JSON without pictures (at most 5 items per list).
- **HTTP** (this computer only, same-origin): `GET /api/device-lab` (profiles and limits; starts nothing),
  `GET /api/device-lab/android` (`adb devices -l`), `POST /api/device-lab/run` (needs `"approved": true`),
  `POST /api/device-lab/android` (needs `"approved": true`). Routes live in `spike/server/device_lab_api.py`, registered in
  `app.py` with one line. One run at a time (a second one answers 409); a run waits in the same queue as video
  renders (one heavy job at a time, free RAM above the queue's floor).

## Profiles

| id | screen | scale | touch / mobile | user agent |
|---|---|---|---|---|
| `small-phone` | 360 x 640 | 2 | yes | `SpikeDeviceLab/1.0 (Mobile; phone; touch)` |
| `large-phone` | 414 x 896 | 2 | yes | same |
| `tablet-portrait` | 768 x 1024 | 2 | yes | `SpikeDeviceLab/1.0 (Tablet; touch)` |
| `tablet-landscape` | 1024 x 768 | 2 | yes | same |
| `laptop` | 1366 x 768 | 1 | no | `SpikeDeviceLab/1.0 (Laptop; desktop)` |
| `desktop` | 1920 x 1080 | 1 | no | `SpikeDeviceLab/1.0 (Desktop)` |

The user agents name only a class of device (pages that look for `Mobile` or `Tablet` see it); no vendor, browser or
system name is shipped in them, in the profile names or in the checks (a test scans for brand words). Pages that read
`navigator.userAgentData` were not checked. A custom profile takes a name (up to 40 printable characters), width and
height 200 to 4000, scale 1 to 4, touch, mobile (default: the same as touch) and an optional user agent (up to 300
printable ASCII characters). At most 6 custom profiles and 12 profiles per run.

## The address, and where the browser may go

The target must be `http://` or `https://` on this computer: `localhost`, `*.localhost`, `127.0.0.0/8` or `[::1]`,
without a user name or password (the project's own preview server is such an address). Anything else is refused before
a browser starts, unless the user names the host for this run (`allow_hosts`, plain host names or IP addresses: no
scheme, port, path or wildcard; at most 8; the permission card shows them).

The same rule limits the *browser*, not only the first address. Playwright's request routes do not see redirect hops
(tested: a redirect to another host passed through them), so the browser is also started with a dead-end proxy (a local
port that nothing listens on, held by SPIKE during the run) that this computer and the named hosts bypass.
`<-loopback>` is first in the bypass list because Chromium would otherwise send link-local addresses such as
`169.254.169.254` around the proxy (also tested). The result: a redirect, an image, a script or a fetch to any other host
fails in the network layer, nothing is downloaded from it, and the profile lists it under *blocked requests* (not as a
failed request). A page whose own address redirects to another host is an `error` with the host in the reason.
WebSocket attempts to other hosts fail too and show up as console errors.

## The checks

Everything is measured in the page as laid out for the profile, by `spike/dev/device_lab_checks.js` (no model, nothing
is changed in the page). After the page loads, it waits up to 2 more seconds for the network to go quiet.

- **Console errors**: `console.error` messages and uncaught exceptions. The browser's own "Failed to load resource"
  lines are not repeated here; they are the failed requests.
- **Failed requests**: network failures and responses with HTTP status 400 or more (the main page included). Queries and
  fragments are cut from every address in the report.
- **Horizontal overflow**: the document is wider than the viewport (`scrollWidth` over `clientWidth`, more than 1 px).
  The elements listed are the outermost boxes that stick out past the right edge; a box clipped by an ancestor that fits
  (a carousel with `overflow-x: auto`) is not a cause, and `position: fixed` boxes are ignored. When no box sticks out
  (a long word spilling from a box that fits) the innermost spilling element is listed with `kind: "content"`.
- **Tap targets**: links, buttons, form controls, `summary`, `[onclick]` and the `button`, `link`, `checkbox`, `radio`,
  `switch`, `tab` and `menuitem` roles whose box is under 24 x 24 CSS px (WCAG 2.2 target size, minimum), on **every**
  profile, touch or not. Exempt: disabled and hidden controls, boxes of 1 px or less (visually hidden), a link inside
  running text (WCAG's inline exception), and a checkbox or radio whose label is big enough. Spacing exceptions are not
  evaluated.
- **Small text**: an element with text of its own rendered under 12 px.
- **Notes**: on a mobile profile, a page without `<meta name="viewport">` is laid out about 980 px wide by phones, so
  its overflow and tap targets are measured at that width; the profile says so (`no_viewport_meta`).
- Not covered: iframes, shadow DOM, contrast and the rest of accessibility (use Visual Critic for contrast), pages that
  need a login or clicks to reach the problem.

**Verdict.** `pass` when none of overflow, tap targets, small text, console errors or failed requests was found;
`fail` with those reasons, in that order; `error` when the page could not be opened or measured (connection refused,
blocked redirect, 30 s navigation timeout, 60 s per profile, 420 s per run). Lists keep 20 items per category and the
total is always counted. The screenshot is the whole page as a PNG at CSS-pixel size (not device pixels), cut at 4000 CSS
px high and 2400 wide, and left out (with a note) above 3 MB.

## The report

One JSON object (`kind: "device_lab"`, `version: 1`): `url` (no query), `started`, `seconds`, `browser`, `emulated: true`,
`allow_hosts`, `limits`, `summary` (`profiles`, `pass`, `fail`, `error`), `profiles[]` and `android`. Each profile has
`id`, `name`, `kind`, `viewport`, `scale`, `touch`, `mobile`, `user_agent`, `status`, `reasons[]`, `reason` (English),
`http_status`, `title`, `notes[]`, `layout`, `overflow` (with `px`), `tap_targets`, `small_text`, `console_errors`,
`failed_requests`, `blocked_requests` (each `{total, items[]}`), `screenshot` (a data URL) and `seconds`. The window
and the chat card show it in Spanish or English from the codes; the report page also carries the JSON without the
pictures. Reports are not saved by SPIKE (nothing is written to the workspace); download the JSON from the window.
What the model gets is private like file contents (it can include text snippets of your page).

## Android (optional)

If `adb` is already on the PATH (`shutil.which`) and `adb devices -l` lists a device or emulator, the window shows it
(states other than `device`, such as `unauthorized`, are shown but cannot be chosen). Listing runs `adb devices -l` and
nothing else (adb may start its own background server, as it always does). **Taking the screenshot and opening the
address on the device happen only after a separate approval** (`android.approved` in the route, its own checkbox in the
window, the permission card of the tool says it will use adb). The steps, each recorded with whether it worked:
`adb -s SERIAL reverse tcp:PORT tcp:PORT` (so the device's `localhost` reaches this computer; only for a local address),
`adb -s SERIAL shell am start -a android.intent.action.VIEW -d '<address, quoted for the device shell>'`, a wait of 3 s,
`adb -s SERIAL exec-out screencap -p` (must start with the PNG signature), and `reverse --remove` at the end, also when
a step failed. Serials are checked (`[A-Za-z0-9._:]` first, then also `-`; 80 characters) and adb is never run through a
shell. No checks run on the device: only the picture of its screen. SPIKE never downloads adb, an SDK or an emulator and
never starts an emulator; without adb or a ready device the report says so (`no_adb`, `no_device`).

## Files

`spike/dev/device_lab.py` (profiles, host rule, the run, adb, the tool), `spike/dev/device_lab_checks.js`,
`spike/server/device_lab_api.py`, `web/src/components/DeviceLab.tsx` and `.css`, `tests/test_device_lab.py`,
`web/src/deviceLab.test.tsx`. Small edits elsewhere: `launch()` in `spike/motion/render.py` takes optional extra browser
flags; the tool is registered in `diagnostic_tools`, `dev_tools` and the `core` and `code` specialists; the sidebar
button and the chat card are one line each in `App.tsx` and `AssistantMessage.tsx`; es and en strings in `i18n.ts`.

## What was tested, and what was not

`tests/test_device_lab.py` (87 tests; the 22 that start Chromium skip cleanly when none is found, using `SPIKE_CHROMIUM`
or Playwright's or an installed Chrome; nothing is downloaded, and the fixture pages are served from `127.0.0.1`):

- Profiles and the host rule: the six profiles, no brand words, custom profiles valid and invalid, 7 accepted and 28
  refused addresses (other hosts, private and link-local ranges, `file:`, `javascript:`, user names, look-alike host
  names), the named host (only that host), which requests the browser may make.
- The tool: asks once even when allowed, denies other hosts and bad profiles before asking, android and named-host cards,
  registered for `code`, `core`, `spike dev` and in `known_tools`, goes through the job queue, a denied call runs nothing
  (not even `adb devices`), no browser or no Playwright is a clear refusal.
- The routes: local only and same-origin, approvals (browser and Android separately), the choices reach the run, error
  codes the app translates, one run at a time, the status route starts no program.
- A fake `adb` script on the PATH (recorded calls; nothing real runs): listing, states, the quoted URL, reverse and cleanup,
  failed steps, no device, a bad screenshot, no adb.
- In a real headless Chromium: a page with a 700 px block, a 16 px button, 10 px text, a console error and a 404 image:
  overflow found on exactly the two phone profiles (340 and 286 px, culprit `#wide`), the tap target and the small text
  on all six, the console error and the failed request on all six; a clean page passes all six; a scrolling strip passes
  and a long word is reported as spilling text; tap-target exemptions; a page without viewport tag; uncaught exceptions;
  emulation applied (user agent, scale, touch points, width read back by the page, also for a custom profile); blocked
  hosts listed and never requested; redirects to another host, to a link-local address, through a local hop, and for an
  image; a closed port; screenshot width and height; one JSON shape; the tool through the agent loop; the route end to end.
- `web/src/deviceLab.test.tsx` (15 vitest tests): the report page escapes hostile text and accepts only PNG data URLs, the
  verdict lines, the chat card, the window (nothing starts on open, approval first and revoked when the address changes,
  custom profiles, the report opens in the panel, Android needs its own approval), es and en keys match and every
  permission reason and error code is translated. The browser smoke test (`web/e2e/smoke.mjs`) runs the tool with its
  permission card, opens the report in the isolated panel, and runs the window against the app itself.

Not tested or not claimed: real phones and tablets, a real Android device or emulator (the fake adb shows only which
commands SPIKE sends; real `adb` flags were not run here), Windows and macOS runs of the browser tests (CI runs them
where Chromium is installed), engines other than Chromium, speed or memory use, any model's ability to use the tool well.

```sh
.venv/bin/python -m pytest -q tests/test_device_lab.py
LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q tests/test_device_lab.py
cd web && npx vitest run src/deviceLab.test.tsx
```

## Resumen en español

Device Lab abre una app web que corre en este ordenador en seis perfiles de pantalla (móvil pequeño y grande, tablet
vertical y horizontal, portátil, escritorio) y los que añadas, y dice por perfil qué falla: errores de consola,
peticiones fallidas, desbordamiento horizontal (y qué elementos lo causan), objetivos táctiles menores de 24 x 24 px CSS y
texto menor de 12 px, con captura, resultado correcto o con problemas y el motivo. **Emula** pantallas en el navegador
de escritorio sin ventana que ya usa SPIKE: no es una prueba en un dispositivo real. Solo se abren direcciones de este
ordenador (localhost, 127.0.0.1, [::1]) salvo que nombres un host para esa ejecución; el navegador solo puede conectar con
la app, este ordenador y esos hosts (lo demás se bloquea y se lista, redirecciones incluidas). Cada ejecución pide
permiso; si ya tienes `adb` y hay un dispositivo o emulador listado, se muestra, y su captura y abrir la dirección en él
piden un permiso aparte. SPIKE nunca descarga adb, SDK ni emuladores. Informe en JSON y en vista legible en el panel de
artefactos, en español e inglés. Lo que se probó y lo que no está arriba.
