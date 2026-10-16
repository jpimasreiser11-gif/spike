# Auditoría de cadena de suministro — skills y MCP externos de Spike

**Fecha de lectura:** 2026-10-16 (Europe/Madrid). **Alcance:** preparación y Fase 0. **Conclusión:** hay una skill externa documental copiada a `/skills` y seis skills propias sin scripts; los demás proveedores quedan pendientes de habilitación. Esta revisión estática **no** certifica la seguridad de sus dependencias ni la posibilidad de ejecutar MCP.

**Actualización de fuente:** el Plan Maestro v3 completo se incorporó posteriormente como [PLAN.md](../../PLAN.md) (§§0–17). Las referencias de esta auditoría a su ausencia describen el estado **en el momento de la lectura**, ya resuelto. La auditoría de hooks y cadenas transitivas y la aprobación de Fase 1 continúan pendientes.

## Método y evidencia verificable

1. Se leyeron `/downloads/spike/AGENTS.md` y `GEMINI.md` antes de escribir. `PLAN.md` completo no existe en el checkout; el extracto de la petición termina en 5.2. No se inventaron las secciones siguientes ni se autorizó Fase 1.
2. Se resolvió HEAD por `git ls-remote https://github.com/ORG/REPO.git HEAD` y se verificó cada SHA y fecha con la API oficial `GET https://api.github.com/repos/ORG/REPO/commits/SHA` (campo `verification.verified=true` en los cuatro commits). Una firma GitHub verificada **no** audita el código ni valida el paquete npm.
3. Se leyó el árbol de cada commit mediante la API oficial `git/trees/SHA?recursive=1` (`truncated=false`), licencias, `SKILL.md` relevantes y fragmentos de scripts **como texto, sin ejecutarlos**. Para los scripts se identificaron hashes SHA-256 y operaciones sensibles; la revisión exhaustiva de todas sus llamadas, dependencias y efectos sigue pendiente.
4. La ruta gestionada `/skills` estaba vacía al inicio. Se consultó el índice de skills anunciado por el entorno (que menciona algunas alternativas como `ext-anthropic-webapp-testing` y `superpowers-writing-skills`), pero sus contenidos exactos **no estaban disponibles bajo `/skills`**: no se equiparan con el código aquí auditado.
5. No se clonaron repositorios ni se ejecutaron `npx`, `npm install`, `pip`, `setup`, bootstrap, hooks, tests, servidores o scripts de terceros. Se leyó contenido HTTPS oficial fijado a commits. Única copia local: dos archivos de texto originales de Anthropic con licencia preservada.

## Commits congelados y licencia

| Origen oficial | Commit exacto verificado | Fecha UTC del commit | Licencia comprobada | Manifestación revisada |
| --- | --- | --- | --- | --- |
| [obra/superpowers](https://github.com/obra/superpowers) | [`bb92a77741419a4ab5f06e711a283343f1ada0c3`](https://github.com/obra/superpowers/tree/bb92a77741419a4ab5f06e711a283343f1ada0c3) | 2026-10-10 00:28:04 | [MIT](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/LICENSE), copyright Jesse Vincent | 15 `skills/*/SKILL.md`, hooks y scripts de empaquetado |
| [anthropics/skills](https://github.com/anthropics/skills) | [`dbd4588f9e1033efb41dad4bef2f7947c8993d44`](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44) | 2026-10-09 18:45:49 | **Apache-2.0 por skill**, `LICENSE.txt` examinada en las cuatro skills solicitadas | `frontend-design`, `webapp-testing`, `mcp-builder`, `skill-creator` |
| [huggingface/skills](https://github.com/huggingface/skills) | [`c3ff942be3e07116b475253f0a8fc4f54682c1a8`](https://github.com/huggingface/skills/tree/c3ff942be3e07116b475253f0a8fc4f54682c1a8) | 2026-10-08 15:30:05 | [Apache-2.0 de la raíz](https://github.com/huggingface/skills/blob/c3ff942be3e07116b475253f0a8fc4f54682c1a8/LICENSE); condiciones específicas por artefacto por verificar | 26 `SKILL.md` encontrados (incluida `hf-mcp`), scripts Python y shell |
| [morluto/rea](https://github.com/morluto/rea) | [`d72d856f58d4747c5eb4307426e80d20934e017c`](https://github.com/morluto/rea/tree/d72d856f58d4747c5eb4307426e80d20934e017c) | 2026-10-16 06:52:33 | [MIT](https://github.com/morluto/rea/blob/d72d856f58d4747c5eb4307426e80d20934e017c/LICENSE) **más** [avisos de terceros](https://github.com/morluto/rea/blob/d72d856f58d4747c5eb4307426e80d20934e017c/THIRD_PARTY_NOTICES.md) | Skill `reverse-engineer-anything`, `install.sh`, `scripts/rea.mjs`, `package.json`, dependencias |

## Veredictos por componente

| Componente | Evidencia de SKILL y scripts leídos | Dictamen de **lectura** | Dictamen de **instalación/ejecución** |
| --- | --- | --- | --- |
| Superpowers | [`using-superpowers/SKILL.md`](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/skills/using-superpowers/SKILL.md), [`hooks/session-start`](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/hooks/session-start), `hooks/run-hook.cmd`, `scripts/package-codex-plugin.sh` | **AUDITABLE parcialmente:** origen, MIT y contenido orientativo leídos | **PENDING:** otros 14 `SKILL.md`, hooks que se integran en sesiones y scripts de empaquetado aún requieren auditoría integral y revisión de modificaciones del agente. El README declara una carga opcional de logo remoto con telemetría de versión; validar desactivación antes de usar. |
| Anthropic `frontend-design` | [`SKILL.md`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design/SKILL.md) de 9.390 bytes; [`LICENSE.txt`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design/LICENSE.txt) de 10.174 bytes; carpeta sin scripts | **AUDITABLE** como instrucciones de texto | **COPIADA EN DISCO** a `/skills/anthropics-frontend-design/{SKILL.md,LICENSE.txt}`; no se ejecutó ningún código ni se confirmó carga automática en sesiones activas. |
| Anthropic `webapp-testing` | [`SKILL.md`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/webapp-testing/SKILL.md); [`scripts/with_server.py`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/webapp-testing/scripts/with_server.py), 106 líneas; ejemplos | **AUDITABLE** como guía | **PENDING ejecución:** `with_server.py` llama `subprocess.Popen(..., shell=True)` con comandos de servidor introducidos por el operador; revisar Playwright, dependencias, permisos y alcance del servidor antes de habilitar. El propio `SKILL.md` sugiere ejecutar `--help` antes de leer scripts: aquí se prioriza la regla 8 local y se leyó primero. |
| Anthropic `mcp-builder` | [`SKILL.md`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/mcp-builder/SKILL.md), `scripts/connections.py`, `scripts/evaluation.py`, `scripts/requirements.txt` | **AUDITABLE** como guía | **PENDING ejecución:** los ejemplos evalúan servidores MCP/URLs y admiten cabeceras de autorización; requerir aislamiento de secretos, costes API, destino y dependencias antes de conexión real. |
| Anthropic `skill-creator` | [`SKILL.md`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/skill-creator/SKILL.md), `quick_validate.py`, `package_skill.py`, `run_eval.py`, `run_loop.py`, `improve_description.py`, `utils.py`, `eval-viewer/generate_review.py` examinados estáticamente | **AUDITABLE como referencia documental de formato y autoría**, licencia Apache-2.0 presente; suficiente para crear skills propias originales sin scripts | **PENDING ejecución:** `run_eval.py` crea ficheros y usa `subprocess.Popen`; `improve_description.py` llama un CLI `claude` mediante `subprocess.run`; scripts de evaluación, empaquetado y visor pueden escribir archivos, ejecutar procesos o usar credenciales. **No se han ejecutado ni copiado**. |
| Hugging Face `skills` | [`huggingface-llm-trainer/SKILL.md`](https://github.com/huggingface/skills/blob/c3ff942be3e07116b475253f0a8fc4f54682c1a8/skills/huggingface-llm-trainer/SKILL.md), `huggingface-datasets/SKILL.md`, `huggingface-local-models/SKILL.md`, ejemplo `train_sft_example.py`, `lighteval_vllm_uv.py`, `hf-cloud-sagemaker-iam-preflight/scripts/create_role.py` | **AUDITABLE parcialmente**, especialmente consulta de APIs públicas sin efectos | **PENDING:** `huggingface-llm-trainer` propone Jobs GPU gestionados, subida a Hub y servicios potencialmente facturables; algunos scripts ejecutan procesos o administran IAM de AWS. Además el frontmatter de `huggingface-llm-trainer` remite a `LICENSE.txt` local que **no existe en esa carpeta**, aunque sí hay licencia Apache-2.0 en la raíz. Exigir comprobación por subskill, coste y permisos. |
| REA (skill + MCP) | [`.agents/skills/reverse-engineer-anything/SKILL.md`](https://github.com/morluto/rea/blob/d72d856f58d4747c5eb4307426e80d20934e017c/.agents/skills/reverse-engineer-anything/SKILL.md); `install.sh`, `scripts/rea.mjs`, `package.json`, `THIRD_PARTY_NOTICES.md` | **AUDITABLE parcialmente** para especificaciones de investigación autorizada | **PENDING:** `install.sh` prepara instalación global npm y `setup` puede registrar MCP y motores; `npx` puede descargar paquetes y crear caché incluso con `doctor`. `package.json` declara 40 dependencias directas y `frida` opcional, además de 210 entradas de scripts npm. REA exige Node 22.19+/24.11+/26+, y proveedores de análisis externos pueden exigir licencias de pago. Revisar paquete npm y transitorios con hash antes de instalar; prohíbese `npx rea-agents@latest setup` en este gate. |

### Huellas de archivos revisados estáticamente

Valores SHA-256 de **los bytes del archivo remoto fijado**, no hashes de instaladores ni de un artefacto ejecutado:

| Archivo | SHA-256 |
| --- | --- |
| `anthropics/frontend-design/SKILL.md` | `d91970639e9f5c37682ac7ab60094d35f1c7c1f38d731bd56396563aee10c1d3` |
| `anthropics/frontend-design/LICENSE.txt` | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |
| `anthropics/webapp-testing/scripts/with_server.py` | `b0dcf4918935b795f4eda9821579b9902119235ff4447f687a30286e7d0925fd` |
| `anthropics/skill-creator/scripts/run_eval.py` | `43e3b8f80dbf69c343967ba77e268fae991d9fa3ed68b32a0ff02532cd48657f` |
| `anthropics/skill-creator/scripts/quick_validate.py` | `67cf5703402013936c8fb75ad6a1afecd8841d45cc5e606b634eb05825fde365` |
| `obra/superpowers/hooks/session-start` | `5c15e62a90ed13ad8e4b3561148c54c26c6ee28b41ec3a55a241f68b400d886d` |
| `morluto/rea/install.sh` | `aa6ce7945262d8ef1599f08c5b82d4ce281fae4c0c51e6eda7bbbff2879a47a8` |
| `morluto/rea/THIRD_PARTY_NOTICES.md` | `c7db9545d34eb4dac7c0e270cb1a639dfd156d4d462a41bcf65cde71369c222c` |

## Skills propias de Spike preparadas

Se crearon seis instrucciones **originales, sin código ejecutable ni hooks**, bajo `.agent/skills/{honest-claims,eval-gate,data-license-audit,specialist-factory,clean-room,release-checklist}/SKILL.md`. Su formato se contrastó con la referencia documental `skill-creator`; **no** se invocó, copió ni ejecutó su implementación. Los nombres vienen de la asignación de esta preparación; el contenido necesita contrastarse contra §3.3 del `PLAN.md` íntegro cuando se facilite. Ninguna de estas skills aprueba entrenamientos, publicaciones o Fase 1.

**Compatibilidad de identificadores heredados:** la petición disponible nombra los identificadores `nexus-*` del §3.3 original; la [ADR 0001](../adr/0001-project-name.md) aprueba el nombre **Spike** para el producto, pero advierte expresamente que renombrar rutas `nexus-*` necesita otra decisión cuando exista el plan completo. En preparación se han usado nombres locales descriptivos **provisionales**, sin afirmar equivalencia formal ni cambiar las rutas heredadas dentro del Plan:

| Identificador referido del Plan Maestro original (pendiente de confirmación textual completa) | Ruta documental provisional creada |
| --- | --- |
| `nexus-honest-claims` | `.agent/skills/honest-claims/SKILL.md` |
| `nexus-eval-gate` | `.agent/skills/eval-gate/SKILL.md` |
| `nexus-data-license-audit` | `.agent/skills/data-license-audit/SKILL.md` |
| `nexus-specialist-factory` | `.agent/skills/specialist-factory/SKILL.md` |
| `nexus-clean-room` | `.agent/skills/clean-room/SKILL.md` |
| `nexus-release-checklist` | `.agent/skills/release-checklist/SKILL.md` |

**Instalación frente a documentación:** las seis skills propias existen solo **dentro del repositorio** y no constan cargadas por ningún cliente. La única skill externa copiada bajo `/skills` es `anthropics-frontend-design`. Ningún MCP quedó registrado.

## Comandos de verificación futura propuestos (NO ejecutarlos como instalación)

```bash
# Consultas de procedencia, siempre solo lectura:
git ls-remote https://github.com/anthropics/skills.git HEAD
git ls-remote https://github.com/morluto/rea.git HEAD

# Integridad de la skill textual instalada, sin ejecutar su contenido:
cd /skills/anthropics-frontend-design
shasum -a 256 SKILL.md LICENSE.txt

# Si se quiere comprobar un archivo remoto EXACTAMENTE fijado (solo salida de texto):
curl -fsSL https://raw.githubusercontent.com/anthropics/skills/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/skill-creator/SKILL.md | sed -n '1,90p'

# Inspección de ficheros locales de Spike (si se recupera PLAN.md):
find .agent/skills -name SKILL.md -type f -print
```

**Antes de cualquier instalación o ejecución adicional:** obtener el manifiesto exacto del paquete, hashes y licencias transitivas, revisar por completo los scripts y sus dependencias, estimar si puede haber costes, mostrar archivos/configuraciones que cambiará y someter la activación a su gate. Evitar ramas móviles, `@latest`, `curl | bash` y ejecuciones de diagnóstico vía `npx` sin paquete previamente auditado y anclado. El inventario de terceros persistente está en [`THIRD_PARTY.md`](../../THIRD_PARTY.md).

## Resultado del gate

| Control | Estado | Evidencia / impedimento |
| --- | --- | --- |
| Identidad de los cuatro upstream y commits concretos | **PASS** | `git ls-remote`, API de commits y árboles sin truncado |
| Licencia de las cuatro skills Anthropic seleccionadas | **PASS** | Cuatro `LICENSE.txt` Apache-2.0 en los respectivos directorios |
| Copia declarativa `frontend-design` con atribución | **PASS (en disco)** | Dos archivos en `/skills`, SHA-256 verificados; carga activa por cliente sin probar |
| Creación de seis skills propias sin scripts | **PASS (estructura)** | Seis `SKILL.md` originales; requisitos definitivos pendientes de §3.3 íntegro |
| Auditoría integral de hooks/MCP y árbol transitivo | **PENDING** | Lectura estática selectiva, sin pruebas de ejecución ni análisis completo de dependencias |
| Coste cero garantizado para HF Jobs, AWS, REA y APIs | **PENDING/NO AUTORIZADO** | Servicios y motores externos podrían generar cargos |
| Aprobación del gate del Plan Maestro v3 | **FAIL/PENDING** | `PLAN.md` completo ya incorporado; faltan pruebas físicas S1–S4/S7, cierre S5 y aprobación expresa para Fase 1 |
