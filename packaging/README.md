# Desktop launcher (I1)

Run `python -m spike.launcher` in an installed SPIKE environment. It reserves a free IPv4 loopback port, waits for
`/api/health`, and opens pywebview when already installed, otherwise the default browser. No dependencies are added
or installed. In browser mode use **Salir de SPIKE / Quit SPIKE** (closing a browser tab does not stop a server), or
Ctrl-C in the terminal. Closing the native window gracefully stops the HTTP server, owned llama-server and embedding
server and cancels downloads. The OS lock permits one launcher per SPIKE_HOME and releases on crashes.

The first-run wizard checks local free disk and total/available RAM. Its conservative reservation is 6 GiB of disk
plus twice the selected adapter sizes, and 8 GiB total RAM; these are installation guards, not measured inference
requirements. Only **Descargar todo / Download all** contacts Hugging Face. The base model uses the same download,
license and SHA-256 implementation as `spike models pull`, with a mandatory hash and license for the wizard.
Partial files survive interruption; failed checksums are discarded. Completion configures paths without starting
inference. **Más tarde / Later** dismisses this session's wizard for users of external providers.

`spike/launcher/adapters.json` is deliberately empty: every built-in adapter is currently planned in the catalog;
no published repository, revision or checksum has been supplied. Claude can add reviewed entries keyed by specialist
id, each containing `repo`, immutable 40-character commit `revision`, catalog-matching `filename` (e.g.
`spike-code.gguf`), positive byte `size`, `sha256`, and allowed `license`. Until then the wizard explicitly labels
these as instruction profiles with no downloadable adapter. No weights were measured or downloaded for I1.

## Offline PyInstaller staging

Build separately on macOS, Windows and Linux using release tooling with PyInstaller already available. This task does
not install PyInstaller or pywebview and does not add the optional `desktop` extra because dependencies were forbidden.

1. Obtain the appropriate **b11709 CPU** archive from
   https://github.com/ggml-org/llama.cpp/releases/tag/b11709 and the MIT LICENSE from the same tag.
   The six exact asset names and SHA-256 pins live in `stage_llama.py`, verified against the upstream
   [b11709 attestation](https://github.com/ggml-org/llama.cpp/attestations/56945604). Linux pins also match
   `scripts/install.sh`. No hash override is allowed.
2. Stage the local archive, without executing it:
   `python packaging/stage_llama.py ARCHIVE packaging/vendor/TARGET/b11709 --target TARGET --license-file LICENSE`
   TARGET is one of Linux-x86_64, Linux-arm64, Darwin-x86_64, Darwin-arm64, Windows-AMD64, Windows-arm64.
   Staging rejects archive traversal, escaping/cyclic links and colliding flat paths and records hashes for every
   bundled file. Safe in-archive tar library aliases become regular copies, avoiding symlink privileges on Windows.
   Unsupported layouts fail closed and require release review.
3. Build `web/dist` with `cd web && npm run build`, then from the repository root run
   `pyinstaller packaging/spike.spec`. `SPIKE_LLAMA_STAGE` may point to another staging directory.
   The spec verifies the staged file hashes and platform/tag, bundles runtime libraries, LICENSE, manifest, static UI,
   catalog and adapter manifest, and detects pywebview if installed. The launcher selects its bundled llama-server.

The spec was not built with real upstream binaries: native startup, shared-library resolution, macOS bundle behavior
and installer signing remain release checks. DMG, Inno Setup and AppImage wrappers belong to later installer tasks.

## Native installer candidates (I2)

`.github/workflows/release.yml` builds on a pull request affecting packaging, an existing `v*` tag, or a manual run.
The first matrix is **Apple Silicon / macOS 14**, **Windows 2022 runner / x64** and **Ubuntu 24.04 / x86_64**.
These are build/test targets, not a promise of compatibility with every older OS or architecture. Intel Macs,
Windows ARM and Linux ARM need their own runner evidence before announcement.

The build installs PyInstaller 6.22.3 and gguf 0.19.0 only in the disposable CI environment, alongside SPIKE's
existing docs/data/finance/motion extras. macOS and Windows also install pywebview 6.2.1; Linux opens the default
browser. No training dependencies, production weights, keys, paid signing or user accounts are required. The
packaged llama-server is b11709 CPU, verified against I1's SHA pins. This does not establish GPU acceleration,
16-GB performance, model quality, or availability of external programs such as ffmpeg/Blender/Godot.

1. Build the web app and install the declared build tools in an isolated environment.
2. `python packaging/release.py fetch --target TARGET --vendor packaging/vendor/release` downloads the pinned
   llama archive and stages it. Linux additionally fetches appimagetool 1.9.1 and the AppImage runtime asset with
   fixed SHA-256 values; changed bytes fail closed. Nothing runs until checksum validation succeeds.
3. Set `SPIKE_LLAMA_STAGE=packaging/vendor/release/llama` and run
   `python -m PyInstaller --noconfirm packaging/spike.spec`.
4. `python tests/fixtures/make_tiny_gguf.py tests/fixtures/out/package` creates random weights locally. They produce
   meaningless text and cannot be used for quality claims or included as the user's production model.
5. `python packaging/release.py build --target TARGET --version 0.1.0 --commit FULL_COMMIT_SHA
   --vendor packaging/vendor/release --model tests/fixtures/out/package/spike-tiny.gguf --output dist/release`
   wraps the app, installs/extracts that artifact into a disposable location, and executes its frozen entry point.
   The self-test checks loopback health, static UI script availability, catalog/skills, a real four-token inference
   through the bundled runtime and runtime stop. It uses a new SPIKE_HOME, no keyring and no external provider.
   It is **not** a browser interaction, native-window usability test or model benchmark; those belong to I3/L1.
6. After all three runners pass, `assemble` verifies the exact version, source commit, model fixture, required smoke
   results and each artifact's SHA-256 before creating `SHA256SUMS`. Mixed/incomplete/tampered candidates fail.
   CI preserves smoke JSON, llama logs and PyInstaller warnings separately, including on failure.

On Windows, Inno Setup installs per user with no administrator request, creates a shortcut and uninstaller, and
leaves models/projects in SPIKE_HOME untouched. The CI smoke then uninstalls its temporary copy. On macOS the DMG
contains SPIKE.app and an Applications shortcut; the build verifies PyInstaller's ad-hoc signature, mounts the DMG,
copies the installed app out, unmounts and tests that copy. AppImage uses extract-and-run in CI, without FUSE.

### Drafts and publication

A normal manual run (`create_draft=false`) only uploads private workflow artifacts. A version-tag push, or an explicit
manual `create_draft=true` run **on an existing version tag**, creates a **draft**, after all native checks succeed.
The tag must match `pyproject.toml`; no tag is created, no release overwritten and no draft published. Joan still
approves public release, accounts and any spending. Release packaging does not replace the RELEASE1 evidence gates,
Claude's review, L2 license/security review or I3 real-model installation journeys. The new workflow must be known to
GitHub on the default branch before its manual dispatch can be used. A PR run is separately identified evidence.

### Abrir sin firma de pago / Opening without paid signing

**Español.** Compara `SHA256SUMS` con el archivo descargado antes de abrirlo. En macOS copia SPIKE.app a Aplicaciones;
si Gatekeeper lo bloquea, usa la excepción para esa app en Ajustes del Sistema → Privacidad y seguridad → Abrir
igualmente, solamente si confías en su procedencia. No desactives Gatekeeper. En Windows comprueba el archivo y,
si SmartScreen permite continuar, usa Más información → Ejecutar de todas formas para esa copia. Una política de
empresa puede impedirlo. En Linux marca el AppImage como ejecutable; si falta FUSE, usa
`./SPIKE-VERSION-Linux-x86_64.AppImage --appimage-extract-and-run`. Los modelos se descargan después de tu clic en
el asistente, con licencia y checksum; los especialistas aún no publicados aparecen como perfiles.

**English.** Verify the downloaded file against `SHA256SUMS`. On macOS copy SPIKE.app to Applications; if Gatekeeper
blocks it, use System Settings → Privacy & Security → Open Anyway for this specific trusted app. Do not disable
Gatekeeper. On Windows verify the file, then use More info → Run anyway only if SmartScreen offers that choice and
you trust its provenance; organizational policies can prevent overrides. On Linux make the AppImage executable;
without FUSE use `./SPIKE-VERSION-Linux-x86_64.AppImage --appimage-extract-and-run`. Model downloads begin only after
an explicit wizard click and license/hash checks. Unpublished specialists remain instruction profiles.

Authoritative references: [PyInstaller signing](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing),
[Inno per-user installs](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[Inno silent install switches](https://jrsoftware.org/ishelp/topic_setupcmdline.htm),
[AppImage FUSE fallback](https://docs.appimage.org/user-guide/troubleshooting/fuse.html),
[Apple Gatekeeper](https://support.apple.com/en-us/102445),
[AppImage runtime license](https://github.com/AppImage/type2-runtime/blob/main/LICENSE).
The AppImage runtime includes third-party libraries (including LGPL libfuse); retain notices and have L2 review
binary/source/relinking obligations. A checksum verifies bytes, not redistribution rights or public-release approval.
