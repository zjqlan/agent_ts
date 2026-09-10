from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from zypg.config import settings
from zypg.storage import mysql

DIM = 384


class VectorIndex(Protocol):
    def add(self, kind: str, ref_id: str, text: str, homework_id: str | None = None) -> int: ...
    def search(self, text: str, k: int = 5, kind: str | None = None) -> list[dict[str, Any]]: ...


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec, axis=-1, keepdims=True)
    n = np.maximum(n, 1e-9)
    return (vec / n).astype("float32")


def hash_embed(text: str, dim: int = DIM) -> np.ndarray:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "little") % (2**32)
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype("float32")
    return _l2_normalize(vec)


def embed_text(text: str) -> np.ndarray:
    from zypg.llm import try_embed

    got = try_embed(text)
    if got is not None:
        arr = np.asarray(got, dtype="float32")
        if arr.shape[-1] != DIM:
            # pad / trim to DIM so FAISS index stays consistent
            out = np.zeros((DIM,), dtype="float32")
            n = min(DIM, arr.shape[-1])
            out[:n] = arr[:n]
            return _l2_normalize(out)
        return _l2_normalize(arr)
    return hash_embed(text)


class FaissIndex:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "indexes" / "items.faiss")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._index = None

    def _load(self):
        import faiss

        if self._index is None:
            if self.path.exists():
                self._index = faiss.read_index(str(self.path))
            else:
                self._index = faiss.IndexFlatIP(DIM)
        return self._index

    def _save(self) -> None:
        import faiss

        if self._index is not None:
            faiss.write_index(self._index, str(self.path))

    def add(self, kind: str, ref_id: str, text: str, homework_id: str | None = None) -> int:
        import faiss

        index = self._load()
        vec = embed_text(text).reshape(1, -1)
        faiss_id = mysql.next_faiss_id()
        if not index.is_trained:
            pass
        # IndexFlatIP add: sequential ids 0..n-1. Keep faiss_id aligned by padding if needed.
        while index.ntotal < faiss_id:
            pad = np.zeros((1, DIM), dtype="float32")
            index.add(pad)
        index.add(vec)
        mysql.insert_embedding_meta(
            faiss_id,
            kind,
            ref_id,
            homework_id,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        self._save()
        return faiss_id

    def search(self, text: str, k: int = 5, kind: str | None = None) -> list[dict[str, Any]]:
        index = self._load()
        if index.ntotal == 0:
            return []
        vec = embed_text(text).reshape(1, -1)
        scores, ids = index.search(vec, min(k * 4, max(index.ntotal, 1)))
        meta = {int(m["faiss_id"]): m for m in mysql.list_embedding_meta()}
        out: list[dict[str, Any]] = []
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0:
                continue
            row = meta.get(int(idx))
            if not row:
                continue
            if kind and row["kind"] != kind:
                continue
            out.append({**row, "score": float(score)})
            if len(out) >= k:
                break
        return out


_default: FaissIndex | None = None


def get_index() -> FaissIndex:
    global _default
    if _default is None:
        _default = FaissIndex()
    return _default
