# Create, Workflows, Research, and Audio and subtitles

Language: [Español](../es/creator.md) | **English** · [Guide Index](README.md)

![Create, Workflows, Research, and Audio and subtitles](../images/creator.png)

## What it does

Brings together SPIKE's guided production tools: **Create** (templates that become a Forge plan you review before it runs, plus the **Data to app** template for editing tables), **Workflows** (steps chained on a canvas with `{{name}}` variables and conditions), **Research** (evidence with exact quotes checked against the document), and **Audio and subtitles** (`SRT`/`VTT` editing and local transcription).

## Step-by-step usage

1. Click **Create** in the sidebar and pick a template (web page, app, dashboard, document, presentation, animated video, automation…). Answer the questions and click **Prepare the plan**: the Forge plan opens with its steps, files and criteria; change it if you like and click **Approve and run**. The **Data to app** template opens an editable table instead; changes are reviewed and approved with **Approve write** before the original file is touched.
2. Inside **Create**, open **Workflows** to chain inputs, specialists, tools, conditions and outputs. **Check** validates the flow before you save or run it, and each tool asks for permission as it does in chat.
3. Click **Research** in the top bar. Choose **Paper Rebuilder** (one PDF) or **Contradiction Map** (2 to 4 PDF, TXT or MD files), click **Review text and destination**, then **Send and analyze once**. Only quotes that match their source exactly are accepted; you can download the evidence as JSON or review the plan in Forge. **Download .ipynb notebook** exports the open chat without running any code.
4. Click **Audio and subtitles** in the sidebar to import an `.srt` or `.vtt` file (or transcribe a file locally), fix timings and text, split, merge or shift segments, and click **Download**.

## Real limits

- Research sends the text shown to the chosen provider in a single request, with no tools and no OCR: at most 2 MB per file, 80 pages and 20,000 characters in total. An exact quote does not prove that its interpretation is right.
- Transcription needs `whisper.cpp` enabled in the chat's **Image and voice** control (up to 10 minutes and 250 MB); making an MP4 with burned-in subtitles needs `ffmpeg` with libass and `ffprobe`. Importing, editing and exporting `SRT`/`VTT` needs nothing else. See [../../SUBTITLES.md](../../SUBTITLES.md), [../../WORKFLOWS.md](../../WORKFLOWS.md), and [../../STATUS.md](../../STATUS.md).

## How to verify

- Run `.venv/bin/python -m pytest -q tests/test_creator.py tests/test_workflows.py tests/test_research.py tests/test_subtitles.py`.
- Run `cd web && npx vitest run src/workflowBuilder.test.tsx src/research.test.tsx src/subtitles.test.tsx`.
