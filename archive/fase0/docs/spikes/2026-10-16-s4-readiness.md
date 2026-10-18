# Spike F0 · S4 — descontaminación Unicode y familias de ejemplos

**Fecha:** 2026-10-16 · **Fuente:** [`PLAN.md` §§0, 5.1, 5.3 y 14](../../PLAN.md) · **Resultado:** herramienta local de comprobación preparada, **S4 NO APROBADO / datos reales no examinados**. El plan pide inventario de licencias, medida de velocidad de un profesor local y descontaminación con coste 0 €. **Este componente cubre únicamente la última parte; no valida derechos, PII, velocidad de profesor, calidad de corpus ni entrenamientos.**

## Entrega verificable

- [`scripts/phase0/decontam_check.py`](../../scripts/phase0/decontam_check.py) es Python de biblioteca estándar. No descarga, instala ni envía datos a servicios. Recibe un único manifiesto JSON **de muestras previamente autorizadas y filtradas de PII**, calcula hashes y n-gramas en memoria, y compara registros de `train` contra `eval` **y también dentro de cada split** para localizar familias conectadas por colisiones transitivas.
- [`tests/gates/test_decontam_check.py`](../../tests/gates/test_decontam_check.py) contiene **solo datos sintéticos inventados para los tests**. Incluye equivalencia Unicode (NFKC, casefold y tildes compuestas), variaciones casi duplicadas en inglés, un ejemplo inventado en japonés sin separadores, variantes de documentos, colisión de familias, propagación transitiva, errores de integridad, privacidad y permisos de salida.
- El detector conserva `phase0_passed: false` y `training_authorized: false` incluso cuando no encuentra cruces; una comprobación negativa de n-gramas no es una aprobación de S4, del conjunto, del modelo ni de Fase 1. **Nunca devuelve estados PASS de gate.**

## Esquema de entrada y fail-closed

Se exige un JSON objeto con `eval_sealed: true` y dos listas no vacías, `train` y `eval`. Cada registro incluye:

| Campo | Validación | Para qué se utiliza |
| --- | --- | --- |
| `id` | Cadena no vacía, globalmente única, máximo 256 caracteres | Diferenciar filas en memoria; **jamás aparece en los informes** |
| `family_id` | Cadena no vacía, máximo 256 caracteres, normalizada como texto Unicode | Agrupar fuente original, variantes, traducciones y paráfrasis declaradas; **no se publica su valor** |
| `rights_reference` | Cadena no vacía, máximo 256 caracteres | Referencia local al trabajo previo de licencia; **declarativa**, el detector no revisa licencia ni permisos |
| `license_approved` | Booleano exactamente `true` | Declaración del responsable de que el uso preciso pasó auditoría de licencias |
| `pii_screened` | Booleano exactamente `true` | Declaración del responsable de que el contenido pasó limpieza/inspección de PII; **no se detecta ni retira automáticamente PII** |
| `allowed_use` | Exactamente `train` o `eval` según la lista | Evitar usar por error muestras con permiso solo de evaluación como entrenamiento |
| `text` | Unicode válido, de 1 a 4096 bytes UTF-8 y suficientes n-gramas | Texto autorizado; leído y transformado **solo en memoria del proceso**. Para textos demasiado cortos se bloquea por cobertura insuficiente |
| `raw_sha256` | SHA-256 hexadecimal en minúsculas del texto en UTF-8 | Comprobar que el texto entregado coincide con el hash declarado |
| `normalized_sha256` | SHA-256 de la normalización documentada | Comprobar que el texto coincide también con el hash normalizado declarado |

El archivo de entrada no puede ser enlace simbólico y tiene límite de **2 MB**. La suma de filas `train+eval` no puede superar **500**: se usa comparación exhaustiva entre todas las parejas (`O(n²)`) para capturar también vínculos entre ejemplos del mismo split. Un input malformado, reseñado sin permisos, sin sellado `eval_sealed`, sin texto suficiente, con hashes inconsistentes, Unicode inválido o excediendo límites produce **`FAIL_INVALID_MANIFEST`** y salida de error sanitizada. Los metadatos `rights_reference`, `license_approved` y `pii_screened` **no sustituyen** una auditoría real ni prueba de cumplimiento legal; un usuario puede declararlos incorrectamente.

### Normalización y comparación

1. Normalizar **NFKC → Unicode casefold → NFKC**, preservar letras, marcas combinantes y números según categorías Unicode `L/M/N`. Sustituir signos, símbolos, controles y espacios por separadores, colapsar separadores; **no** eliminar diacríticos ni modificar cifras.
2. Comparar hashes originales y normalizados, además de coincidencia exacta del `family_id` normalizado. Estas señales detectan equivalencias de formato, puntuación y familias declaradas.
3. Construir conjuntos de trigramas de palabras para textos de **6 o más tokens**; detectar `Jaccard ≥0.75` o `containment ≥0.90`, siempre con intersección de **al menos 3 trigramas**.
4. Construir n-gramas de **5 caracteres** sobre texto sin separadores cuando tenga **25+ caracteres**; detectar `Jaccard ≥0.82` o `containment ≥0.95`, siempre con intersección de **al menos 12 n-gramas**.
5. Para texto sin segmentación en palabras (p. ej., japonés/chino), admitir **trigramas de caracteres** con longitud **≥12**, intersección ≥8 y `Jaccard ≥0.82`. Esto es un detector aproximado conservador, **no** segmentación lingüística real.
6. Unir en grafo todas las parejas coincidentes, incluso dentro de `train` o de `eval`; si una componente conexa contiene al menos una muestra de cada split, **todas las filas de esa componente** se consideran contaminadas. Registrar cantidad y evidencia solo mediante índices por posición y puntuaciones, sin texto ni IDs.

**Cautelas técnicas:** un conjunto de n-gramas ignora frecuencias y puede producir falsos positivos por frases comunes o falsos negativos por paráfrasis fuertes, traducciones o cambios semánticos. Para ejemplos diminutos se exige más evidencia en vez de declarar limpio un chequeo de hashes. Los umbrales están fijados en código y en la salida; cambiar una versión requiere revisión y nueva calibración con datos lícitos. No se detecta contaminación por pretraining del modelo base. Para código, matemáticas y tablas pueden necesitarse verificadores específicos de AST, unidades y estructuras, fuera de esta herramienta.

## Uso local futuro (sin modelos ni descargas)

```bash
cd /downloads/spike
# Pruebas exclusivas sobre muestras sintéticas incluidas en los tests.
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/gates -p 'test_decontam_check.py' -v

# SOLO si existe un manifiesto previamente revisado, licenciado y limpio de PII.
PYTHONDONTWRITEBYTECODE=1 python3 scripts/phase0/decontam_check.py \
  --manifest /ruta/a/manifiesto-autorizado.json \
  --output /ruta/segura/s4-decontam.json
```

La herramienta **no construye datasets, no lee rutas de ficheros de contenido ni sigue URLs incluidas en los registros**. Su análisis usa únicamente el campo `text` proporcionado en el manifiesto. Si no se proporciona `--output`, prepara un nombre de informe bajo `reports/phase0/`. Cada informe se crea **sin sobrescritura** (`O_EXCL`) y con permisos de archivo `0600`; los directorios nuevos se crean con `0700`. Se bloquean directorios de salida que sean symlinks, excepto los alias macOS conocidos `/var → /private/var` y `/tmp → /private/tmp`. Los informes no incorporan texto, IDs, nombres de familia, referencias de derechos, rutas de entrada ni hashes de contenido; también las excepciones se reducen a códigos fijos. El usuario debe conservar el manifiesto de entrada en ubicación protegida, pues **ese archivo sí contiene el texto original**.

## Informe JSON y reproducibilidad

Esquema `spike.phase0.decontamination.v2`, serializado con claves ordenadas y valores predefinidos. Para los mismos datos, parámetros y versión del intérprete compatible, el **contenido JSON es reproducible byte por byte**, sin timestamp/commit/path/salts aleatorias dentro del JSON; el nombre por defecto puede variar para no sobrescribir. Un ejemplo de estructura de resultado **ilustrativa y sin mediciones**:

```json
{
  "schema": "spike.phase0.decontamination.v2",
  "status": "SCREENING_ONLY_NO_DETECTED_OVERLAP",
  "phase0_passed": false,
  "training_authorized": false,
  "contaminated_train_count": 0,
  "contaminated_eval_count": 0,
  "evidence_pairs": [],
  "evidence_pairs_truncated": false
}
```

El informe real incluye también conteos de entradas, componentes cruzadas, señales de colisión, pares directos de hasta 40, configuración de n-gramas y límites. **El JSON de arriba es solo una ilustración parcial del esquema**, no una salida de evaluación ni métricas propias del proyecto. Si se detecta un cruce entre splits se emite `FAIL_CONTAMINATION_DETECTED` y exit `1`; entrada no conforme genera `FAIL_INVALID_MANIFEST` y exit `1`; sin cruces se emite `SCREENING_ONLY_NO_DETECTED_OVERLAP` y exit `0`, **únicamente porque el detector completó su comprobación acotada**, nunca porque S4 esté aprobado. Si no puede escribirse informe, exit `1` y `FAIL_REPORT_WRITE` sin revelar rutas.

## Estado de S4 y siguientes controles

| Requisito real §14/§5 | Evidencia de esta entrega | Estado de Fase 0 |
| --- | --- | --- |
| Comparación exacta y Unicode, familias declaradas y near dedupe | Código y tests sintéticos reproducibles, informe sanitizado | **Implementado como verificador; no validado con corpus real** |
| Auditoría de licencias A/B/C y permisos por muestra | Declaraciones obligatorias para ejecutar, [registro de fuentes](../../DATA_LICENSES.md) todavía sujeto a verificación de origen | **PENDIENTE** |
| Filtrado y comprobación legal de PII, menores y contenido vetado | `pii_screened` declarativo; herramienta sin análisis de seguridad o privacidad del texto | **PENDIENTE, condición externa obligatoria** |
| Contaminación semántica, traducciones y pretraining desconocido | Filtro léxico aproximado y familias; no prueba semántica | **RIESGO ABIERTO** |
| Profesor local, licencia, velocidad y 0 € de coste | No se conecta con modelos, hardware externo ni servicios | **NO MEDIDO** |
| Gate completo de S4 y transición a Fase 1 | No se entregó modelo ni datos reales ni evaluación autorizada | **NO GO / sin autorización de Fase 1** |

**Dictamen:** existe un filtro preparatorio auditable, determinista y defensivo, pero **S4 sigue PENDING/NOT RUN sobre datos reales**; no se presentan resultados simulados de modelos, ningún dataset queda aprobado y no se da por superado F0.
