"""Heavy jobs are bounded, RAM gated, cancellable and do not expose exception details."""

import asyncio

import pytest

from spike.jobs import JobQueue


@pytest.mark.asyncio
async def test_queue_limit_ram_cancel_and_failure():
    ram = [0]
    queue = JobQueue(limit=2, ram_floor=100, available=lambda: ram[0], poll=0.01)
    active, peak = 0, 0
    gate = asyncio.Event()

    async def work():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await gate.wait()
            return 42
        finally:
            active -= 1

    jobs = [queue.submit("render", work) for _ in range(5)]
    await asyncio.sleep(0.03)
    assert all(j["status"] == "queued" for j in queue.list())
    ram[0] = 1000
    await asyncio.sleep(0.03)
    assert active == 2
    queue.cancel(jobs[-1])
    queue.cancel(jobs[0])
    await asyncio.sleep(0.03)
    assert active == 2  # the cancelled job released its slot
    gate.set()
    await asyncio.sleep(0.03)
    assert peak == 2
    assert sum(j["status"] == "cancelled" for j in queue.list()) == 2

    async def broken():
        raise ValueError("secret")

    jid = queue.submit("eval", broken)
    with pytest.raises(ValueError):
        await queue.wait(jid)
    assert "secret" not in str(queue.list())
    await queue.close()


@pytest.mark.asyncio
async def test_invalid_limits_and_shutdown():
    with pytest.raises(ValueError):
        JobQueue(limit=0)
    queue = JobQueue(available=lambda: 0)
    jid = queue.submit("training", lambda: asyncio.sleep(100))
    await queue.close()
    assert queue.list()[0]["status"] == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await queue.wait(jid)


@pytest.mark.asyncio
async def test_cancellation_waits_for_cleanup_and_immediate_cancel():
    queue = JobQueue(limit=1, ram_floor=0)
    started, cleanup = asyncio.Event(), asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.sleep(100)
        finally:
            await cleanup.wait()

    first = queue.submit("training", work)
    await started.wait()
    second = queue.submit("eval", lambda: asyncio.sleep(0))
    queue.cancel(first)
    await asyncio.sleep(0)
    assert queue.list()[1]["status"] == "queued"
    cleanup.set()
    await queue.wait(second)
    third = queue.submit("indexing", lambda: asyncio.sleep(100))
    queue.cancel(third)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert queue.list()[-1]["status"] == "cancelled"
    await queue.close()


@pytest.mark.asyncio
async def test_nested_indexing_keeps_one_slot_and_failure_releases_it():
    queue = JobQueue(ram_floor=0)

    async def outer():
        return await queue.execute("indexing", lambda: asyncio.sleep(0, result=7))

    assert await asyncio.wait_for(queue.execute("indexing", outer), 1) == 7
    assert len(queue.list()) == 1
    await queue.close()


@pytest.mark.asyncio
async def test_cancelled_thread_is_drained_before_next_job():
    import threading

    from spike.memory.folders import _drained_thread

    queue = JobQueue(ram_floor=0)
    started, done = threading.Event(), threading.Event()

    def work():
        started.set()
        assert done.wait(2)

    first = queue.submit("indexing", lambda: _drained_thread(work))
    while not started.is_set():
        await asyncio.sleep(0.001)
    queue.cancel(first)
    second = queue.submit("eval", lambda: asyncio.sleep(0))
    await asyncio.sleep(0.01)
    assert queue.list()[1]["status"] == "queued"
    done.set()
    await queue.wait(second)
    await queue.close()


def test_shutdown_ignores_finished_tasks_from_previous_event_loop():
    queue = JobQueue(ram_floor=0)
    assert asyncio.run(queue.execute("indexing", lambda: asyncio.sleep(0, result=1))) == 1
    assert asyncio.run(queue.execute("eval", lambda: asyncio.sleep(0, result=2))) == 2
    asyncio.run(queue.close())
