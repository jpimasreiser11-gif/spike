# Studio: integración con la app actual

El rescate S1 conserva los módulos de proyectos, memoria, skills, conectores, orquestación y API de esta rama.
La comparación con la implementación anterior está en [el informe S1](team/reports/S1.md). Esta página describe
únicamente los contratos rescatados; no anuncia las funciones pendientes del antiguo vídeo conceptual.

- El ZIP `spike-project`, versión 1, incluye opcionalmente `memories`: una lista de `{kind, text}` del proyecto.
  Los archivos antiguos sin esta lista siguen funcionando. Las notas reciben IDs nuevos al importar y quedan en
  el ámbito del proyecto nuevo. Se validan antes de crear registros; un fallo de importación limpia también las notas.
- No viajan los IDs de las notas, su origen local, sus metadatos, las memorias globales ni las de otros proyectos.
  Los índices `file:` se reconstruyen a partir de los archivos; los resúmenes `conversation:` no se trasladan como notas.
  El límite es de 1.000 notas; no se recortan silenciosamente. El tipo y tamaño de cada nota siguen `MemoryStore`.
- Los archivos de proyecto que son enlaces simbólicos o atraviesan uno se rechazan al leer, escribir o borrar,
  y se omiten del listado y del ZIP. Si el propio directorio del proyecto o `files` es un enlace, se rechaza
  antes de acceder o crear carpetas, también al listar/exportar. Esto es contención de rutas, no un sandbox ni protección
  frente a un proceso local que cambie enlaces simultáneamente.
- El manifiesto del paquete de prueba existente declara `verification.status: not_independently_verified`.
  Una afirmación del modelo o un checksum no certifica la calidad ni la veracidad de la respuesta.
- `/v1/chat/completions` devuelve `usage: null` si no recibe recuentos completos válidos del backend. Un evento
  válido conserva el cero real; varios eventos válidos se suman. Los eventos parciales o inválidos se ignoran;
  en una ejecución con varias llamadas no se estima el uso de llamadas cuyo backend no informó recuentos.
  Con `stream_options.include_usage`, el chunk final de uso sigue la misma regla. Se conserva la API ampliada
  de [INTEGRATIONS.md](INTEGRATIONS.md), incluyendo las herramientas del cliente y los contratos JSON.

Los ZIP y paquetes de prueba contienen texto del usuario: revisarlos antes de compartir. S1 no incorpora el
formato JSON de proyecto antiguo, sus tablas, sus endpoints duplicados, su política `local_only` por proyecto,
su cola de tareas ni sus recibos de activación de adaptadores. La revisión de Claude debe tratar esas diferencias
como trabajo pendiente explícito; la app actual no promete las garantías de privacidad de aquel Studio.

Verificación de estos contratos sin red ni pesos reales:

```sh
.venv/bin/python -m pytest -q tests/test_projects.py tests/test_studio_port.py tests/test_proof.py
LC_ALL=C LANG=C .venv/bin/python -X utf8=0 -m pytest -q tests/test_projects.py tests/test_studio_port.py
```

El smoke de proyectos en `web/e2e/smoke.mjs` incluye exportar/importar una nota. Requiere el servidor de prueba
`tests/e2e/serve_scripted.py` y un navegador existente. No se han medido calidad, rendimiento ni compatibilidad
con pesos reales en S1.
