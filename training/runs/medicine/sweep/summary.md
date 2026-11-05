# Checkpoint sweep: medicine

Recipe `training/configs/medicine.yaml`, trained at commit `00a00906402efc01114c996c5578bedd6f2abf3a` for 13270 iterations. Chosen on `medicine-select, general-select` (the recipe's rule with the suites renamed), measured against the base model in one run (`training/runs/medicine/sweep/select`).

| candidate | asked | iteration | scale | medicine-select Δ pts (p) | general-select Δ pts | passes |
|---|---|---|---|---|---|---|
| spike-medicine-it1600-s1 | 0.125 | 1600 | 1 | +23.83 (0) | -11.75 | no |
| spike-medicine-it3400-s1 | 0.25 | 3400 | 1 | +31.00 (0) | -8.00 | no |
| spike-medicine-it6600-s1 | 0.5 | 6600 | 1 | +28.00 (0) | -7.25 | no |
| spike-medicine-it13270-s0.5 | 1@0.5 | 13270 | 0.5 | +33.83 (0) | +0.00 | yes |

Chosen: `spike-medicine-it13270-s0.5`
- spike-medicine-it1600-s1: medicine-select: +23.83 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -11.75 pts (max drop 1.5)
- spike-medicine-it3400-s1: medicine-select: +31.00 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -8.00 pts (max drop 1.5)
- spike-medicine-it6600-s1: medicine-select: +28.00 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: -7.25 pts (max drop 1.5)
- spike-medicine-it13270-s0.5: medicine-select: +33.83 pts (need ≥ 3.0), p = 0 (need ≤ 0.05); general-select: +0.00 pts (max drop 1.5)

**Final, on the acceptance suites (medicine, general): ACCEPTED** (`training/runs/medicine/sweep/final`)
- medicine: +35.07 pts (need ≥ 3.0), p = 0 (need ≤ 0.05)
- general: -0.62 pts (max drop 1.5)
