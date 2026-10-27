---
name: dataset-audit
description: Audit dataset quality, provenance, licensing, leakage and representativeness before reuse.
license: Apache-2.0
metadata:
  spike-specialists: data
  spike-keywords: calidad del dataset, dataset quality
---

# Dataset Audit

1. Establish the intended use, schema, source, collection date and license evidence. Unknown rights block reuse claims.
2. Count missing values, duplicates, invalid ranges and type failures using reproducible local operations.
3. Check train/evaluation separation by stable identifiers and chronology where relevant. Report sampling limitations.
4. Inspect for sensitive fields without reproducing personal records. Never transmit the dataset for inspection.
5. Record source provenance and any restrictions. For SPIKE training, reject model-generated text and unclear commercial rights.
6. Deliver findings with counts, method, severity, proposed remediation and acceptance checks; do not silently alter data.

Respond in the user's language. Distinguish a draft from a verified deliverable.
