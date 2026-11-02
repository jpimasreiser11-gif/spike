# Research / Investigación

Open **Research / Investigación** in the top bar. The selected project determines the source folder; without a
project, paths refer to the configured SPIKE workspace. The panel does not call a provider or read a file on opening.
Results remain in the panel until you download the evidence JSON. Closing the panel discards that UI state.

## Notebook

Open a saved or temporary chat, then download its `.ipynb` from Research. Only that conversation is exported. Python
fences become proposed cells without outputs. Recorded `python` and `data_python` calls become separate cells, with
plain-text tool results linked only by an unambiguous tool name and call ID in the same message, after the call.
Other/unlinked tool results remain plain raw cells. Other code languages remain in the original Markdown.

The export never executes code. Execution counts stay `null`: SPIKE's isolated tools did not run in a shared Jupyter
kernel. Recorded results can be truncated and do not prove a script will run again in the notebook environment.
Review code before execution and provide any required data/dependencies yourself. No images, HTML output bundles,
credentials from provider configuration, or unrelated chats are added. Content already in the chat is exported as-is;
this is not a secret-redaction service. Raw output cells are restricted to `text/plain` for conversion.

Format: nbformat 4.5, with unique cell IDs and Python kernel metadata, generated with the standard library.
[Jupyter's official format description](https://nbformat.readthedocs.io/en/latest/format_description.html) defines the
schema. No nbformat runtime dependency is required.

## Paper Rebuilder

1. Select one PDF relative to the workspace/project and click **Review text and destination**.
2. Check extracted pages, provider/model, estimated price and permissions. Extraction uses pypdf locally, without OCR.
3. **Send and analyze once** makes one guarded model request, without tools. The source material is marked private.
4. Read the method/equation/table fragments and their page, character offsets and original byte SHA-256. An empty
   category means no usable fragment was identified, not proof that the paper contains none.
5. **Review plan in Forge** opens the existing editable plan. Nothing executes until **Approve and run**. The plan
   references the file, its hash and extracted spans. It deliberately does not paste private quotations into ordinary
   plan instructions; Forge's file tools and provider guards govern reading during execution.

The plan requires checking the source hash, documenting missing materials, building a bounded experiment and comparing
actual observations. It is a proposal to reproduce a paper, not a completed reproduction. Complex equations and tables
may lose their layout; inspect the original PDF. Provider quality and real-paper reproduction remain unmeasured.

## Contradiction Map

Select 2–4 PDF, UTF-8 TXT or MD files. After reviewing the local preview, explicitly request analysis. Each candidate
row contains two exact quotes from different documents and the model's explanation. Page numbers are one-based;
start/end offsets are zero-based Python character offsets in the extracted page. For repeated text, the first exact
occurrence is used. Case changes, fabricated quotes, missing sources and malformed results reject the entire analysis.

Matching a quote verifies its location, **not** the truth of the claim or whether the two studies really contradict.
Differences in time, population, methods and scope still need human review. The model can miss contradictions.

## Limits and privacy

- At most 2 MiB per source, 80 PDF pages per source, 20,000 extracted characters across the selection. No silent text
  truncation. Encrypted PDFs, blank/scanned-only PDFs, unsupported types, traversal and symlink paths are rejected.
  These parsing caps are not a sandbox for hostile PDFs; pypdf still parses/decompresses content before some checks.
- The preview is local, has one use, expires after five minutes and binds source hashes, project root and provider
  settings/model. At most ten previews are held in process memory. No preview or result database is created.
- Analysis checks source bytes before and after the provider call. Changes require a new preview. Provider failures
  require another explicit attempt; there is no automatic retry/fallback or automatic adapter activation.
- External providers require existing file-sharing and paid-call permissions. Existing monthly guards apply; previews
  display estimated cost at configured prices, which is not a spending cap. Unknown prices remain unknown.
- A request has at most 3,000 output tokens and a 120-second provider timeout. The declared provider context is checked
  when available; an undeclared context capacity is not measured by this feature. No model starts or downloads here.
- Notebook exports are capped at 8 MiB of serialized source messages and served as private downloads. No Jupyter kernel
  is included or launched.

## Español

Abre **Investigación** en la barra superior. Los archivos se leen desde el proyecto seleccionado o la carpeta de
trabajo. Primero revisa el texto extraído y el proveedor; solo el botón **Enviar y analizar una vez** realiza la
solicitud. Las citas muestran página, posición y SHA-256. Las contradicciones son candidatas, y Paper Rebuilder entrega
un borrador que se revisa y aprueba en Forge. No confirma que el artículo esté reproducido.

El cuaderno exporta exclusivamente el chat abierto, sin ejecutar código ni inventar resultados. El texto de las
conversaciones puede contener información privada: revisa el archivo antes de compartirlo. Los resultados y la vista
previa no se guardan como historial; descarga el JSON si quieres conservar las evidencias. PDFs escaneados necesitan
OCR externo y el formato de tablas/ecuaciones puede perderse durante la extracción.

## Validation

`python -m pytest -q tests/test_research.py tests/test_research_server.py` exercises exact quotes, tampered files,
scope/path limits, provider guards and notebook provenance using scripted providers and tiny original fixtures.
`cd web && npx vitest run src/research.test.tsx` checks local-only opening, bilingual strings and preview invalidation.
The full `web/e2e/smoke.mjs` includes real-browser research and Forge-review flows against the scripted test server.
These checks do not certify model quality, hostile-PDF isolation, clean installs, real Jupyter UI or other operating
systems. The task report contains the actual latest test results.
