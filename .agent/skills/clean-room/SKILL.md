---
name: clean-room
description: Garantiza que Spike se implemente de manera independiente al estudiar funcionalidades de terceros, con licencias, atribución y trazabilidad verificables.
---

# Clean room — Spike

## Cuándo aplicar

Durante análisis competitivo, diseño de interfaces, funciones equivalentes, interacción con software propietario, integración de repositorios o uso de herramientas de ingeniería inversa.

## Proceso

1. Comprueba legitimidad de acceso, términos, finalidad permitida y permisos de observación. Limita la observación a material autorizado.
2. Formula una **especificación funcional propia** basada en comportamientos y necesidades, sin copiar implementación ajena, código, assets, fuentes, iconos, textos, nombres o marcas.
3. Separa notas de observación de código de implementación; documenta decisiones independientes y alternativas propias.
4. Si se propone reutilizar un fragmento expresamente licenciado, registra origen, commit/hash, fichero, licencia, avisos, compatibilidad y atribución antes de integrarlo; preferir implementación autónoma cuando no hay permisos claros.
5. Rechaza extracción de secretos, evasión de controles de acceso, licencias eludidas y uso de contenido sobre el que no existan derechos.
6. Revisa cada entrega y sus artefactos binarios para detectar similitudes indebidas y dependencias ocultas.

## Registro

`fuente autorizada | alcance observado | descripción funcional | decisión original | material reutilizado/licencia | comprobación final`.

## Límite

Las herramientas externas (incluido REA) requieren su propia auditoría de cadena de suministro antes de activarse. Una investigación permitida no supone autorización para copiar o redistribuir.
