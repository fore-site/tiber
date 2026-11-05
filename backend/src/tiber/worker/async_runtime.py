"""Reuse one asyncio loop per Celery worker process."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Lock
from typing import Any

from celery.signals import worker_process_shutdown

_runner: asyncio.Runner | None = None
_runner_lock = Lock()


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on the worker's persistent event loop."""
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = asyncio.Runner()
        return _runner.run(coro)


@worker_process_shutdown.connect(weak=False)
def close_async_runtime(**_: object) -> None:
    """Dispose async database resources before closing the worker event loop."""
    global _runner
    with _runner_lock:
        if _runner is None:
            return

        from ..core.database import engine

        _runner.run(engine.dispose())
        _runner.close()
        _runner = None
