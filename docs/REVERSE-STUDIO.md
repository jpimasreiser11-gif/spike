# Reverse Studio (A20)

Reverse Studio turns a reference you own into **one editable HTML/CSS file**. Open **Settings → Design / Diseño** and
go to **Reverse Studio / Estudio inverso** (below the design systems). It is not part of the chat and runs nothing
until you click Generate.

## What it takes

| Reference | Needs | What reaches the model |
|---|---|---|
| **Screenshot** (PNG, JPEG or WebP, resized to 1536 px in the browser, 2.8 MB at most) | a provider that supports **vision** (the manual declaration in *Settings → Providers*, `VisionSetting`) | the image itself |
| **Page on this computer** (`http(s)://localhost…`, `127.0.0.1`, `[::1]`, `*.localhost`; no credentials) | Playwright for Python and a Chromium (`SPIKE_CHROMIUM`, else Playwright's, else an installed Chrome or Edge); **works with the local model** | the layout and computed styles, with placeholder text |
| **HTML file of the project** (a relative `.html` path inside the project folder or the workspace) | the same browser | the same as a page |

An image with a provider that has no vision is refused before anything is sent, with the message "needs a vision
provider, or use the address of a page on this computer" (API code `reverse_vision_required`). Any other address
(another host, `file:`, a private network address, a URL with a password) is refused (`reverse_url`) and never opened.
"The user's own project preview" means a page served on localhost (a dev server) or a `.html` file of the project, which
is served to the browser from its own folder only (a link or `../` that leaves the folder returns 404).

## The confirmation

A checkbox, **"I own this reference or have permission to use it"**, is required. The button stays disabled without
it, changing the reference clears it, and the API refuses any request without `"authorized": true` with **HTTP 400**
(`reverse_authorization`) before looking at anything else. The confirmation is saved with the result (see below): the
statement, when it was given and which reference it covered (the SHA-256 of an image, or the address or path of a
page). It is a record of what the user declared; SPIKE cannot check it.

## What leaves the computer: the existing consent, not a new one

`POST /api/reverse/preview` sends nothing. It checks the request, records the confirmation and returns what would be
sent, to which provider, whether that is remote, the estimated cost of the text and a `blocked` reason if any.
`POST /api/reverse/generate` then runs once from that preview (single use, 5 minutes, bound to the provider's
settings: a changed provider is refused with 409). Whether the provider may receive it is decided by the checks
`GuardedProvider` already makes for every file and image (`spike/providers/guard.py`):

- the provider must declare **vision** (`capabilities.vision`) for an image;
- a paid provider needs **Allow paid requests**, and the **monthly limits** must not be reached (`blocked`,
  `blocked_for`);
- a remote provider needs **Send your files' contents to this provider** (`share_files`; `receives_files`), for the
  image *and* for the structure of a page (it is derived from the user's page, so it is treated as file content and
  marked private); otherwise the request is refused (`images_private`, `reverse_files_blocked`);
- the checks run in the preview, again at the start of generate (before the browser opens) and again with the real
  size of the request; `GuardedProvider.stream` applies them a last time and writes the call to the call log.

In the UI an external provider (anything not marked local) first shows "this image / this structure will be sent to X"
with the estimated text cost and a **Send and generate** button; a local provider generates directly because nothing
leaves the computer. The cost covers the text only: image billing depends on the provider.

## Brand assets become placeholders

For a page, the model never sees the page's words. The browser capture (`spike/design/reverse_capture.js`) returns the
boxes (position and size), the computed styles that differ from the browser's defaults, and only the *length* of each
text; the description (`describe`) writes a lorem-style text of that length instead (or the user's own text, line by
line, if they typed some). Not in the description: the text, `src`/`srcset`/`href`/CSS `url()`, `alt` and `title`
attributes, class names, ids, and any font that is not a generic or very common system family. Images, SVG and media
are lines marked as a neutral gray box of the same size.

For both paths the answer is rewritten (`clean_document`) before it is shown or saved:

- only a fixed list of HTML tags and attributes survives; `<script>`, `<iframe>`, `<link>`, `<object>`, `<video>`,
  comments and every `on…` handler are dropped, one `<style>` is kept, and `@import`, `@font-face` and every `url()`
  are removed or replaced by a gray gradient;
- every `<img>` keeps only its size and gets a gray placeholder source (a `data:` SVG); every inline `<svg>` becomes a
  gray box (logos are not redrawn); every link becomes `#…`;
- the names the page calls itself (title and site name, logo labels, `alt` of images, the copyright line) and the names
  the user typed under "names that must not appear" are replaced by "lorem" in text, attributes and styles. Words that
  are only words (home, menu, search…) and anything in the user's own text are kept. **For an image there is no page to
  read the names from**: the instruction not to transcribe text or name anything is in the prompt, and only the names
  the user lists are removed mechanically. A model can still write a brand it recognised in a screenshot.

## The fidelity score

After generating, the page is rendered in the same headless Chromium at the reference's size (JavaScript off, every
request refused) and compared with the reference: the screenshot of the page that was read, or the user's image.
The browser decodes both (PNG, JPEG, WebP), draws them on white at the same size, and Python compares them with
`spike.design.reverse.similarity`:

```
score = 1 - (sum of |R, G, B differences of every pixel|) / (3 × pixels × 255)      0.0 … 1.0
```

The result reports the score of **that run** with its size and what it was measured against, and nothing else. It is
a pixel measure: 1.0 means every pixel is identical, a white page against a mostly white reference scores high, and it
says nothing about the quality of the code, the structure or the text. If there is no browser the page is still
saved and the result says "similarity was not measured" with the reason; for a page there is no result without a
browser. The score is not saved anywhere beyond that run's record.

## The result

The HTML is shown in a sandboxed frame in the panel (the same isolation as the artifacts panel), can be opened in the
**artifacts panel**, edited in a text box and saved. It is written to `reverse/reverse-<date>-<id>.html` in the chosen
project (the project's files) or in the workspace, next to `reverse-<date>-<id>.json`: the confirmation, the source,
the provider and model (no keys), what was sent, the score, what was removed and the names replaced. `PUT
/api/reverse/file` saves edits only to an existing `reverse/*.html` of that project or the workspace.
All routes are for this computer only (the same rule as speech and desktop settings) and one job runs at a time.

## Tested

`pytest tests/test_reverse.py tests/test_reverse_api.py` (86 tests; the ones that need a Chromium use
`SPIKE_CHROMIUM`, else Playwright's, and skip cleanly where there is none, like `tests/test_dev_diagnostics.py`):

- the confirmation: every request without `true` is refused with 400, nothing runs, nothing is written;
- an image with a non-vision provider is refused; no image reaches a provider unless it has vision, paid permission,
  file permission and no monthly limit reached, and nothing is sent by the preview; a provider changed after the
  preview, an expired or used preview and a blocked preview send nothing (scripted provider records its requests);
- the description and the cleaned answer contain no brand text, sources, links or scripts (with a model that copies
  everything it can); the user's own text is used and its names kept;
- URL, path and image-header validation; a project page is served only from its folder;
- real Chromium: the capture of a localhost fixture page, the render and the score (identical page ≥ 0.999, blank and
  black pages lower, a JPEG reference, scripts not run, network refused), from a page to a saved file through the API;
- the saved file, its record, the edit route and its path rules; Vitest for the panel (button disabled until the
  confirmation, the confirmation revoked on change, the vision message, the second click for an external provider);
  the browser smoke (`web/e2e/smoke.mjs`) opens a page on localhost, waits for the measured score and opens the
  result in the artifacts panel.

**Not measured:** how good the generated code is, or how similar it is, with a real model: every test uses a scripted
provider. No real vision model was run, and no paid or remote provider was called.
