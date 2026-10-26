---
name: test-inventor
description: Use to invent edge case tests, property tests and adversarial cases from a software contract.
license: Apache-2.0
allowed-tools:
- read_file
- write_file
- python
metadata:
  author: SPIKE contributors
  spike-specialists:
  - code
  spike-keywords: casos de prueba, pruebas de propiedades, edge case, property tests, inventa, invent, boundary,
    límite
---

# Test inventor

1. Read the supplied contract and neighbouring tests. Identify observable behaviour, invalid inputs, boundaries,
   invariants, state transitions and failures of dependencies. Reply in the user's language.
2. Make a case matrix: input class, minimal example, expected result and the contract clause it verifies.
   If the oracle is ambiguous, ask instead of encoding an invented requirement.
3. Write deterministic tests with the project's existing test framework and fixtures; add no dependency.
   Use parametrized examples and seeded standard-library generators for properties. Cover empty, Unicode,
   size limits, malformed values, retries and cleanup only where the contract makes them relevant.
4. Mock external services and clocks. No network, paid calls, real credentials or changes to user-owned files.
   File writes and code execution must use the normal permission broker and workspace boundaries.
5. Run the smallest relevant suite if authorized. Confirm each regression fails without the behaviour it protects.
   Report exact commands and results, distinguishing tests written from tests actually executed.
