from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_MONOTONIC_RESOLUTION = 0.0001


def async_fire_time_changed(utc_datetime: datetime) -> None:
    timestamp = utc_datetime.timestamp()
    loop = asyncio.get_running_loop()
    for task in list(loop._scheduled):  # type: ignore[attr-defined]  # noqa: SLF001
        if not isinstance(task, asyncio.TimerHandle):
            continue
        if task.cancelled():
            continue

        mock_seconds_into_future = timestamp - time.time()
        future_seconds = task.when() - (loop.time() + _MONOTONIC_RESOLUTION)

        if mock_seconds_into_future >= future_seconds:
            task._run()  # noqa: SLF001
            task.cancel()
