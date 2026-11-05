# SPIKE v0.1: release review (L2, part 1)

Date: 2026-11-02. Reviewed: `main` at aac98aa (includes I3 and M10) plus the fixes of this review. Offline: nothing was
fetched; the only network used was 127.0.0.1. Nothing is ticked below without the command, file or run id next to it.
This is an engineering review, not legal advice. Parts that wait on other people are marked pending.

## 1. Checklist (PLAN.md section 27)

| Item | Status | Evidence |
|---|---|---|
| Measured numbers on a 16 GB x86 machine, no GPU | done | `evals/results/bench-x86-16gb-20261018/` (4-core x86 VM, 15.7 GB, no swap): generation 6.2 / 5.1 / 2.1 tok/s at 1K / 8K / 32K, peak anonymous memory 3,654 to 3,675 MiB; 32K is not interactive on 4 cores (STATUS, "The 16 GB target"). Also I3 run 41449693467 on 16 GB Windows and Linux runners: 4.9 and 7.9 tok/s |
| An accepted adapter, or an honest status | honest status done; accepted adapter pending (M2) | The only trained adapter, medicine, was rejected (`evals/results/20261020-202442/summary.md`, STATUS "First trained adapter: medicine, REJECTED"). `README.md` ("Not claimed here") and `THIRD_PARTY.md` ("No adapter has been released yet") say so |
| Install in 3 commands or fewer, tested on clean macOS, Linux and Windows | done on clean GitHub runners; not on a user's own machine | `git clone ... && cd spike`, then `scripts/install.sh --yes` (or `install.ps1 -Yes`): 2 commands. Installers workflow runs 39160997172 (macOS 26 arm64, Ubuntu 24.04, Windows 2025) and 39421918616 (Windows PowerShell 5.1, Ubuntu without Homebrew); each passed `spike doctor --strict` and answered with the real model (STATUS). Native installers with the real model: run 41449693467 passed on Windows and Linux; macOS was refused by the app's own 8 GiB RAM guard (7 GiB runner), so the macOS installer with the real model is not tested |
| CI green on GitHub | pending | The last CI run in STATUS is 39097864750 (commit dcbfd3f, 2026-10-18). No green run on the release commit is recorded, and this review could not query GitHub. Waits on a CI run of the commit to be released |
| A real 30 to 60 s demo recording | pending (L1) | `git ls-files` has `docs/DEMO.md` and `web/e2e/demo.mjs` (the recorder) and no recording |
| Adapters and model cards on Hugging Face | pending (M2, L3) | The card generator exists (`pytest tests/test_model_card.py`); nothing is published and no adapter is accepted |
| Release notes | pending | `packaging/RELEASE-NOTES.md` is a private draft ("not a public launch") and `CHANGELOG.md` has `[0.1.0] unreleased`. Final text waits on the founder |
| Final security and license review | done for what could be read offline, with open items (section 5) | Sections 2 to 4 below. Tests: `pytest -q tests/test_security_review.py tests/test_collect_licenses.py` |
| E1 to E6, EV3, EV8 (evolution) | done | `pytest -q tests/test_evolution.py tests/test_evolution_levels.py tests/test_personal_adapter.py tests/test_prompt_regression.py tests/test_strategy.py`: 161 passed in 109 s |
| EV6 personal adapter | pending (built, never trained on real weights) | PLAN marks it built; Apple silicon only; effect not measured (STATUS) |
| Cheap additions, skills-as-code items | not re-checked one by one | Covered only by the full suite result below |

Full suite on the reviewed tree (`python -m pytest -q` with llama-server, Chromium, Playwright MCP and the converter
available): `2808 passed, 8 skipped in 1065.45s (0:17:45)`. Lint: `ruff check .` gave `All checks passed!`. The new test
files under a C locale without UTF-8 mode (`LC_ALL=C LANG=C python -X utf8=0 -m pytest -q`) pass.

Failed items: none. A failed item would be listed here with its run id.

## 2. Security findings

Method: read every route group (`spike/server/*_api.py`, reverse, device lab, workflow, recorder, Studio, Forge,
data apps, packs and skills import, launcher and setup, `packaging/`, the I3 driver and workflow, and M10's SQL
sandbox) against SECURITY.md, then wrote small local probes for each suspicion. A finding is confirmed only when a probe or
a test showed it. Probes are in the reviewer's scratch folder; what matters is kept as tests in
`tests/test_security_review.py` (46 tests). Run against the tree before the fixes, the S1 to S4 tests give 33 failed and
12 passed; after, all pass.

| ID | Severity | Where | Scenario | Confirmed | State |
|---|---|---|---|---|---|
| S1 | Medium | `spike/projects.py:30-37` (`clean_path`), `spike/tools/builtin.py:136-140` (`write_file`); sink `spike/forge/prototypes.py:110` | A shared project archive (`/api/projects/import`), a file upload, a pack or an approved `write_file` plants `.git/config` with `core.fsmonitor=<program>`. Parallel Prototypes runs git in that folder; `git status` runs the program with the user's rights | Yes: a probe created a marker file by running `git status`; tests fail without the fix | Fixed: any `.git` path part is refused (any case, trailing dot or space, `GIT~1`) |
| S2 | Medium | `spike/server/app.py:556-560` (pack import) | A pack's custom connector carries `env` (`UV_DEFAULT_INDEX`, `NODE_OPTIONS`, `npm_config_registry`), secret definitions and links. The enable confirmation shows only the command, so what runs differs from what the user approves | Yes: the env reached the started process; test fails without the fix | Fixed: a pack connector is read through the same model as the Connectors form (`CustomConnectorIn`) |
| S3 | Medium | `spike/server/app.py:686,711`, `spike/server/state.py:269,305`, `spike/providers/registry.py:75` | A provider at `http://localhost.example.com/v1` or `http://127.0.0.1@example.com/v1` was "local" by address prefix, so it received file contents without "send files", escaped paid-call and limit rules, and a local provider moved to another host stayed local | Yes: probe and test | Fixed: local means the host is this computer (`localhost`, `*.localhost`, loopback IP); the flag is recomputed on read and on PATCH |
| S4 | Medium | `spike/tools/builtin.py:286-300` (`web_fetch`) | `http://100.100.100.200/latest/meta-data/` (Alibaba Cloud metadata), a Tailscale node 100.64.x.x, or an IPv4-mapped IPv6 form passed the "public address" check because 100.64.0.0/10 is not "private" | Yes: test reaches the mock server without the fix | Fixed: only globally routable, non-reserved, non-multicast addresses |
| L1 | Low | `spike/server/app.py:374-384` | The Host/Origin allow-list compares host names only, so a page served from another port on `localhost` passes it. JSON routes still refuse non-JSON bodies (422), so the reach is the few raw-body POST routes (`/api/projects/import`, `/api/pack/import`) | Yes (probe: `Origin: http://127.0.0.1:9999` reaches the handler; `https://evil.example` gets 403) | **Open on purpose**, see "L1 stays open" below |
| L2 | Low | `spike/tools/builtin.py:296` | `web_fetch` resolves a name to check it, and the HTTP client resolves it again: DNS rebinding between the two is not covered | No (reasoned, not run); stated in SECURITY.md | **Fixed**: the name is looked up once, every answer must be public, and the request goes to one of those addresses with the name kept for `Host`, the TLS server name and the certificate check (`_resolve_public`, `_pinned` in `spike/tools/builtin.py`). Redirects are still not followed, so each target is a new call through the same check. Behind an environment proxy the proxy connects and cannot be pinned: a second lookup right before must agree, and the window inside the proxy stays (SECURITY.md). Tests: `tests/test_security_review_low.py` (`test_web_fetch_connects_to_the_address_it_checked`, `..._on_a_real_socket`, `..._verifies_the_certificate_against_the_name_not_the_address`, `test_behind_a_proxy_...`) |
| L3 | Low | `spike/runtime/models.py:95-99` | `spike models pull` continues without a SHA-256 when the Hub gives none (the desktop setup refuses: `spike/launcher/setup.py:72`) | Read, not run | **Fixed**: with no SHA-256 from the Hub `download` raises `UnverifiedDownload` and saves nothing; `spike models pull --allow-unverified` downloads, prints a warning and writes `<model>.gguf.manifest.json` with `unverified: true` (every download gets a manifest; `spike doctor` shows it). The desktop setup still refuses. Tests: `tests/test_cli.py` (`test_download_without_a_hub_hash_is_refused_unless_the_user_allows_it`, `test_models_pull_refuses_when_the_hub_gives_no_hash_and_says_how_to_override`, `test_doctor_marks_a_model_downloaded_without_a_hash_check`) |
| L4 | Low | `spike/proof.py:25,164` | The proof package copies a provider's `base_url` as typed, so credentials in the address (`user:key@host`, `?key=`) end up in a zip people share | Read, not run; a probe of httpx showed its status errors quote the full URL | **Fixed**: `strip_url_secrets` (`spike/runtime/urls.py`) keeps scheme, host, port and path of any address written into a proof package (providers, call details), the call log (on write and on read, so rows an earlier version wrote are clean too), an error event from a provider, and a pack export. Tests: `tests/test_security_review_low.py` (`test_the_proof_package_has_no_credentials_from_a_provider_address`, `test_the_call_log_stores_and_returns_addresses_without_credentials`, `test_a_pack_exports_connector_addresses_...`) |
| L5 | Low | `spike/connectors/manager.py:42,177` | Header values typed literally in a connector (not as `{SECRET_NAME}`) are stored in the SQLite file in clear; only placeholders go to the key store | Read, not run | **Fixed**: a header whose name looks like a credential and has a literal value goes to the key store (`connector:<id>:HEADER_<NAME>`), the row keeps `{HEADER_<NAME>}` and declares it as a secret; done when the connector is added and, for rows an earlier version saved, on the first read (`ConnectorManager._vault_headers`). A key store that refuses leaves an old row as it was. Tests: `tests/test_security_review_low.py` (`test_a_literal_secret_header_goes_to_the_key_store_not_to_the_database`, `test_rows_stored_by_an_earlier_version_are_migrated_when_read`, ...) |
| L6 | Low | `spike/design/library.py:56` | The `url(` check of imported tokens does not see CSS escapes (`u\72l(`). Artifacts run in a sandboxed iframe whose CSP blocks network loads, so the effect is small | Read, not run | **Fixed**: the check reads the text after CSS escapes are decoded (`css_text`), and also refuses `image-set(`, which loads from a string. Comments are not stripped before the check on purpose (an escaped slash or a string can fake a comment). Tests: `tests/test_security_review_low.py` (`test_tokens_with_css_escapes_cannot_hide_what_the_check_refuses`, `test_ordinary_tokens_with_escapes_still_pass`) |
| L7 | Low | `spike/projects.py:35` | `clean_path` rejects `:` only in the first segment; on Windows `dir/file.txt:stream` makes an alternate data stream | Read, not run (Windows only) | **Fixed**: `:` is refused in every part of a project path; `is_git_name` also sees `.git::$INDEX_ALLOCATION`. Tests: `tests/test_security_review_low.py` (`test_a_project_path_has_no_colon_in_any_segment`, `test_a_git_folder_reached_through_a_data_stream_name_is_still_git`, `test_a_file_upload_and_an_archive_cannot_name_a_data_stream`) |
| L8 | Low | `.github/workflows/*.yml`, `packaging/real_model_check.py:128-146` | Actions are pinned by tag (`@v4`), not by commit. The I3 `source` check accepts any successful run of `release.yml`, from any branch (it checks name and path, not branch) | Read | **Fixed**: all 46 `uses:` lines are pinned to the full commit of their tag with the tag in a trailing comment; `check_source_run` accepts only a run whose `head_branch` is `main` (not from a pull request) or a push of a version tag, and refuses a fork's run. Tests: `tests/test_security_review_low.py` (`test_every_action_is_pinned_to_a_full_commit_with_its_tag_in_a_comment`, `test_the_same_action_has_the_same_commit_in_every_workflow`), `tests/test_real_model_check.py` (`test_source_run_must_come_from_main_or_a_tag_push`, ...) |

Checked, no finding: loopback bind and the `/v1` and `/mcp` access rule (`spike/server/openai_api.py:74-87`); the setup
routes (same-origin JSON from loopback, `spike/server/setup_api.py:20-31`) and `this_computer` on desktop, media, device
lab, Reverse Studio, memory and settings routes; zip import limits and the pack import of skills; the hash-pinned llama.cpp
staging (`packaging/stage_llama.py`, tests in `tests/test_launcher_packaging.py`); no `shell=True`, `os.system`, `eval`,
`pickle` or `yaml.load` anywhere in `spike/`, `packaging/`, `training/`, `scripts/`, except `run_command` (a shell
command by design, shown to the user on an approval card, `spike/dev/tools.py:173-180`) and the vendored upstream skill
script `webapp-testing/scripts/with_server.py:71`; artifact isolation (`sandbox="allow-scripts"`; a probe with a
`javascript:` link did not run in Chromium); M10's SQL sandbox (`ATTACH`, `PRAGMA`, `load_extension`, `VACUUM`, `VACUUM
INTO` are all refused, runaway recursion and sorting stop at 2.0 s, pathological `LIKE` and `GLOB` finish at once; guard
test `test_the_sql_sandbox_cannot_write_a_file_with_vacuum_into`); the I3 driver (clean child environment, argv lists
only, loopback only, scrubs secrets and paths before printing or saving) and its workflow (numeric run id checked before
use, inputs passed through `env`, read-only token, actionlint pinned by SHA-256).

Not covered: real Windows and macOS sandbox behaviour (no such machine), fuzzing, and a line-by-line review of the
web app beyond the existing audit `docs/audits/2026-10-17-web-bundle-rea.md`.

### Dependency vulnerability audit (2026-11-05)

`npm audit` (npm registry advisories) on `web/` and `pip-audit 2.10.1` (PyPI and OSV advisories) on the 93 packages of
the development environment (`pip freeze --exclude-editable`, `-r freeze.txt --no-deps --disable-pip`):

| Package | Where | Advisory | Action |
|---|---|---|---|
| dompurify 3.4.16 | shipped UI: sanitizes Markdown (`web/src/components/Markdown.tsx`) | critical: `SAFE_FOR_TEMPLATES`, `IN_PLACE` and xhtml `PARSER_MEDIA_TYPE` bypasses (SPIKE uses none of these options) | updated to 3.4.17; `npm audit --omit=dev`: 0 |
| pypdf 6.21.1 | optional `docs` extra: reading PDFs into memory, Paper Rebuilder | 10 CVEs: crafted PDFs cause long runtimes, large memory use or an infinite loop | floor raised to `pypdf>=6.21.4` |
| certifi 2026.7.22 | dependency of httpx, not declared by SPIKE | PYSEC-2026-4320: a distrusted root CA in the bundle | not pinned: a fresh install takes the current certifi; build machines must not reuse an older one |
| vite 5.4.10, vitest 2.1.4 | development only (dev server, test runner); not in the built UI | dev-server request forgery and path traversal, test-runner RCE when its UI/API server listens | updated to the fixed 5.x/2.x releases (5.4.21, 2.1.9); the advisories still open need vite 8 and vitest 5 (majors), left for a later upgrade: CI runs `vitest run` with no server, and the dev server should not be exposed beyond localhost |

### Follow-up on the Low findings (2026-11-02)

L2 to L8 were closed after the review above. Each has tests that failed on the tree before its fix: with the source changes taken out and the tests kept, 54 of the new or changed tests failed (37 in `tests/test_security_review_low.py`, 7 in `tests/test_cli.py`, 10 in `tests/test_real_model_check.py`). L5 note: no form of today's app writes a header (`CustomConnectorIn` has no such field), so the rows that could hold a literal value are those an earlier version or a caller of `add_custom` saved; both are covered. The action commits were read with `git ls-remote --tags https://github.com/actions/NAME refs/tags/vN` (and `vN^{}`) because the session's `gh` token had no access to those repositories; the six tags are lightweight, so there was nothing to dereference: checkout v4 = `11d5960`, setup-python v5 = `a26af69`, setup-node v4 = `49933ea`, upload-artifact v4 = `ea165f8`, download-artifact v4 = `d3f86a1`, cache v4 = `0057852`. The `head_branch`, `event` and `head_repository` fields the new `source` check reads are those of GitHub's REST run object; it was written from the documented fields and the existing fixture, not checked against a live response from this repository.

**L1 stays open.** The Host/Origin allow-list compares host names only, and the fix (compare scheme, host and port) would refuse the developer's own UI: `npm run dev` serves the UI from the Vite dev server on another port (`web/vite.config.ts`, which proxies `/api` to `127.0.0.1:8740`), so its `Origin` is `http://localhost:5173`. The exposure is as described above (a page on this computer served from another port, and only the raw-body POST routes); revisit it when the dev proxy rewrites the origin or the allow-list can name the dev origin explicitly.

## 3. Secrets scan of the git history

`git log -p --all -U0` over 233 commits on all 26 branches, 180,703 diff lines. Rules: `hf_`, `sk-`, `ghp_`/`gho_`/`github_pat_`,
`AKIA`/`ASIA`, `xox*`, private key blocks, `AIza`, Stripe, GitLab, npm, SendGrid, JWT, credentials in URLs, and
assignments to `*_KEY`/`*_TOKEN`/`*_SECRET`/`*PASSWORD*` with a high-entropy value. Values were never printed. File names
in history were checked for `.env`, `*.pem`, `id_rsa`, `credentials`: none (only the module `spike/store/secrets.py`).

Result: 6 hits, none a real secret.

| Commit | Path | What it is |
|---|---|---|
| 6b8f29e182 | `tests/test_real_model_check.py` | a fake secret the redaction test must hide |
| 4c24cbac40 | `tests/test_reverse.py` | `user:pass@localhost` as an address the SSRF check must refuse |
| 6eb79d71d7 | `tests/test_recorder.py` | a credential-shaped string for the recorder's secret detector |
| 395b45c627 | `tests/test_skill_validation.py` | a fake `api_key = xxxx` and a `BEGIN PRIVATE KEY` line the skill validator must reject (2 hits) |
| 9ee35c6f95 | `scripts/phase0/decontam_check.py` | false positive of the generic rule (code identifiers) |

## 4. License review of what ships

Sources: `importlib.metadata` of the build environment for Python; `web/package-lock.json` with the `license` field of
each `node_modules` package for the web app (the lockfile of the main checkout is byte-identical to this branch's);
license files inside the repository for skills, design systems, fonts and brand. The venv's installed `spike-ai`
metadata is older than `pyproject.toml`, so the Python list is built from `pyproject.toml` (dependencies plus the `docs`,
`data`, `finance`, `motion` extras the release installs).

Result: no GPL, AGPL, SSPL, non-commercial, unknown or missing license among the 64 Python packages, CPython and the 90
production npm packages. Every one of them ships a license file or has its text collected (`INDEX.md` of the collector
shows no "none shipped"). `licenses/third-party/INDEX.md` is generated by `packaging/collect_licenses.py` (2.0 MB, 190
files).

| Component | Ships in | License | Verdict |
|---|---|---|---|
| SPIKE code, 22 skills written for SPIKE, catalogs, `evals/data`, `training/topics` | repo, wheel, bundle | Apache-2.0 | ok. The 22 skills declare Apache-2.0 and carry no upstream marker; their authorship cannot be proven offline |
| 64 Python packages | bundle | MIT 28, BSD 15 (14 BSD-3, 1 BSD-2), Apache-2.0 10, PSF-2.0 3, dual MIT/Apache/BSD 3, MPL-2.0 2 (certifi, orjson), MIT AND PSF-2.0 1, MIT-CMU 1, numpy's BSD/0BSD/MIT/Zlib/CC0 mix 1 | ok. MPL-2.0 files are unmodified; source link and note added to THIRD_PARTY.md |
| CPython 3.12 runtime | bundle | PSF-2.0 | ok; the collector copies its `LICENSE.txt` and records "not found" if a Python lacks it (to confirm on the release runners) |
| 90 production npm packages | `web/dist` | BSD-3 35, ISC 26, MIT 24, OFL-1.1 2, 0BSD, Unlicense, MPL-2.0 OR Apache-2.0 (DOMPurify, used under Apache-2.0) | ok |
| Inter and Nunito fonts | `web/dist/assets` | SIL OFL-1.1 | ok; the text now also travels with the fonts as `/FONT-LICENSES.txt` (wheel and bundle) |
| Playwright wheel (`motion` extra) | bundle, if the driver is collected | Apache-2.0; embeds Node.js (MIT, long list of bundled libraries) | ok; the collector adds the driver's LICENSE, NOTICE and ThirdPartyNotices. Whether PyInstaller collects the 130 MB driver is not checked (no PyInstaller offline) |
| 8 skills copied from obra/superpowers, anthropics/skills, Vercel (via open-design) | `spike/skills/bundled` | MIT x5, Apache-2.0 x3 | ok; license file in each folder; credited in NOTICE (was missing) |
| 20 design systems from open-design | `spike/design/systems` | Apache-2.0 | ok; `LICENSE-open-design` present; no company brand look; credited in NOTICE |
| Brand images, specialist avatars, state illustrations | `web/public` | project's own; derived from the founder's logo with ChatGPT image generation | ok as own work; the generator's terms on output rights are not checkable offline |
| llama.cpp b11709 `llama-server` | desktop bundle | MIT, plus statically linked cpp-httplib, nlohmann/json, xxHash, sha256, rotate-bits, stb_image, miniaudio, subprocess.h (all MIT, BSD-2, public domain, MIT-0 or Unlicense) | ok. The archive carries only the top-level LICENSE (61 entries listed); the vendored libraries' texts, copied from tag b11709 (commit 62318cd), are in `packaging/licenses/llama-vendored.txt` (bundled as `licenses/native/`). llama-server also embeds llama.cpp's web UI (`tools/ui`, fetched prebuilt at build time since `LLAMA_USE_PREBUILT_UI` defaults to on; inferred from the tag's CMake, not checked in the binary). SPIKE never serves it; `packaging/llama_ui_notices.py` derived the notices of its 396 npm packages and 3 vendored libraries from the tag's source and lockfile (static superset, the UI was not built) into `packaging/licenses/llama-ui-npm.txt`: all permissive, dompurify taken under Apache-2.0 |
| AppImage type2-runtime | Linux AppImage | MIT; statically links libfuse (LGPL-2.1), musl, squashfuse, libzstd, zlib | flagged: LGPL. Met as far as engineering can tell (unmodified upstream binary, replaceable with `appimagetool --runtime-file`, source links in THIRD_PARTY.md and the release notes). Whether that satisfies LGPL-2.1 section 6 for a static link is the founder's or counsel's decision |
| PyInstaller bootloader | frozen executables | GPL-2.0 with the PyInstaller exception for non-GPL programs | ok under the exception; text not readable offline |
| pywebview 6.2.1 | macOS and Windows bundles | BSD-3-Clause (per project) | not readable offline: not installed here |
| Inno Setup, appimagetool, actionlint | build tools, not inside SPIKE | Inno Setup terms, MIT, MIT | ok; not readable offline |
| Remotion (`marketing/video`) | not shipped (`marketing` is excluded from the sdist) | Remotion's own license (company-size terms) | flagged: custom, not open source; keep out of the product; already described in THIRD_PARTY.md |
| Qwen models, datasets, MCP servers | downloaded by the user on request, not shipped | Apache-2.0, MIT, per THIRD_PARTY.md tables | Hub license fields not re-read (no network); the app re-checks them at download time against its allowlist |

Documents corrected: `THIRD_PARTY.md` (14 missing Python packages added; `pypdf` is an optional runtime extra, not
development only; the 18 skills written for SPIKE named; MPL, CPython, Playwright driver, llama.cpp vendored libraries,
LGPL runtime reading, what the bundle carries), `NOTICE` (skills, fonts, llama.cpp, the mlx-lm adaptation with its MIT
text; open-design copyright line), `packaging/spike.spec` (bundles `NOTICE` and the collected texts, which it did not
before), `packaging/RELEASE-NOTES.md` (licenses and LGPL source). Versions in the "version checked" column of
THIRD_PARTY.md differ from the build environment for two packages (`duckdb` 1.5.6 against 2.0.0 installed,
`charset-normalizer` 3.5.2 against 3.4.7); the licenses are the same (MIT).

## 5. Open items before the repository goes public

1. ~~A real PyInstaller build with the new spec~~ Done: `Native installers` run 41501251258 (2026-11-02, ee555f0)
   built all three; the installed-app smoke, which now refuses a bundle without LICENSE, NOTICE, THIRD_PARTY.md and
   `third-party/INDEX.md`, counted 199 (macOS), 198 (Windows) and 194 (Linux) license files.
2. Founder's decision on the LGPL libfuse inside the AppImage runtime (section 4).
3. ~~Append the vendored-library notices of llama.cpp tag b11709~~ Done: `packaging/licenses/llama-vendored.txt`
   (copied from the tag; `tests/test_collect_licenses.py` fails if the staged tag changes and the file is not redone).
   The npm packages of llama-server's embedded web UI: `packaging/licenses/llama-ui-npm.txt` (section 4). Building
   llama-server without the UI (`-DLLAMA_USE_PREBUILT_UI=OFF`) would drop them but replace the pinned upstream binaries.
4. Green CI on the release commit. ~~`pip-audit` and `npm audit` with network~~ Done 2026-11-05 (section 2): shipped
   dependencies clean after the dompurify and pypdf updates; dev-only vite/vitest advisories wait for a major upgrade.
5. L1 demo, M2 adapter, L3 Hugging Face publication, final release notes: pending as listed in section 1.
6. The Low findings: L2 to L8 are fixed (section 2); L1 stays open on purpose (the dev server's origin) and does not block v0.1 by itself.
