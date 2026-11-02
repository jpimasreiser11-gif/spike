---
name: api-contract
description: Define an API contract with request schemas, error cases, authorization boundaries and compatibility rules.
license: Apache-2.0
metadata:
  spike-specialists: code
  spike-keywords: contrato de la api, api contract
---

# Api Contract

1. Identify clients, use cases, trust boundaries and the repository's existing route and schema conventions.
2. Specify methods, paths, parameters, request and response fields with requiredness, types, limits and examples.
3. Define errors for malformed input, missing authorization, missing resources, conflicts and service unavailability.
4. State idempotency, pagination and concurrency expectations only where relevant. Do not put credentials in examples.
5. Define compatibility and deprecation rules. Place new HTTP routes in a dedicated APIRouter module.
6. Propose contract tests using offline fixtures for success, boundaries and permission failures before implementation.

Respond in the user's language. Distinguish a draft from a verified deliverable.
