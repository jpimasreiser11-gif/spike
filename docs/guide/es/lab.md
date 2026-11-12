# Model Lab (comparador A/B de modelos y especialistas)

Idioma: **Español** | [English](../en/lab.md) · [Índice de la guía](README.md)

![Model Lab (comparador A/B de modelos y especialistas)](../images/lab.png)

## Qué hace

Compara el mismo prompt, o hasta 16 casos JSON, entre especialistas y proveedores, con la latencia, los tokens y el coste estimado de cada respuesta. No se envía nada hasta que pulsas **Ejecutar ahora**.

## Cómo se usa paso a paso

1. Pulsa **Lab** en la barra superior para abrir el comparador.
2. Escribe el **Prompt** o, en **Casos de evaluación (JSON opcional)**, pega una lista de casos `{"prompt": "…", "expected": "…"}`; los que tienen `expected` se puntúan por coincidencia exacta.
3. En cada fila elige **Especialista** y **Proveedor**; **Añadir comparación** añade otra fila (hasta 8).
4. Pulsa **Estimar comparación**: muestra cuántas solicitudes se harán y su coste estimado sin enviar nada. Después pulsa **Ejecutar ahora**.
5. Cada resultado muestra la latencia (ms), los tokens de entrada y salida y, con casos, la puntuación exacta. Las últimas 50 ejecuciones quedan en **Ejecuciones guardadas** y se pueden exportar en JSON.
6. **Estimar prueba de proveedor** comprueba, con hasta cinco solicitudes pequeñas, qué admite el proveedor de la primera fila (herramientas, JSON, imagen, streaming y contexto). Nunca ejecuta herramientas.

## Límites reales

- Como máximo 32 respuestas por ejecución y 128 tokens de salida por respuesta, sin herramientas.
- Cuando varias filas usan el mismo `llama-server` local, comparten sus ranuras paralelas, así que el tiempo total depende de cuántas tenga.
- Un proveedor de pago queda bloqueado si no lo has permitido o si alcanzaría su tope mensual (Ajustes → Proveedores); consulta [../../STATUS.md](../../STATUS.md).

## Cómo comprobarlo

- Ejecuta `.venv/bin/python -m pytest -q tests/test_lab.py`.
