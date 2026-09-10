from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

import httpx

from zypg.config import settings

OcrBackend = Callable[[str], dict[str, Any]]
_backend: OcrBackend | None = None


def set_backend(fn: OcrBackend | None) -> None:
    global _backend
    _backend = fn


def ocr_image(path: str) -> dict[str, Any]:
    """Return {text, garbled, reason}."""
    if _backend is not None:
        return _backend(path)
    token = settings.mineru_key
    base = (settings.ocr_url or "").rstrip("/")
    if not token or not base:
        return {"text": "", "garbled": True, "reason": "no_ocr"}
    try:
        return _mineru_ocr(path, base, token)
    except Exception as exc:
        return {"text": "", "garbled": True, "reason": f"ocr_error:{exc}"}


def _mineru_ocr(path: str, base: str, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    name = Path(path).name
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{base}/file-urls/batch",
            headers=headers,
            json={
                "files": [{"name": name, "data_id": Path(path).stem, "is_ocr": True}],
                "model_version": "vlm",
            },
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(body.get("msg") or "mineru apply url failed")
        batch_id = body["data"]["batch_id"]
        url = body["data"]["file_urls"][0]
        data = Path(path).read_bytes()
        put = client.put(url, content=data, headers={})
        if put.status_code >= 300:
            raise RuntimeError(f"upload failed {put.status_code}")
        zip_url = None
        for i in range(60):
            if i:
                time.sleep(1)
            q = client.get(f"{base}/extract-results/batch/{batch_id}", headers=headers)
            q.raise_for_status()
            qd = q.json()
            results = (qd.get("data") or {}).get("extract_result") or []
            if not results:
                continue
            item = results[0]
            state = item.get("state")
            if state == "done":
                zip_url = item.get("full_zip_url")
                break
            if state == "failed":
                raise RuntimeError(item.get("err_msg") or "ocr failed")
        if not zip_url:
            return {"text": "", "garbled": True, "reason": "ocr_timeout"}
        zbytes = client.get(zip_url, timeout=120.0).content
    text = _md_from_zip(zbytes)
    garbled = (not text) or len(text.strip()) < 2
    return {"text": text, "garbled": garbled, "reason": "ocr_garbled" if garbled else ""}


def _md_from_zip(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        for n in names:
            if n.endswith("full.md") or n.endswith(".md"):
                return zf.read(n).decode("utf-8", errors="ignore")
        for n in names:
            if n.endswith(".json"):
                return zf.read(n).decode("utf-8", errors="ignore")[:4000]
    return ""
