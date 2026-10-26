---
name: localization
description: Use to localize strings and translate with a project glossary while preserving placeholders and tone.
license: Apache-2.0
allowed-tools:
- list_dir
- read_file
- write_file
metadata:
  author: SPIKE contributors
  spike-specialists:
  - writing
  spike-keywords: localiza, localize, localización, localization, traduce, translate, glosario, glossary, traducción
---

# Localization

1. Establish source/target locales, audience, tone and file format. Reply in the user's language.
2. Read the project glossary when present: look in the user-provided project context or use list_dir/read_file
   within the workspace for glossary.*, glosario.* or docs/glossary.*. Ask about ambiguous terms; if there is no
   glossary, say so and keep a small proposed terminology table separate from approved terminology.
3. Preserve keys, interpolation placeholders, markup, escape sequences, URLs and product names exactly.
   Use the project's i18n mechanism and plural rules; do not translate code identifiers or hard-code locale rules.
4. Translate meaning and register, checking accents, punctuation, units, date conventions and text expansion.
   Do not invent claims. Where supplied terminology conflicts with context, flag the conflict for review.
5. Deliver translations plus a placeholder/key parity checklist and unresolved terms. Use existing tests where
   available; claim native review only when it happened. Writes require the normal permission flow.
