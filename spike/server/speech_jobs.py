"""One local speech/media job per app, including while a disconnected request's thread finishes."""

import asyncio

from fastapi import HTTPException

from spike.media import MediaError


async def execute_speech(state, action, *args, cleanup=None):
    if state.speech_lock.locked():
        raise HTTPException(409, 'speech_busy')
    async with state.speech_lock:
        job = asyncio.create_task(asyncio.to_thread(action, *args))
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            # Cancelling to_thread does not kill the child program. Hold the gate until it finishes or times out.
            try:
                result = await job
                if cleanup:
                    cleanup(result)
            except Exception:
                pass
            raise
        except (MediaError, OSError, UnicodeError) as exc:
            raise HTTPException(400, str(exc) if isinstance(exc, MediaError) else 'subtitles_command') from exc
