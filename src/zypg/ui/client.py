from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import httpx

API = os.environ.get("ZYPG_API", "http://127.0.0.1:8765")


def base() -> str:
    return os.environ.get("ZYPG_API") or API


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _raise(r: httpx.Response) -> None:
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text}
    msg = data.get("detail") or data.get("error") or r.text
    if isinstance(msg, dict):
        msg = msg.get("message") or str(msg)
    raise ApiError(str(msg), r.status_code)


def _headers() -> dict[str, str]:
    token = os.environ.get("ZYPG_TOKEN") or ""
    try:
        import streamlit as st

        token = st.session_state.get("auth_token") or token
    except Exception:
        pass
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def get(path: str, **params: Any) -> dict[str, Any]:
    r = httpx.get(
        f"{base()}{path}",
        params={k: v for k, v in params.items() if v not in (None, "")},
        headers=_headers(),
        timeout=30.0,
    )
    if r.status_code >= 400:
        _raise(r)
    return r.json()


def post_json(path: str, body: dict[str, Any] | None = None, timeout: float = 120.0, **params: Any) -> dict[str, Any]:
    r = httpx.post(
        f"{base()}{path}",
        params={k: v for k, v in params.items() if v not in (None, "")},
        json=body or {},
        headers=_headers(),
        timeout=timeout,
    )
    if r.status_code >= 400:
        _raise(r)
    return r.json()


def patch_json(path: str, body: dict[str, Any], **params: Any) -> dict[str, Any]:
    r = httpx.patch(f"{base()}{path}", params=params, json=body, headers=_headers(), timeout=30.0)
    if r.status_code >= 400:
        _raise(r)
    return r.json()


def delete(path: str, **params: Any) -> dict[str, Any]:
    r = httpx.delete(
        f"{base()}{path}",
        params={k: v for k, v in params.items() if v not in (None, "")},
        headers=_headers(),
        timeout=30.0,
    )
    if r.status_code >= 400:
        _raise(r)
    if not r.content:
        return {"ok": True}
    try:
        return r.json()
    except Exception:
        return {"ok": True}


def post_file(path: str, upload, extra: dict[str, str] | None = None) -> dict[str, Any]:
    files = {"file": (upload.name, upload.getvalue())}
    r = httpx.post(f"{base()}{path}", data=extra or {}, files=files, headers=_headers(), timeout=60.0)
    if r.status_code >= 400:
        _raise(r)
    return r.json()


def save_upload(upload, kind: str) -> str:
    name = getattr(upload, "name", None) or "upload.bin"
    data = upload.getvalue() if hasattr(upload, "getvalue") else upload.read()
    return _write_local_upload(name, data, kind)


def _write_local_upload(name: str, data: bytes, kind: str) -> str:
    import uuid

    from zypg.storage.files import file_root

    dest = file_root() / kind
    dest.mkdir(parents=True, exist_ok=True)
    safe = Path(name).name or "upload.bin"
    path = dest / f"{uuid.uuid4().hex[:10]}_{safe}"
    path.write_bytes(data)
    return str(path)


def extra_from_uploads(files) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    scans: list[str] = []
    for f in files or []:
        name = (getattr(f, "name", "") or "").lower()
        if name.endswith((".csv", ".xlsx", ".xls")):
            extra["path"] = save_upload(f, "rosters")
            extra["roster_path"] = extra["path"]
        elif name.endswith((".md", ".docx", ".doc", ".pdf", ".txt")):
            extra["path"] = save_upload(f, "papers")
            extra["paper_path"] = extra["path"]
        elif name.endswith((".png", ".jpg", ".jpeg")):
            scans.append(save_upload(f, "scans"))
    if scans:
        extra["scan_paths"] = scans
    return extra


def understand_ask(
    text: str,
    extra: dict[str, Any] | None,
    class_id: str | None = None,
    homework_id: str | None = None,
) -> dict[str, Any]:
    return post_json(
        "/ask/understand",
        {
            "text": text,
            "extra": extra or {},
            "class_id": class_id or None,
            "homework_id": homework_id or None,
        },
    )


def start_ask(
    text: str,
    class_id: str | None,
    homework_id: str | None,
    conversation_id: str | None,
    sid: str | None,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    r = httpx.post(
        f"{base()}/ask/start",
        json={
            "text": text,
            "class_id": class_id or None,
            "homework_id": homework_id or None,
            "conversation_id": conversation_id or None,
            "sid": sid or None,
            "extra": extra or {},
        },
        headers=_headers(),
        timeout=30.0,
    )
    if r.status_code >= 400:
        _raise(r)
    return r.json()


def ask_stream(
    text: str,
    class_id: str | None,
    homework_id: str | None,
    conversation_id: str | None,
    sid: str | None,
    extra: dict[str, Any] | None,
    on_token: Callable[[str], None] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    body = {
        "text": text,
        "class_id": class_id or None,
        "homework_id": homework_id or None,
        "conversation_id": conversation_id or None,
        "sid": sid or None,
        "extra": extra or {},
    }
    acc = ""
    done: dict[str, Any] = {}
    with httpx.stream("POST", f"{base()}/ask/stream", json=body, headers=_headers(), timeout=1800.0) as resp:
        event = None
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = {"text": payload}
                if event == "token":
                    acc += data.get("text") or ""
                    if on_token:
                        on_token(acc)
                elif event == "progress":
                    if on_progress:
                        on_progress(data)
                elif event == "done":
                    done = data
                    acc = data.get("summary") or acc
                elif event == "error":
                    acc = data.get("error") or acc
    done["summary"] = acc or done.get("summary") or done.get("error") or ""
    return done


def file_url(path) -> str:
    from urllib.parse import quote

    from zypg.storage.files import relpath as to_rel

    p = Path(path)
    stored = to_rel(p) if p.is_absolute() else str(path)
    stored = stored.replace("\\", "/")
    return f"{base()}/ui/file?path={quote(stored)}"


def abs_data(p: str) -> Path:
    from zypg.config import ROOT, settings

    path = Path(p)
    if path.is_absolute():
        return path
    cand = settings.data_dir / p
    if cand.exists():
        return cand
    return ROOT / "data" / p
