# Release evidence / Evidencia para el lanzamiento

SPIKE is not declared finished by a green CI badge, a task count or tokens spent. This offline tool links the agreed
scope to implementation references, repeatable user journeys and review records. It does not call models, run recorded
commands, inspect accounts, upload evidence or publish a release. English field names are stable v1 interchange keys;
the inventory and review instructions are in Spanish for the current team.

El inventario inicial contiene **120 referencias de origen y 98 funciones agrupadas**: 95 dentro del alcance, dos
exclusiones expresas y monetización aplazada. Los 60 puntos de la conversación están presentes. La lista repetida se
contabiliza una vez. `documented` significa que se localizó código o un procedimiento, no que esté completo ni que su
calidad haya sido validada. `in_review` identifica una entrega candidata con la revisión exacta y su PR.

## Uso reproducible

Desde la raíz del checkout, con Python del entorno de desarrollo existente:

```sh
python scripts/release/readiness.py check --revision <SHA-completo-del-candidato>
python scripts/release/readiness.py report --revision <SHA-completo-del-candidato> --format markdown --out readiness.md
python scripts/release/readiness.py report --revision <SHA-completo-del-candidato> --format html --out readiness.html
python scripts/release/readiness.py gate --revision <SHA-completo-del-candidato>
```

El HTML funciona sin servidor ni conexión, permite buscar y filtrar, y escapa el contenido del inventario.
`check` valida estructura y cobertura de fuentes, no archivos ni resultados. `report` añade integridad y cobertura;
su salida 0 significa que pudo crear el informe. `gate` devuelve 0 si los registros cumplen, 1 si faltan criterios y 2
si los datos no se pueden interpretar. Los errores de lectura/escritura también devuelven 2. JSON con claves duplicadas,
NaN, versiones desconocidas o campos inesperados se rechaza. `--out` escribe únicamente el archivo indicado.

## Archivos y responsabilidades

- `catalog.json`: alcance, responsable propuesto, tareas del tablero, referencias, pruebas existentes y recorrido por
  función. No reemplaza `docs/team/tasks.json`. A15 sigue bajo Claude aunque Codex entregó la PR candidata. Gemini
  conserva diagnósticos y accesibilidad; su G1 local aún requiere entrega e integración.
- `evidence.json`: registros aportados, decisiones de revisión y defectos. Se entrega **vacío**: no hay recorridos reales
  completos del candidato integrado que podamos acreditar. No significa que SPIKE carezca de pruebas históricas.
- `COORDINATION.md`: foto fechada de integración y bloqueos, incluida medicina, con próximos pasos para Claude.
- `LAUNCH.md`: oferta de posicionamiento, borradores de campaña y monetización para revisión. No es publicación.

Claude valida cambios de alcance y revisa resultados; Joan revisa la experiencia final y controla la publicación.
Codex puede preparar registros de lo que pruebe. No puede escribir una aprobación en nombre de Claude o Joan.

## Formato v1 de evidencia

Los registros se conservan incluso cuando fallan. Cada `run` requiere:

```json
{
  "id": "dev-macos-001",
  "journey": "dev-flow",
  "revision": "<40 caracteres hexadecimales del commit probado>",
  "version": "0.1.0-rc.1",
  "recorded_at": "2026-10-29T12:00:00Z",
  "platform": "macos",
  "mode": "real",
  "model": {"name": "<modelo realmente usado>", "revision": "<hash o revisión de pesos>"},
  "configuration": {"hardware": "<equipo>", "context": 8192, "backend": "<versión>", "permissions": "<permisos>"},
  "outcome": "pass",
  "commands": ["<comando exacto o pasos de interfaz ejecutados>"],
  "artifacts": [{"path": "release-evidence/dev-macos-001.json", "sha256": "<SHA-256 real>"}]
}
```

Este bloque es una plantilla, no datos válidos ni una prueba realizada. `model` puede ser `null` solo en recorridos que
no requieren modelo. `mode` admite `real` y `simulated`; este último nunca satisface un recorrido de lanzamiento.
`outcome`: `pass`, `fail`, `blocked`, `cancelled`. El nombre de plataforma es `macos`, `windows` o `linux`; la versión del
SO, arquitectura, backend, hardware, modelo, parámetros, entradas y permisos concretos van en `configuration` y logs.
Los pasos y comandos se almacenan como texto: el comprobador **nunca los ejecuta**.

Artefactos bajo `--root`, con rutas relativas POSIX; no enlaces simbólicos, rutas absolutas, `..`, unidades Windows ni
lecturas fuera de la raíz. Límite 512 MiB por artefacto y 8 MiB por archivo de registros. Para grabaciones mayores,
conservar segmentos o un manifiesto revisado y las grabaciones privadas aparte; un manifiesto no prueba por sí solo su
contenido externo. No incluir credenciales, documentos personales, claves ni conversaciones privadas en el repositorio.
Los hashes comprueban integridad desde el registro, **no autenticidad ni verdad del resultado**.

Cada recorrido crítico exige tres ejecuciones consecutivas distintas, con idéntica versión, modelo y configuración,
en **cada plataforma declarada**. Los demás exigen una. Un fallo, bloqueo, cancelación, cambio de configuración o
reutilización de todo un juego de artefactos reinicia la secuencia. Puede compartirse un manifiesto de configuración
si cada ejecución conserva un resultado propio distinto. Pruebas de otros commits no cuentan; hay que repetir tras
integrar. Esta política es conservadora: no permite sustituir revalidación por heredar resultados de una PR.

Un defecto es `{id, title, status: "open" | "fixed", breaks_promise: boolean, reference}`. Los abiertos que rompen una
promesa bloquean. La lista vacía no prueba ausencia de defectos: revisar exhaustivamente es un recorrido independiente.

Cada aprobación usa `{actor: "claude" | "joan", revision, decision: "approve" | "reject", recorded_at,
artifact: {path, sha256}}`. Se exige revisión posterior a la última ejecución real del candidato. Prevalece la decisión
más reciente; una negativa o un archivo alterado bloquea. No son firmas digitales ni sustituyen la autorización de
publicar. Un registro editado maliciosamente podría mentir: el responsable debe contrastar la evidencia original.

## Recorridos y aceptación

Cada función incluye pasos observables. En todos: usar una carpeta de prueba, datos propios no sensibles, dependencias
reales y versión exacta; registrar también errores, capturas, logs y los archivos finales. Abrir los entregables en sus
lectores reales. Verificar permisos denegados, cancelación, recuperación y reapertura cuando proceda. La suite Python y
el navegador con proveedor simulado prueban ingeniería; no sustituyen calidad con pesos reales.

El alcance sigue siendo grande: Device Lab y Visual Workflow Builder se conservan como promesas sin implementación
confirmada, no se excluyen por conveniencia. Las salas multiusuario y el escritorio con modelo local sí se excluyen por
el plan del equipo. La facturación espera la oferta aprobada y no bloquea Community. Algunos módulos pueden quedar como
perfiles o capacidades opcionales si Claude y Joan lo deciden explícitamente; no relajar criterios de modelos.

Los requisitos de 16 GB se miden por configuración, cargando módulos bajo demanda. Render, entrenamiento, escritorio,
Blender, Godot y proveedores externos necesitan sus propias mediciones y dependencias. No arrancar otro trabajo pesado
mientras medicina siga sin diagnóstico. No se llama a proveedores de pago para rellenar huecos de evidencia.
