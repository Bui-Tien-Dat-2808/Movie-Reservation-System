import asyncio
from typing import Any, Coroutine, Set

_background_tasks: Set[asyncio.Task[Any]] = set()


def fire_and_forget(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """
    Launch a background asyncio task and retain a strong reference in a module-level set
    to prevent Python garbage collection from terminating the task before completion.
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
