# Checkpoint sweep: medicine

Recipe `training/configs/medicine.yaml`, trained at commit `a1dc5beec0b4060af91103275557e64cf0883266` for 25469 iterations. Chosen on `medicine-select, general-select` (the recipe's rule with the suites renamed), measured against the base model in one run (`training/runs/medicine/sweep/select`).

| candidate | asked | iteration | scale | medicine-select Δ pts (p) | general-select Δ pts | passes |
|---|---|---|---|---|---|---|
| spike-medicine-it3200-s1 | 0.125 | 3200 | 1 | +26.17 (0) | -5.50 | no |
| spike-medicine-it6400-s1 | 0.25 | 6400 | 1 | +29.33 (0) | -7.75 | no |
| spike-medicine-it12800-s1 | 0.5 | 12800 | 1 | +31.50 (0) | -8.25 | no |
| spike-medicine-it25469-s0.5 | 1@0.5 | 25469 | 0.5 | +31.33 (0) | -7.25 | no |

Chosen: none, no candidate passed.
- spike-medicine-it3200-s1: medicine-select: +26.17 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -5.50 pts (max drop 1.5)
- spike-medicine-it6400-s1: medicine-select: +29.33 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -7.75 pts (max drop 1.5)
- spike-medicine-it12800-s1: medicine-select: +31.50 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -8.25 pts (max drop 1.5)
- spike-medicine-it25469-s0.5: medicine-select: +31.33 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -7.25 pts (max drop 1.5)
