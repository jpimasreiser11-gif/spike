# SPIKE — installer candidate / candidato de instalación

This is a private draft for Claude and Joan to review. It is not a public launch or a declaration that every SPIKE
feature, trained specialist or platform has passed product acceptance.

The attached installers have a SHA256SUMS file and per-platform JSON evidence. The packaging smoke uses a tiny
random-weight GGUF fixture to exercise application health, bundled UI resources, catalog/skills and local inference.
It does not measure answer quality, 16-GB performance, native-window usability, real-model download or GPU support.
Models are not embedded: the first-run wizard requests an explicit download and checks licenses and hashes.

Build targets: Apple Silicon on macOS 14, x64 Windows on the Windows 2022 runner, and x86_64 Ubuntu 24.04.
Paid signatures and notarization are absent. See packaging/README.md for the corresponding OS warnings and opening
instructions. No payments or accounts are activated by this draft.

Real model (I3, measured on GitHub runners on 2026-11-02, runs 41449693467 and 41502647706): on Windows Server 2022
and Ubuntu 24.04 the installed app downloaded Qwen3.5-4B Q4_K_M through its own first-run setup, checked it against
the Hub's SHA-256, answered one question, quit and uninstalled keeping the profile and the model. The free macOS
runner has 7.0 GiB of RAM and the app's own 8 GiB guard refused the download, so the real model on macOS is not
tested on a runner; it is to be checked on a Mac with the demo (L1). The security and license review (L2) is in
docs/release/REVIEW-v0.1.md; still open there: the founder's reading of the LGPL runtime below, and Joan's publication
approval (L3). No specialist adapter is released yet: each one ships only after it passes its own acceptance gate.

Licenses: each build carries SPIKE's Apache-2.0 LICENSE, NOTICE, THIRD_PARTY.md and the license text of every bundled
Python and web package (`licenses/` next to the program; `licenses/third-party/INDEX.md` lists them). The Linux
AppImage starts from the unmodified upstream type2-runtime, which statically links libfuse (LGPL-2.1); its source is
https://github.com/AppImage/type2-runtime (the pinned release) and https://github.com/libfuse/libfuse, and the runtime
can be replaced by re-packing the AppImage with `appimagetool --runtime-file`. llama.cpp's `llama-server` (tag b11709)
carries its MIT license plus the notices of the libraries it vendors (`licenses/native/llama-vendored.txt`) and of the
npm packages in the web UI it embeds and SPIKE does not use (`licenses/native/llama-ui-npm.txt`).

Español: revisa los hashes y la evidencia antes de probar estos candidatos. Las pruebas con pesos aleatorios no
validan la calidad de los especialistas ni todas las funciones. La publicación requiere la aprobación de Joan.
