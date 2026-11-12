# Model Lab (A/B Model and Specialist Comparator)

Language: [Español](../es/lab.md) | **English** · [Guide Index](README.md)

![Model Lab (A/B Model and Specialist Comparator)](../images/lab.png)

## What it does

Compares the same prompt, or up to 16 JSON cases, across specialists and providers, with each answer's latency, tokens and estimated cost. Nothing is sent until you click **Run now**.

## Step-by-step usage

1. Click **Lab** in the top bar to open the comparator.
2. Type the **Prompt** or, in **Evaluation cases (optional JSON)**, paste a list of `{"prompt": "…", "expected": "…"}` cases; those with `expected` are scored by exact match.
3. Choose a **Specialist** and a **Provider** in each row; **Add comparison** adds another row (up to 8).
4. Click **Estimate comparison**: it shows how many requests will be made and their estimated cost without sending anything. Then click **Run now**.
5. Each result shows the latency (ms), the input and output tokens and, with cases, the exact-match score. The last 50 runs stay in **Saved runs** and can be exported as JSON.
6. **Estimate provider probe** checks, with up to five small requests, what the first row's provider supports (tools, JSON, images, streaming and context). It never runs tools.

## Real limits

- At most 32 answers per run and 128 output tokens per answer, without tools.
- When several rows use the same local `llama-server`, they share its parallel slots, so the total time depends on how many it has.
- A paid provider is blocked unless you allowed it or when it would reach its monthly limit (Settings → Providers); see [../../STATUS.md](../../STATUS.md).

## How to verify

- Run `.venv/bin/python -m pytest -q tests/test_lab.py`.
