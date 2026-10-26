---
name: synthetic-data
description: Use to generate reproducible synthetic data or fake data for software fixtures without personal records.
license: Apache-2.0
allowed-tools:
- python
- write_file
metadata:
  author: SPIKE contributors
  spike-specialists:
  - data
  spike-keywords: datos sintéticos, synthetic data, datos ficticios, fake data, reproducibles, reproducible
---

# Synthetic data

1. Establish the schema, row count, types, constraints, relationships, seed and intended test purpose.
   Reply in the user's language. Use invented fixtures only; never copy real personal records or secrets.
2. Use an installed Faker module only if importlib.util.find_spec("faker") finds it. Otherwise use standard-library
   random.Random(seed), uuid.UUID(int=rng.getrandbits(128)), datetime, csv and json. Do not install anything.
   Record which path and seed were used; reproducibility across Faker versions is not guaranteed.
3. Create generators with referential integrity and explicit distributions. Use example.invalid email domains,
   clearly fictional identifiers and no functioning credentials. Bound output size before generation.
4. Validate row counts, nullability, unique keys, foreign keys and numeric/date bounds. Include deliberate invalid
   cases only in a separately labelled negative fixture set. Save UTF-8 files inside the workspace with permission.
5. Deliver the generator, schema and validation summary. Mark output synthetic; do not claim it represents a
   population, preserves privacy statistically or is suitable for training. This skill makes test fixtures, not
   training data: model-generated text must never enter SPIKE's training corpus.
