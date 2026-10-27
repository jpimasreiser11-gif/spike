# Local skill marketplace / Marketplace local de skills

The minimal marketplace uses a JSON index you explicitly choose. It has no remote catalog, background refresh,
network access or new dependencies. A repository can carry the index and ZIPs; fetch it yourself, review it, then
use the local copy inside your project. Direct git URLs are not supported by this implementation.

El marketplace mínimo usa un índice JSON elegido explícitamente. No tiene catálogo remoto, actualizaciones en
segundo plano, acceso a red ni dependencias nuevas. Un repositorio puede incluir el índice y sus ZIP; descarga y
revisa tú la copia local dentro del proyecto. Esta implementación no admite URLs git directas.

## Index / Índice

```json
{
  "packs": [
    {
      "id": "my-pack",
      "license": "Apache-2.0",
      "sha256": "<64 hexadecimal characters / 64 caracteres hexadecimales>",
      "path": "my-pack.zip"
    }
  ]
}
```

Replace the hash with the SHA-256 of the ZIP bytes. The placeholder above is deliberately invalid. Each entry
requires exactly these four fields; identifiers must be unique. Paths are relative to the index directory;
index, archives and destination must resolve inside the current working directory. Absolute archive paths,
parent traversal, URL paths and symlinks escaping the workspace are refused. The index can be empty.

Sustituye el hash por el SHA-256 de los bytes del ZIP. El marcador del ejemplo es deliberadamente inválido.
Cada entrada requiere exactamente estos cuatro campos; los identificadores deben ser únicos. Las rutas son
relativas al directorio del índice; índice, archivos y destino deben permanecer dentro del directorio actual.
Se rechazan rutas absolutas de archivos, rutas ascendentes, URLs y enlaces fuera del proyecto. El índice puede estar vacío.

A ZIP contains one or more top-level skill folders, each with `SKILL.md` and optional resources. All skills in a
pack must declare the index's license (from the validator's allowlist). Nothing in a pack runs during installation.
Archive and uncompressed content limits are 50 MiB, 2,000 entries; the index limit is 1 MiB and 1,000 packs.

Un ZIP contiene una o más carpetas de skills en su raíz, cada una con `SKILL.md` y recursos opcionales. Todas deben
declarar la licencia del índice, aceptada por el validador. La instalación no ejecuta contenido del paquete.
Los límites son 50 MiB de ZIP y de contenido descomprimido, 2.000 entradas, y un índice de 1 MiB y 1.000 paquetes.

## Commands / Comandos

Run from the project root / Ejecuta desde la raíz del proyecto:

```sh
spike skills list catalog/index.json --lang es
spike skills install catalog/index.json my-pack --destination .spike/skills --yes --lang es
spike skills validate .spike/skills --lang es
```

`list` is read-only. `install` requires explicit write approval (`--yes`). It checks the SHA-256 before extraction,
stages the archive in the workspace, runs the same validator as `skills validate`, and publishes only after all
skills pass. It refuses existing names rather than replacing them. Validation failures leave the destination
untouched; publication failures remove only newly created skill folders. No installation history is written.

`list` solo lee. `install` exige permiso explícito de escritura (`--yes`). Comprueba SHA-256 antes de extraer,
prepara el archivo dentro del proyecto y ejecuta el mismo validador que `skills validate`. Solo publica cuando
todas las skills pasan. Rechaza nombres existentes. Los fallos de validación dejan intacto el destino; los fallos
al publicar eliminan solo las carpetas nuevas. No se escribe historial de instalación.

To make this project-local library visible to the app, start it with `SPIKE_HOME` set to the project's `.spike`
folder (or install into the `skills` folder of an existing project-local `SPIKE_HOME`). A running app needs a restart
to reload CLI-installed skills. Do not point `SPIKE_HOME` at an unrelated installation just to install a pack.

Para que la app vea esta biblioteca local, inicia la app con `SPIKE_HOME` apuntando a `.spike` del proyecto
(o instala en `skills` de un `SPIKE_HOME` local existente). Una app ya abierta necesita reiniciarse para cargar
skills instaladas desde CLI. No apuntes `SPIKE_HOME` a otra instalación solo para instalar un paquete.

Integrity confirms agreement with the index, not publisher identity or instruction safety. Review the index and
skill instructions before choosing a pack. Validation checks format, license, declared tools, size and possible
literal secrets; it does not execute scripts or evaluate instruction quality. The nine new profiles and five
`template.md` resources are original Apache-2.0 content. They are instruction profiles, not measured model capabilities.

La integridad comprueba coincidencia con el índice, no la identidad del autor ni la seguridad de las instrucciones.
Revisa el índice y las instrucciones antes de elegir un paquete. La validación comprueba formato, licencia,
herramientas declaradas, tamaño y posibles secretos; no ejecuta scripts ni evalúa la calidad de las instrucciones.
Los nueve perfiles nuevos y sus cinco `template.md` son contenido original Apache-2.0. Son perfiles de instrucciones,
no capacidades medidas del modelo.
