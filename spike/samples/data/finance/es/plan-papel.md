# Caso de práctica: la serie «DEMO» en modo papel

> **Solo simulación.** Este caso usa la cuenta de papel de SPIKE (dinero simulado). No hay ninguna orden real,
> ninguna cuenta de un bróker y ninguna clave. Los precios de `precios.csv` están inventados: no son de ningún
> mercado real. Nada de esto es asesoramiento financiero.

## Situación

Tienes una cuenta de papel con dinero simulado y una serie de 60 sesiones de un activo inventado llamado DEMO. El
precio sube con suavidad durante las primeras siete semanas y después baja. Quieres practicar cómo se razona una
decisión antes de tomarla, no ganar dinero.

## Tareas sugeridas

1. **Mira la serie.** Pide un resumen: precio inicial y final, máximo, mínimo y la caída más larga seguida.
2. **Prueba una regla simple.** Pide una simulación histórica (backtest) de cruce de dos medias móviles, por
   ejemplo de 5 y 20 sesiones, sobre `precios.csv`, y compárala con comprar y mantener.
3. **Mide el riesgo.** Pide la mayor caída desde un máximo y la variación diaria típica.
4. **Opera en papel.** Si la regla da una señal, pide una orden de papel pequeña con `paper_order` (no más del
   10 % de la cuenta simulada) y que explique por qué, qué haría cambiar de opinión y cuándo revisarla.
5. **Escribe el diario.** Una nota corta con la decisión, el motivo y lo que habrías hecho distinto.

## Límites del caso

- Tamaño máximo de cada orden de papel: 10 % de la cuenta simulada.
- Ninguna orden a crédito ni en corto.
- Si algo parece una orden real, para y avisa: este proyecto no las admite.
- Las simulaciones históricas no prometen resultados futuros; di siempre qué no se ha medido.
