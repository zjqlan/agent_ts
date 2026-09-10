from __future__ import annotations

import json
from typing import Any

import redis

from zypg.config import settings

_client: redis.Redis | None = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def reset() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None


def ping() -> bool:
    return bool(client().ping())


def set_session(sid: str, data: dict[str, Any], ttl: int = 3600) -> None:
    client().setex(f"session:{sid}", ttl, json.dumps(data, ensure_ascii=False))


def get_session(sid: str) -> dict[str, Any]:
    raw = client().get(f"session:{sid}")
    return json.loads(raw) if raw else {}


def publish_stream(sid: str, event: dict[str, Any]) -> None:
    client().publish(f"stream:{sid}", json.dumps(event, ensure_ascii=False))


def set_task(a2a_id: str, mapping: dict[str, Any], ttl: int = 86400) -> None:
    key = f"task:{a2a_id}"
    pipe = client().pipeline()
    pipe.hset(key, mapping={k: json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v for k, v in mapping.items()})
    pipe.expire(key, ttl)
    pipe.execute()


def get_task(a2a_id: str) -> dict[str, str]:
    return dict(client().hgetall(f"task:{a2a_id}") or {})


def delete_task(a2a_id: str) -> None:
    client().delete(f"task:{a2a_id}")


def set_roster_gate(class_id: str, ok: bool) -> None:
    client().set(f"roster:gate:{class_id}", "1" if ok else "0")


def roster_gate(class_id: str) -> bool | None:
    v = client().get(f"roster:gate:{class_id}")
    if v is None:
        return None
    return v == "1"


def set_insight_hot(class_id: str, payload: dict[str, Any], ttl: int = 300) -> None:
    client().setex(f"insight:hot:{class_id}", ttl, json.dumps(payload, ensure_ascii=False))


def get_insight_hot(class_id: str) -> dict[str, Any] | None:
    raw = client().get(f"insight:hot:{class_id}")
    return json.loads(raw) if raw else None


def set_teacher_session(token: str, teacher_id: str, ttl: int = 604800) -> None:
    client().setex(f"teacher_session:{token}", ttl, teacher_id)


def get_teacher_session(token: str) -> str | None:
    raw = client().get(f"teacher_session:{token}")
    return str(raw) if raw else None


def delete_teacher_session(token: str) -> None:
    client().delete(f"teacher_session:{token}")
