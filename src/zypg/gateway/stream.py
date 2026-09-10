from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

from zypg.storage import redis_store


def sse_pack(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def iter_sse(events: Iterable[tuple[str, Any]]) -> AsyncIterator[str]:
    for name, data in events:
        yield sse_pack(name, data)


def emit(sid: str | None, event: str, data: Any) -> None:
    if sid:
        redis_store.publish_stream(sid, {"event": event, "data": data})
