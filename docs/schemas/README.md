# Public formats v1 / Formatos públicos v1

The `$id` values are stable versioned identifiers, not network endpoints. Validation is local with jsonschema.
Los `$id` son identificadores versionados, no servicios de red. La validación es local.

| Schema | Real output / Salida real |
|---|---|
| specialist-pack.schema.json | `pack.json` from `export_pack` / de `export_pack` |
| skill-pack.schema.json | Same combined pack, with `skills/<name>/SKILL.md` / mismo pack combinado |
| project-export.schema.json | `project.json` inside the project zip / dentro del zip del proyecto |
| proof-package.schema.json | `manifest.json` inside the proof zip / dentro del zip de prueba |
| bench-share.schema.json | `spike bench --model <GGUF> --share` |

`--share` prints and saves anonymous JSON to `bench-share.json` (or `--out`), without uploading anything.
It keeps rounded RAM, CPU class, cores, numeric OS version, SPIKE version, known llama.cpp commit, known model
label, context and measured speeds. Unknown labels become `unknown`; unknown build versions become `null`.
Model labels currently recognize Qwen GGUF names; other names are deliberately withheld. Adapted results are
labelled `adapted` with no adapter name. The raw benchmark report remains private and is not saved in share mode.

`--share` imprime y guarda JSON anónimo en `bench-share.json` (o `--out`), sin enviarlo. Conserva RAM redondeada,
clase de CPU, núcleos, versión numérica del sistema, versiones, modelo reconocido, contexto y velocidades medidas.
Las etiquetas desconocidas pasan a `unknown` y las versiones de compilación desconocidas a `null`. Actualmente
se reconocen nombres GGUF de Qwen. No se guarda el informe privado al usar `--share`.

`GET /api/conversations/{id}/proof?include=environment,calls` chooses sections. Allowed: `chat`, `calls`, `files`,
`providers`, `settings`, `environment`. Omit the query for all sections; `include=` selects none. Unknown sections
return HTTP 400. The manifest lists the exact selection. README, manifest and checksums are always included.
`environment.json` contains package versions, OS, architecture, numeric OS release and numeric values only for
OMP_NUM_THREADS, OPENBLAS_NUM_THREADS and MKL_NUM_THREADS. No arbitrary environment variables are copied.

La consulta `include` elige secciones; sin consulta se incluyen todas, `include=` no incluye ninguna y los nombres
incorrectos dan HTTP 400. El manifiesto enumera la selección. README, manifiesto y sumas siempre están presentes.
La cápsula incluye versiones, sistema, arquitectura y solo valores numéricos de las tres variables de hilos indicadas.

Selection controls sections, not redaction within a selected section: chat includes raw text and recorded events;
providers and settings may contain private endpoints and instructions. Review selected files before sharing.
Checksums prove integrity since export, not identity or completeness of omitted sections. No real-weight measurements
were made for these export features.

La selección controla secciones, no censura sus contenidos: el chat contiene texto y eventos; proveedores y ajustes
pueden contener direcciones e instrucciones privadas. Revisa los archivos antes de compartir. Las sumas prueban
integridad, no identidad ni completitud de secciones omitidas. Estas funciones no se midieron con pesos reales.
