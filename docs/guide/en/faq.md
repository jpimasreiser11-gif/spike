# Frequently Asked Questions & Troubleshooting (FAQ)

Language: [Español](../es/faq.md) | **English** · [Guide Index](README.md)

This page documents every diagnostic check emitted by `spike doctor` (`spike/cli.py` and `spike/runtime/hardware.py`) and every user-facing error message (G24): **what it means**, **probable cause**, and **what to do** to recover cleanly.

---

## 1. `spike doctor` Diagnostic Checks

Run `.venv/bin/spike doctor` (or `.venv/bin/spike doctor --json` / `--strict`) to inspect your hardware, the local `llama-server` binary, and installed GGUF models.

### `hardware`
- **What it means**: Inspects the CPU model (`CPU`), physical/logical cores, SIMD flags (`cpu_flags`: `avx2`, `avx512f`, `neon`), total and available `RAM`, and operating system/architecture (`OS`, `apple_silicon`).
- **Probable cause**: Informational diagnostic check performed by `spike doctor` or `spike doctor --json`.
- **What to do**: Confirm that your machine has at least 8 GB of total RAM (16 GB recommended) and sufficient free memory before starting `llama-server`.

### `recommendation`
- **What it means**: Computes the recommended quantization (`quant`, `Q4_K_M` or `Q8_0` on ≥ 32 GB RAM), context window (`context`), KV cache type (`kv_cache_type`, `q8_0`), CPU `threads`, and `gpu_layers`.
- **Probable cause**: Conservative starting profile derived from total RAM and Apple Silicon Metal availability.
- **What to do**: Use these values as a safe baseline or run `spike tune` / `spike bench` to measure your specific hardware.

### `llama_server`
- **What it means**: Reports the resolved path to the `llama-server` binary (from llama.cpp) or `not found` when missing.
- **Probable cause**: `llama-server` is not in `PATH`, `~/.spike/bin/`, or `SPIKE_LLAMA_SERVER`.
- **What to do**: Run `./install.sh` (or `.\install.ps1` on Windows), install `llama.cpp`, or set `SPIKE_LLAMA_SERVER=/path/to/llama-server`.

### `models`
- **What it means**: Lists every local `.gguf` model in `~/.spike/models/` along with its architecture (`arch`), file size (`file_gb`), KV cache size (`kv_cache_gb`), and `estimated_total_gb` (including `0.5` GB runtime compute overhead).
- **Probable cause**: Local GGUF header inspection without loading weights into RAM.
- **What to do**: Ensure `estimated_total_gb` fits comfortably within your `available_ram_gb`.

### `Less than 8 GB RAM: expect slow generation; close other apps.`
- **What it means**: The machine has less than 7.5 GB of total system RAM.
- **Probable cause**: The `Qwen3.5-4B Q4_K_M` base model needs ~3.6 GiB of anonymous resident RAM on top of the OS.
- **What to do**: Close memory-heavy applications before starting the local engine, lower the context window in Settings › Engine, or use an external provider.

### `CPU without AVX2 detected: llama.cpp will run, but several times slower.`
- **What it means**: On Linux x86_64/AMD64, the processor does not advertise the `avx2` instruction flag in `/proc/cpuinfo`.
- **Probable cause**: Older x86 CPU or a virtual machine configured with a generic virtual CPU model lacking AVX2 passthrough.
- **What to do**: If running inside a VM (KVM/QEMU/Proxmox), switch the VM CPU type to `host` to expose AVX2; otherwise expect slower prompt processing.

### `CPU only: context set to 8K because long prompts are slow without a GPU; raise it in Settings if your CPU is fast.`
- **What it means**: When running on CPU only (`gpu_layers == 0`), SPIKE caps the default recommended context at 8192 tokens even if 16+ GB of RAM is present.
- **Probable cause**: On a 4-core CPU, a 32K prompt fits in RAM (3.6 GiB anonymous) but takes ~1.5 h to the first token, whereas 8K remains interactive.
- **What to do**: Keep the 8192 context on CPU-only machines, or raise it manually in Settings › Engine on a high-core-count CPU or GPU.

### `downloaded without a SHA-256 check`
- **What it means**: The model manifest next to the `.gguf` file has `unverified: true` (`[downloaded without a SHA-256 check]`).
- **Probable cause**: The model was downloaded with `--allow-unverified` or placed manually without a verified SHA-256 digest.
- **What to do**: Re-download the official verified model with `spike models pull qwen3.5-4b` so its SHA-256 digest is checked and recorded.

### `No local models yet. Run: spike models pull`
- **What it means**: `spike doctor` found no `.gguf` files in `~/.spike/models/`.
- **Probable cause**: SPIKE was just installed and the base model has not been downloaded yet.
- **What to do**: Run `spike models pull qwen3.5-4b` in the terminal or complete the first-run setup wizard in the desktop app.

### `no local model (run: spike models pull)`
- **What it means**: Strict mode failure (`spike doctor --strict`): exits with code `1` because no local GGUF model is installed.
- **Probable cause**: An installer or readiness check ran `spike doctor --strict` (without `--no-model-check`) before downloading weights.
- **What to do**: Run `spike models pull qwen3.5-4b` first, or pass `--no-model-check` if only checking for the `llama-server` binary.

### `llama-server was not found (install llama.cpp or set SPIKE_LLAMA_SERVER)`
- **What it means**: Strict mode failure (`spike doctor --strict`): exits with code `1` because the `llama-server` binary could not be located.
- **Probable cause**: `llama-server` is not installed on `PATH` or under `~/.spike/bin/`.
- **What to do**: Install `llama.cpp` (`brew install llama.cpp` on macOS or run `./install.sh`) or set `SPIKE_LLAMA_SERVER` to the binary path.


---

## 2. User-Facing UI and API Error Messages (G24)

Every server error code or message is translated in the UI with a clear explanation and recovery action (never exposing internal tracebacks or host absolute paths):

| Server Code / Message | What it means, probable cause, and what to do (UI message) |
|---|---|
| `reverse_authorization` | Confirm that you own the reference or have permission to use it. |
| `reverse_vision_required` | An image needs a vision provider. Choose another provider or use the address of a page on this computer. |
| `reverse_url` | Only pages on this computer are opened: http(s) on localhost or 127.0.0.1, with no username or password. |
| `reverse_path` | Choose an existing .html file inside the project or workspace, with a relative path and no symbolic links. |
| `reverse_image_size` | The image must be between 64 and 4096 pixels on each side. |
| `reverse_browser_missing` | There is no browser to read the page: install Playwright and a Chromium, or set SPIKE_CHROMIUM. |
| `reverse_capture_failed` | The page could not be opened. Check that the local server is running and the address responds. |
| `reverse_invalid_output` | The model did not return an HTML page. Try again or use another provider. |
| `reverse_failed` | The provider or the browser failed. Nothing was saved. |
| `reverse_busy` | A generation is already running. |
| `reverse_expired` | The preview expired or was already used. Start again. |
| `reverse_changed` | The provider or project changed after the preview. Start again. |
| `reverse_files_blocked` | This external provider may not receive your files. Allow it in Settings › Providers. |
| `reverse_provider_blocked` | The provider is blocked by the paid-request permission or a monthly limit. Check Settings › Providers. |
| `reverse_context` | The request does not fit the model's context. |
| `reverse_file_missing` | The file no longer exists. |
| `reverse_unknown_project` | The project no longer exists. |
| `reverse_unknown_provider` | The provider no longer exists. |
| `subtitles_invalid` | Invalid subtitles: check timing, overlaps, text and limits. |
| `subtitles_limit` | File exceeds limits: 10 minutes, 250 MB, 1000 segments or 4096 \u00d7 2160 resolution. |
| `subtitles_unsupported` | Plain text only: subtitle styling and positioning are not supported. |
| `subtitles_split` | Splitting requires two words and at least two milliseconds. |
| `subtitles_path` | Choose a relative path without symbolic links inside the project. |
| `subtitles_source` | No supported media file was found at that path. |
| `subtitles_whisper` | whisper-cli is missing. Install whisper.cpp separately and configure its model in Voice. |
| `subtitles_ffmpeg` | ffmpeg is missing. SRT/VTT editing is still available. |
| `subtitles_ffprobe` | ffprobe is missing and is needed to inspect the video or audio. |
| `subtitles_wav` | Audio must be at most 10 minutes; direct WAV input requires mono PCM16 at 16 kHz. |
| `subtitles_command` | The local program failed or timed out. Check models, codecs and libass for subtitle rendering. |
| `subtitles_video` | A video is required and subtitle timing must fit its duration. |
| `device_lab_approval` | Confirm that Device Lab may open the page in a headless browser. |
| `device_lab_android_approval` | Confirm using adb before touching the Android device. |
| `device_lab_url` | Enter an http:// or https:// address without spaces or a user name. |
| `device_lab_host` | That address is not on this computer. Use localhost, 127.0.0.1 or [::1], or allow the host for this run. |
| `device_lab_hosts` | Allowed hosts are plain names or IP addresses: no scheme, port, path or wildcard. |
| `device_lab_profile` | Choose at least one profile from the list. |
| `device_lab_custom` | Invalid custom profile: a name of up to 40 characters, width and height from 200 to 4000 px, scale from 1 to 4. |
| `device_lab_browser` | Device Lab needs Playwright and a Chromium (pip install 'spike-ai[motion]' and python -m playwright install chromium, or SPIKE_CHROMIUM). |
| `device_lab_android` | The Android device serial is not valid, or adb returned too much data. |
| `device_lab_busy` | Device Lab is already testing another page. Wait for it to finish. |
| `subtitles_approval` | Approve the local operation before running it. |
| `file path leaves the project or uses a symbolic link` | The path leaves the project or uses a symbolic link. |
| `too many project notes to export` | Too many project notes to export. |
| `invalid project notes or note budget exceeded` | Project notes are invalid or exceed the limit. |
| `invalid project note (kind/text)` | Invalid project note (kind or text). |
| `project notes need a memory store` | Project notes require a memory store. |
| `design system not found` | The design system was not found. Refresh the list or select another one in Design. |
| `skill not found` | The skill was not found. Refresh the skills list or check its name. |
| `built-in skills can be disabled, not deleted` | Built-in skills cannot be deleted; disable them with their toggle in Settings › Skills. |
| `not a zip archive` | The file is not a valid ZIP archive. Choose a .zip file. |
| `not a SPIKE project archive (zip)` | The file is not a SPIKE project archive (.zip). Export a project from SPIKE and try again. |
| `connector not found` | The connector was not found. Refresh the list in Settings › Connectors. |
| `id or preset is required` | Enter an identifier or choose a provider preset before saving. |
| `base_url must be an http(s) URL` | The provider address must start with http:// or https://. Fix the URL and try again. |
| `provider not found` | The provider was not found. Check Settings › Providers or select another provider. |
| `the built-in local provider cannot be removed` | The built-in local provider cannot be removed; you can change the default provider in Settings. |
| `request refused: it comes from another web site` | Request refused because it comes from another web site. Use the interface opened directly on this computer. |
| `a confirmation must name the order in the body and the X-Spike-Confirm header` | The order confirmation is missing. Confirm the order from its card in the chat or in Finance. |
| `no open order with that id` | There is no open order with that ID. Refresh the simulated portfolio. |
| `no such order` | That order does not exist. Refresh the order list in Finance. |
| `save an API key for the chosen exchange first` | No API key is saved for this exchange. Save the key in Settings › Finance first. |
| `invalid report` | The data report is not valid. Check the query blocks and export it again. |
| `format must be docx or pdf` | The report format must be Word (docx) or PDF. Choose one of those two formats. |
| `an image is not valid base64` | A chart image in the report is invalid. Regenerate the chart and try again. |
| `invalid Content-Length header` | The upload size header is invalid. Send the file again. |
| `project not found` | The project no longer exists. Select another project or create a new one. |
| `file not found` | The file was not found. Check the name or refresh the project file list. |
| `invalid file path` | The file path is not valid. Use a relative path inside the project, without '..' or symbolic links. |
| `invalid file path: a .git folder is not part of a project's files` | Files inside a .git folder cannot be saved in a project. Choose another path inside the project. |
| `project is not a branch` | This project is not a branch. Fork the project into a branch first to compare or merge it. |
| `conversation not found` | The conversation no longer exists. Select another one in the sidebar or start a new chat. |
| `Unknown proof section / Sección de prueba desconocida` | Unknown proof package section. Select only the available sections and export again. |
| `'before' must be a user message of this conversation` | A branch can only start from one of your messages in this conversation. Choose a user message. |
| `message not found` | The message was not found in this conversation. Reload the chat and try again. |
| `item not found` | The Evolution item no longer exists. Refresh the list. |
| `failure not found` | The failure record was not found. Refresh the failures tab in Evolution. |
| `an optimisation is already running` | A prompt optimization is already running. Wait for it to finish or cancel it before starting another. |
| `job cancelled` | The job was cancelled. You can start it again whenever you want. |
| `not found` | The requested resource was not found. Refresh the view and try again. |
| `turn on “Use my corrections to retrain” in Settings → Evolution first` | Turn on “Use my corrections to retrain” in Settings › Evolution first. |
| `turn on the personal adapter in Settings → Evolución first` | Turn on the personal adapter in Settings › Evolution first. |
| `that chat is not marked` | That conversation was not marked for the personal adapter. Refresh the list. |
| `that example is not in the personal set` | That example is no longer in the personal set. Refresh the list in Evolution. |
| `the previous adapter file is gone` | The previous adapter file is no longer on disk. Install the accepted adapter again. |
| `memory not found` | The memory note no longer exists. Refresh the list in Memory. |
| `folder not found` | The indexed folder is no longer registered. Refresh the list in Memory › Folders. |
| `that folder does not exist or cannot be read` | That folder does not exist or cannot be read. Check the path and permissions on this computer. |
| `that path is not a folder` | The path points to a file, not a folder. Enter the path of a folder. |
| `choose a folder, not a whole disk` | A whole disk cannot be indexed. Choose a specific folder inside your documents. |
| `SPIKE's own data folder cannot be indexed` | SPIKE's internal data folder cannot be indexed. Choose another folder. |
| `entry not found` | The glossary entry no longer exists. Refresh the glossary. |
| `topic not found` | The study topic no longer exists. Refresh the list in Tutor. |
| `relation not found` | The graph relation no longer exists. Refresh the memory graph. |
| `no pending permission request with this id` | This permission request was already answered or expired. Continue in the conversation. |
| `no pending question with this id` | This question was already answered or expired. Continue in the conversation. |
| `No local model configured. Download one with `spike models pull` or set it in Settings.` | No local model is configured. Download one with `spike models pull` or select it in Settings. |
| `llama-server not found. Install llama.cpp (e.g. `brew install llama.cpp`) or set SPIKE_LLAMA_SERVER.` | llama-server was not found. Install llama.cpp (`brew install llama.cpp`) or set SPIKE_LLAMA_SERVER. |
| `a tuning run is already in progress` | A local engine tuning run is already in progress. Wait for it to finish. |
| `Parallel Prototypes saves files, which needs tools: turn them on in Settings` | Parallel Prototypes saves files and needs tools: turn them on in Settings. |
| `each approach must save at least one file (a step with 'deliverables')` | Each approach must save at least one deliverable file. Add a deliverable to each plan. |
| `no such prototype run` | That prototype run no longer exists. Open another one or start a new run. |
| `this run is still building` | This prototype run is still building. Wait for it to finish before discarding it. |
| `Parallel Minds needs a prose answer: it cannot be combined with a Forge blueprint or an answer contract (JSON)` | Parallel Minds needs a prose answer: turn off the Forge blueprint or the JSON answer contract. |
| `Parallel Minds runs 2 to 4 minds` | Parallel Minds runs 2 to 4 minds. Choose between 2 and 4 in the selector. |
| `replace_from needs an existing conversation` | Editing and resending a message requires an existing conversation. Send a new message. |
| `replace_from must be a user message of this conversation` | You can only edit and resend one of your own messages in this conversation. |
| `a Forge task cannot also have an answer contract` | A Forge task cannot be combined with a JSON answer contract. Turn one of them off. |
| `this blueprint saves files, which needs tools: turn them on in Settings` | This Forge blueprint saves files and needs tools: turn them on in Settings. |
| `data_app_expired` | The table session expired or was already applied. Generate the app again from Creator. |
| `data_app_conflict` | The source file changed on disk since the preview opened. Reopen the file. |
| `data_app_approval` | Approve the operation before creating the app or saving changes to the file. |
| `data_app_project` | The selected project no longer exists. Choose another project. |
| `data_app_invalid` | The file or proposed edits are not valid. Check that the file is a CSV, TSV, JSON or Excel file inside the project. |
| `describe what the task is` | Describe the desktop task you want to run before starting. |
| `no pending desktop action with this id` | This desktop action was already answered or finished. Continue in the desktop panel. |
| `screenshot not found` | The screenshot is no longer available. Screenshots are only kept during the active task. |
| `Desktop actions are off. Turn them on in Settings → Desktop.` | Desktop actions are off. Turn them on in Settings › Desktop first. |
| `history_filter` | The search filters are not valid. Check the query and the selected scope. |
| `project_not_found` | The project selected for search no longer exists. Choose another scope. |
| `invalid_target` | Select between 1 and 4 valid specialist and provider combinations in Lab. |
| `invalid_cases` | The Lab test cases are not valid. Use a JSON list with prompt and optional expected fields. |
| `one_probe_target` | The capability probe tests a single target at a time. Leave only one target selected. |
| `expired_quote` | The Lab quote expired or was already used. Click Preview again before executing. |
| `changed_quote` | The provider configuration changed since the preview. Compute a new preview in Lab. |
| `provider_blocked` | The provider is blocked by the paid-request permission or a monthly limit. Check Settings › Providers. |
| `unknown_run` | The Lab run no longer exists. Select another one from the Lab history. |
| `Launcher only` | This action is only available from the SPIKE desktop launcher. |
| `Adapter unavailable` | One of the selected adapters is not yet available for download. Uncheck it and try again. |
| `Installation busy or insufficient resources` | A download is already running or there is not enough free disk space or RAM. Free up space and try again. |
| `Local same-origin JSON request required` | This action requires a local request from the SPIKE window itself. |
| `Spike View is not running: turn it on in Settings first` | Spike View is not running. Turn on the browser in Settings › Connectors first. |
| `Spike View is not running` | Spike View is not running. Turn on the browser in Settings › Connectors first. |
| `this script is being replayed: stop the replay first` | This script is currently being replayed. Stop the replay before deleting it. |
| `there is no such script` | The browser script no longer exists. Refresh the script list. |
| `the replay is not waiting for that answer` | The replay is no longer waiting for that answer. Check the current script status. |
| `unknown specialist` | The specified specialist does not exist. Choose a specialist from the catalog. |
| `job not found` | The background job already finished or does not exist. Refresh the job queue. |

---

## 3. Frequently Asked Questions (FAQ)

### Does SPIKE ever send my files or chats to the internet?
No. By default everything runs on `127.0.0.1` via `spike-local` and local SQLite under `~/.spike/`. Zero external connections are made unless you explicitly download a model, approve a `web_fetch` tool call, or configure and enable a remote provider. Verified by `tests/test_no_network_g29.py`.

### Why is a specialist marked `β` (instruction profile)?
Because no specialist is claimed to beat the base model until its trained LoRA adapter passes its statistical acceptance gate without general-knowledge forgetting (at most 1.5 points drop on MMLU-Pro general). Today **Medicine** has passed its gate (+35.07 points on medicine, −0.62 on general); the remaining specialists run as instruction profiles on the base model.

### What should I do if a model download is interrupted?
Re-run `spike models pull qwen3.5-4b` or click retry in the first-run setup wizard: SPIKE resumes from the `.part` file using HTTP `Range` requests and verifies the full SHA-256 digest before installation.
