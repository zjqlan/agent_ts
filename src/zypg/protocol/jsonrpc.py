from __future__ import annotations

from typing import Any


def request(method: str, params: dict[str, Any] | None = None, id: Any = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if id is not None:
        body["id"] = id
    return body


def result(id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "result": value}


def error(id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": err}
