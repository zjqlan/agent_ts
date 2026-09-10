from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from zypg.mcp_tools.card_render import decode_student_bits, hw_bits


def _gray(path: str | Path) -> np.ndarray:
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.float32)


def _circle_mean(arr: np.ndarray, cx: int, cy: int, r: int) -> float:
    h, w = arr.shape
    rr = max(3, int(r * 0.65))
    y0, y1 = max(0, cy - rr), min(h, cy + rr + 1)
    x0, x1 = max(0, cx - rr), min(w, cx + rr + 1)
    patch = arr[y0:y1, x0:x1]
    if patch.size == 0:
        return 255.0
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= rr * rr
    vals = patch[mask]
    if vals.size == 0:
        return 255.0
    return float(vals.mean())


def _read_bits(arr: np.ndarray, spec: dict[str, Any]) -> tuple[bool, list[int]]:
    cell = int(spec["cell"])
    y = int(spec["y"])
    h = int(spec["h"])
    n = int(spec["n"])
    x = int(spec["x"])
    markers = bool(spec.get("markers", True))
    cy = y + h // 2

    def sample(col_x: int) -> float:
        pad = max(2, cell // 4)
        x0 = col_x + pad
        x1 = col_x + cell - pad
        y0 = y + pad
        y1 = y + h - pad
        patch = arr[max(0, y0) : y1, max(0, x0) : x1]
        if patch.size == 0:
            return 255.0
        return float(patch.mean())

    if markers:
        start = sample(x)
        if start > 110:
            return False, []
        x += cell
    bits: list[int] = []
    for _ in range(n):
        m = sample(x)
        bits.append(1 if m < 80 else 0)
        x += cell
    if markers:
        end = sample(x)
        if end > 110:
            return False, bits
    return True, bits


def _read_matrix(arr: np.ndarray, spec: dict[str, Any]) -> tuple[bool, list[int]]:
    cell = int(spec["cell"])
    n = int(spec["n"])
    x = int(spec["x"])
    y = int(spec["y"])
    h, w = arr.shape

    def sample(px: int, py: int) -> float:
        y0, y1 = max(0, py - 1), min(h, py + 2)
        x0, x1 = max(0, px - 1), min(w, px + 2)
        patch = arr[y0:y1, x0:x1]
        if patch.size == 0:
            return 255.0
        return float(patch.mean())

    border = sample(x + cell // 2, y + cell // 2)
    if border > 80:
        return False, []
    bits: list[int] = []
    for rr in range(n):
        for cc in range(n):
            px = x + (cc + 1) * cell + cell // 2
            py = y + (rr + 1) * cell + cell // 2
            bits.append(1 if sample(px, py) < 80 else 0)
    return True, bits


def decode_homework(scan_path: str | Path, geometry: dict[str, Any]) -> bool:
    arr = _gray(scan_path)
    expect = hw_bits(geometry["homework_id"], n=int((geometry.get("hw_barcode") or {}).get("n") or 32))
    if geometry.get("hw_barcode"):
        ok, bits = _read_bits(arr, geometry["hw_barcode"])
        if ok and bits == expect:
            return True
    tag = geometry.get("card_tag")
    if tag:
        ok, bits = _read_matrix(arr, tag)
        if ok and bits[:16] == hw_bits(geometry["homework_id"], 16):
            return True
    return False


def decode_id_grid(arr: np.ndarray, geometry: dict[str, Any], blank: np.ndarray | None) -> str | None:
    grid = geometry.get("id_grid") or {}
    slots = grid.get("slots") or []
    if not slots:
        return None
    chars: list[str] = []
    for slot in slots:
        filled: list[tuple[float, str]] = []
        for ch, spec in slot.items():
            cx, cy, r = int(spec["cx"]), int(spec["cy"]), int(spec["r"])
            ms = _circle_mean(arr, cx, cy, r)
            mb = _circle_mean(blank, cx, cy, r) if blank is not None else 245.0
            delta = mb - ms
            if delta > 22:
                filled.append((delta, str(ch)))
        if len(filled) == 1:
            chars.append(filled[0][1])
        elif len(filled) > 1:
            filled.sort(reverse=True)
            if filled[0][0] >= filled[1][0] + 10:
                chars.append(filled[0][1])
            else:
                return None
        else:
            chars.append(" ")
    text = "".join(chars).strip()
    return text or None


def decode_student_no(
    scan_path: str | Path,
    geometry: dict[str, Any],
    blank_path: str | Path | None = None,
) -> str | None:
    arr = _gray(scan_path)
    tag = geometry.get("card_tag")
    if tag:
        ok, bits = _read_matrix(arr, tag)
        if ok and len(bits) >= 64:
            no = decode_student_bits(bits[16:64])
            if no:
                return no
    if geometry.get("student_barcode"):
        ok, bits = _read_bits(arr, geometry["student_barcode"])
        if ok:
            no = decode_student_bits(bits)
            if no:
                return no
    blank = _gray(blank_path) if blank_path else None
    return decode_id_grid(arr, geometry, blank)


def decode_page(scan_path: str | Path, geometry: dict[str, Any]) -> int:
    spec = geometry.get("page_barcode")
    if not spec:
        return 0
    ok, bits = _read_bits(_gray(scan_path), spec)
    if not ok or not bits:
        return 0
    n = 0
    for b in bits:
        n = (n << 1) | int(b)
    n_pages = int(geometry.get("n_pages") or 1)
    if n < 0 or n >= max(n_pages, 1):
        return 0
    return n


def read_bubbles(
    scan_path: str | Path,
    blank_path: str | Path,
    geometry: dict[str, Any],
) -> dict[str, str]:
    """Pixel OMR only. Does not take answer_key."""
    from zypg.mcp_tools.card_render import _item_page

    scan = _gray(scan_path)
    blank = _gray(blank_path)
    n_pages = int(geometry.get("n_pages") or 1)
    page = decode_page(scan_path, geometry) if n_pages > 1 else 0
    out: dict[str, str] = {}
    for item_id, letters in geometry.get("bubbles", {}).items():
        if n_pages > 1 and _item_page(geometry, item_id) != page:
            continue
        filled: list[str] = []
        for letter, spec in letters.items():
            cx, cy, r = int(spec["cx"]), int(spec["cy"]), int(spec["r"])
            ms = _circle_mean(scan, cx, cy, r)
            mb = _circle_mean(blank, cx, cy, r)
            if (mb - ms) > 18:
                filled.append(letter)
        if len(filled) == 1:
            out[item_id] = filled[0]
        elif len(filled) == 0:
            out[item_id] = "empty"
        else:
            out[item_id] = "double"
    return out


def crop_subjective(
    scan_path: str | Path,
    geometry: dict[str, Any],
    item_id: str,
    dest: str | Path,
) -> str:
    box = geometry["subjective"][item_id]
    img = Image.open(scan_path).convert("RGB")
    crop = img.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    crop.save(dest)
    return str(dest)
