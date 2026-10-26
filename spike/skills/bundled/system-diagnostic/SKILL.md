---
name: system-diagnostic
description: Use for SPIKE system diagnostics with spike doctor, without starting models or changing the machine.
license: Apache-2.0
allowed-tools: []
metadata:
  author: SPIKE contributors
  spike-specialists:
  - core
  spike-keywords: diagnostica, diagnóstico, diagnose, diagnostics, doctor, diagnóstico del sistema, system diagnostics
---

# System diagnostic

1. Ask for the symptom, platform and relevant error, and reply in the user's language. Start with the read-only
   `spike doctor --json` report. Request pasted output if a command tool is unavailable.
2. If an authorized command tool is available, run doctor through its normal permission broker. Do not bypass
   its sandbox using another tool. Never start llama-server, training or a download as part of diagnosis.
3. Separate detected hardware, discovered model files and runtime availability from recommended estimates.
   `spike doctor --strict` checks local readiness via its exit code; missing runtime/models is a finding, not a crash.
   Memory recommendations are estimates and are not measured inference speed or quality.
4. Redact usernames, private paths, tokens and account information before sharing a report. Do not collect env,
   dump credentials or upload diagnostics. Compare only the fields relevant to the symptom.
5. Deliver findings with report evidence, uncertainty and the smallest suggested next step. Installation, config
   changes and resource-heavy work require separate authorization; never claim an unexecuted fix succeeded.
