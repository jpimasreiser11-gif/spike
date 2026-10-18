# Recording the README demo

`web/e2e/demo.mjs` records the real app answering a real question with the real local model, in real time: the chat
loads, a short question about ETFs is typed at human speed, the Finance chip shows and the answer streams in.

```bash
spike serve                   # starts llama-server and loads the model; /api/runtime must say "running": true
(cd web && npm ci && npx playwright-core install chromium)          # once; also fetches Playwright's ffmpeg
node web/e2e/demo.mjs http://127.0.0.1:8740 demo-out   # optional: --lang en, --question "...", --timeout 600
```

It writes `demo.webm` (raw), `demo.gif` (12 fps, 960 px), `demo.mp4` (H.264) and `demo.json` (question, date, model
file, provider, hardware, and the seconds from sending to the specialist chip, first token and finished answer,
measured in the page). GIF and MP4 need `ffmpeg` on the PATH; without it the script prints the commands.

- Real time: nothing is scripted, sped up, cut or edited. Caption it with the machine and model, from `demo.json`:
  "recorded in real time on `<machine>`, Qwen3.5-4B Q4_K_M" (and say so if an earlier question warmed the model up).
- It fails when the answer errors or the model asks for a tool permission, and warns when the local engine is off.
- A recording made against `tests/e2e/serve_scripted.py` (a fake model) only proves that the script works. It is not
  a demo and must never be published as one.
