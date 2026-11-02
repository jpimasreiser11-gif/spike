# SPIKE — installer candidate / candidato de instalación

This is a private draft for Claude and Joan to review. It is not a public launch or a declaration that every SPIKE
feature, trained specialist or platform has passed product acceptance.

The attached installers have a SHA256SUMS file and per-platform JSON evidence. The packaging smoke uses a tiny
random-weight GGUF fixture to exercise application health, bundled UI resources, catalog/skills and local inference.
It does not measure answer quality, 16-GB performance, native-window usability, real-model download or GPU support.
Models are not embedded: the first-run wizard requests an explicit download and checks licenses and hashes.

Build targets: Apple Silicon on macOS 14, x64 Windows on the Windows 2022 runner, and x86_64 Ubuntu 24.04.
Paid signatures and notarization are absent. See packaging/README.md for the corresponding OS warnings and opening
instructions. Real-model journeys (I3), final license/security review (L2), Claude's review and Joan's publication
approval remain separate gates. No payments or accounts are activated by this draft.

Licenses: each build carries SPIKE's Apache-2.0 LICENSE, NOTICE, THIRD_PARTY.md and the license text of every bundled
Python and web package (`licenses/` next to the program; `licenses/third-party/INDEX.md` lists them). The Linux
AppImage starts from the unmodified upstream type2-runtime, which statically links libfuse (LGPL-2.1); its source is
https://github.com/AppImage/type2-runtime (the pinned release) and https://github.com/libfuse/libfuse, and the runtime
can be replaced by re-packing the AppImage with `appimagetool --runtime-file`.

Español: revisa los hashes y la evidencia antes de probar estos candidatos. Las pruebas con pesos aleatorios no
validan la calidad de los especialistas ni todas las funciones. La publicación requiere la aprobación de Joan.
