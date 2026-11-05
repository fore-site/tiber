import asyncio

from tiber.worker.async_runtime import close_async_runtime, run_async


async def _current_loop_id():
    return id(asyncio.get_running_loop())


def test_worker_runtime_reuses_event_loop():
    """Celery task invocations use the same event loop in a worker process."""
    first = run_async(_current_loop_id())
    second = run_async(_current_loop_id())

    assert first == second
    close_async_runtime()
