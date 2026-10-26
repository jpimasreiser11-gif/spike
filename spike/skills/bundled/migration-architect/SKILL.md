---
name: migration-architect
description: Use to design a database migration or migration plan with compatibility, rollback and validation gates.
license: Apache-2.0
allowed-tools:
- read_file
metadata:
  author: SPIKE contributors
  spike-specialists:
  - code
  spike-keywords: migración, migration, rollback, reversión, esquema, schema, backfill
---

# Migration architect

1. Read the current and target schema, application contracts and deployment constraints. Establish data volume,
   availability needs, ownership and backup/restore capabilities. Reply in the user's language.
2. Propose expand, backfill, switch and contract phases. Separate compatible additive changes from destructive
   cleanup; account for mixed application versions, idempotency, interrupted runs and concurrent writes.
3. Provide a dry-run plan, sample transformations, row-count and invariant checks, and explicit gates for each phase.
   State assumptions about engine-specific transaction and locking behaviour rather than claiming compatibility.
4. Define rollback before every irreversible step, including restore verification and the point of no return.
   Estimate resource needs only from supplied measurements; otherwise label them unmeasured.
5. Deliver a phased checklist with owners, evidence and stop conditions. Do not execute production migrations,
   delete data or access a database without the user's explicit scope and normal tool permissions.
