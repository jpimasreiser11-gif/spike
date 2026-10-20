# Cálculo de Cuota Mensual - Sistema Francés

## Datos del Préstamo
- **Monto principal (P):** 10.000 €
- **Tasa nominal anual:** 5%
- **Plazo:** 3 años (36 meses)

## Fórmula del Sistema Francés
La fórmula utilizada es:

```
Cuota = P × i × (1 + i)^n / ((1 + i)^n - 1)
```

Donde:
- **P** = Monto principal del préstamo
- **i** = Tasa de interés mensual = tasa anual / 12
- **n** = Número de meses de amortización

## Cálculos Detallados

1. **Tasa mensual (i):**
   i = 0.05 / 12 = 0.004166666667

2. **Número de meses (n):**
   n = 3 años × 12 meses/año = 36 meses

3. **Factor de amortización:**
   (1 + i)^n = (1 + 0.05/12)^36 = 1.161472231333

4. **Cuota mensual:**
   Cuota = 10.000 × (0.05/12) × (1 + 0.05/12)^36 / ((1 + 0.05/12)^36 - 1)
   
   Cuota = 10.000 × 0.004166666667 × 1.161472231333 / (1.161472231333 - 1)
   
   Cuota = 299.71 €

## Resultado Final
**Cuota mensual:** **299.71 €** (aproximadamente)

Con precisión: 299.7089710466555 €

## Observación
En el sistema francés (amortización francés), se paga un interés fijo sobre el capital restante y una parte del principal que disminuye con el tiempo. Cada cuota tiene el mismo monto total, pero se compone de:
- Interés: 41.67 € (fijo)
- Amortización: 258.04 € (crece progresivamente)
