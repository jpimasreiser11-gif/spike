# Audio and subtitles (A14)

A14 extends A13's local voice setup. Open **Audio y subtítulos / Audio and subtitles** in the sidebar. Import an SRT
or WebVTT file to edit immediately, or enter the relative path of an existing audio/video file in the current project
(or personal workspace). To transcribe, configure whisper.cpp's model in the chat **Image and voice** controls, enable
voice and explicitly authorize the selected file. No model is downloaded, no provider is contacted and opening the
editor runs no program.

The editor supports text and millisecond timing changes, shifting all cues, splitting a cue, merging adjacent cues,
20 levels of undo and SRT/VTT downloads. Split halves the time and word count; it is not word alignment. There is a warning
before discarding unexported changes, and browser navigation gets a beforeunload warning. Closing while a job runs does
not cancel the external program: it finishes or times out and its result is discarded. Keep an SRT/VTT for later editing;
drafts are not automatically persisted. A successful export clears the unsaved flag. Pages show 25 cues at a time.

## Local programs and limits

- `whisper-cli` is detected on PATH, with the A13 `speech.whisper_model` inside the personal workspace. Calls use
  automatic language, SRT output, CPU only and two threads. There are no word timestamps or speaker diarization claims.
- Mono PCM16 WAV at 16 kHz works directly. Other WAV, audio and video inputs require `ffmpeg` and `ffprobe` for inspection
  and conversion. Formats: WAV, MP3, M4A, AAC, OGG, FLAC, MP4, MOV, MKV and WebM; actual codec support depends on the binaries.
- Burning captions requires a separate approval, a video file, `ffmpeg` built with the `subtitles`/libass filter and
  H.264/AAC encoders, plus `ffprobe`. It downloads a new MP4 and never overwrites the source. No auto-play or publishing.
- Input/render limit: 250 MB; media duration: 10 minutes. Each external command times out after 5 minutes. Video bounds:
  at most 4096 on either side and 4096 × 2160 pixels. The output is probed again and rejected if truncated.
- One speech/media job per app process, shared with A13 dictation and Piper. A disconnected request holds the gate until
  its worker thread finishes; other speech jobs return `speech_busy`. This is not a machine-wide scheduler and does not
  claim coordination with external training processes or other SPIKE processes.
- Text limit: 1 MB, 1000 non-overlapping cues, 2000 characters per cue, timestamps within 24 hours. Negative times, empty
  cues, blank lines inside a cue and overlaps are rejected. The plain editor rejects styling/positioning rather than
  silently dropping it. Cue IDs are regenerated; WebVTT NOTE blocks are ignored. UTF-8 and CRLF/BOM imports are supported.
- Automatic transcripts require human review. **Not measured with real weights.** No precision, speed or universal
  platform compatibility claim is made.

## Data flow and isolation

All routes live under `/api/subtitles`, with the existing same-computer/origin checks. GET returns availability only.
POST `/import`, `/edit` and `/export` process plain text; `/transcribe` and `/burn` additionally require `approved:true`.
Requests identify the current `project_id` or personal workspace. Media paths must be relative, inside that scope and
free of symlinks. The source is copied into a unique temporary folder before processing. Subprocesses use argument
arrays, fixed filter filenames, bounded protocols/demuxers and no shell. This is not a new OS sandbox or certification
of third-party decoders. Only use installed programs you trust.

Transcription folders are deleted after success or failure. A rendered video's folder is deleted after the HTTP download;
cancellation before response delivery and an interrupted download also clean it up. An abrupt process crash may leave a `subtitles-*` temporary
folder, which may contain private media. Downloads go to the user's browser download location. Exports are no-store;
provider keys, tool logs and model output outside the selected source are not included. Caption text is never rendered
as HTML in the editor; exports escape markup and retain literal text on reimport.

## Validation and delivery

`tests/test_subtitles.py` covers SRT/VTT round trips, edits, Unicode, invalid timings, bounds, fake whisper/ffmpeg/ffprobe,
missing binaries, symlinks, command failures/timeouts and cleanup. `tests/test_subtitles_api.py` covers local origin,
approval, settings, shared job exclusion, cancellation and download cleanup. `web/src/subtitles.test.tsx` covers the
explicit approval and unsaved-change flows. The full browser smoke exercises transcription through scripted programs,
text edits, split/merge/shift, VTT reimport, render approval, downloads and mobile layout.

On the development Mac, a one-second synthetic video passed **real ffprobe inspection and ffmpeg audio conversion**.
Whisper was replaced by a fake that checked the converted WAV; this does not measure recognition quality. The installed
ffmpeg lacks the subtitles/libass filter, so real burn-in was unavailable; its safe failure and cleanup were checked.
Rendering through the real API is covered with fake binaries and in the browser with scripted programs.

This branch is stacked on `codex/a13` while Claude reviews A13. Merge A13 first, then review/rebase A14; do not mark its
board dependency done solely because a branch exists. No training, public release or installer certification is included.

Implementation references: [whisper.cpp CLI](https://github.com/ggml-org/whisper.cpp/blob/master/examples/cli/cli.cpp),
[FFmpeg filter documentation](https://github.com/FFmpeg/FFmpeg/blob/master/doc/filters.texi), and
[WebVTT format](https://developer.mozilla.org/en-US/docs/Web/API/WebVTT_API/Web_Video_Text_Tracks_Format).
