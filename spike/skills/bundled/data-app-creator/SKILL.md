---
name: data-app-creator
description: Create a local data app with explicit input contracts, reproducible transformations and safe export boundaries.
license: Apache-2.0
metadata:
  spike-specialists: code
  spike-keywords: aplicación de datos, data app
---

# Data App Creator

1. Confirm the user's workflow, input format, expected size, sensitive fields and desired output.
2. Load template.md. Define column types, missing-value policy and validation errors before implementing transformations.
3. Keep raw input separate from derived data. Prefer installed libraries and deterministic transformations.
4. Validate file paths within the workspace. Preview writes and require permission before replacing files or sending data.
5. Provide loading, empty, invalid-input and processing-error states without logging sensitive rows.
6. Test a tiny known dataset, malformed input, missing fields and export round-trip. Report measured limits only.

Respond in the user's language. Distinguish a draft from a verified deliverable.
