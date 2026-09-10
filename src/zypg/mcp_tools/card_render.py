from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from zypg.storage.files import homework_dir, relpath

PAGE_W = 1240
PAGE_H = 1754
MARGIN = 40
BUBBLE_R = 13
LETTERS = ("A", "B", "C", "D")
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ID_CHARS = 8
ID_CELL = 20
ID_COLS = 4
ID_ROWS = 9
TAG_CELL = 6
TAG_N = 8
FOOTER_Y = PAGE_H - 48
OBJ_ROW_H = 36
OBJ_HEAD_H = 20
SUBJ_PREF_H = 260
SUBJ_MIN_H = 160
PAGE_CONT_Y = 148


def _font(size: int) -> ImageFont.ImageFont:
    for p in (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def hw_bits(homework_id: str, n: int = 32) -> list[int]:
    digest = hashlib.sha256(homework_id.encode("utf-8")).digest()
    bits: list[int] = []
    for byte in digest:
        for b in range(7, -1, -1):
            bits.append((byte >> b) & 1)
            if len(bits) >= n:
                return bits
    return bits[:n]


def encode_student_no(student_no: str) -> list[int]:
    s = (student_no or "").upper()[:8].ljust(8, " ")
    bits: list[int] = []
    for ch in s:
        if ch == " ":
            idx = 63
        else:
            idx = CHARSET.find(ch)
            if idx < 0:
                idx = 62
        for b in range(5, -1, -1):
            bits.append((idx >> b) & 1)
    return bits


def decode_student_bits(bits: list[int]) -> str | None:
    if len(bits) < 48:
        return None
    chars: list[str] = []
    for i in range(0, 48, 6):
        idx = 0
        for b in bits[i : i + 6]:
            idx = (idx << 1) | int(b)
        if idx == 63:
            chars.append(" ")
        elif 0 <= idx < len(CHARSET):
            chars.append(CHARSET[idx])
        else:
            return None
    text = "".join(chars).strip()
    return text or None


def _draw_bits(draw: ImageDraw.ImageDraw, x: int, y: int, cell: int, h: int, bits: list[int], markers: bool = True) -> dict[str, Any]:
    ox = x
    if markers:
        draw.rectangle([ox, y, ox + cell - 1, y + h], fill=(0, 0, 0))
        ox += cell
    for bit in bits:
        fill = (0, 0, 0) if bit else (255, 255, 255)
        draw.rectangle([ox, y, ox + cell - 1, y + h], outline=(0, 0, 0), width=1, fill=fill)
        ox += cell
    if markers:
        draw.rectangle([ox, y, ox + cell - 1, y + h], fill=(0, 0, 0))
        ox += cell
    return {"x": x, "y": y, "cell": cell, "h": h, "n": len(bits), "markers": markers, "end_x": ox}


def encode_card_tag(homework_id: str, student_no: str | None) -> list[int]:
    return hw_bits(homework_id, 16) + encode_student_no(student_no or "")


def card_tag_code(homework_id: str, student_no: str | None) -> str:
    if student_no:
        return f"{homework_id[:8]}-{str(student_no).upper()[:8]}"
    return f"{homework_id[:8]}-BLANK"


def _id_grid_spec(origin_x: int, origin_y: int) -> dict[str, Any]:
    gap_x = 8
    char_w = ID_COLS * ID_CELL + gap_x
    r = 8
    slots: list[dict[str, Any]] = []
    for ci in range(ID_CHARS):
        slot: dict[str, Any] = {}
        ox = origin_x + ci * char_w
        for idx, ch in enumerate(CHARSET):
            rr, cc = divmod(idx, ID_COLS)
            cx = ox + cc * ID_CELL + ID_CELL // 2
            cy = origin_y + rr * ID_CELL + ID_CELL // 2
            slot[ch] = {"cx": cx, "cy": cy, "r": r}
        slots.append(slot)
    return {
        "x": origin_x,
        "y": origin_y,
        "n_chars": ID_CHARS,
        "cell": ID_CELL,
        "cols_per_char": ID_COLS,
        "char_w": char_w,
        "h": ID_ROWS * ID_CELL,
        "w": ID_CHARS * char_w,
        "charset": CHARSET,
        "slots": slots,
    }


def page_bits(page: int, n: int = 8) -> list[int]:
    return [(page >> (n - 1 - i)) & 1 for i in range(n)]


def _split_kinds(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def _num(it: dict[str, Any]) -> int:
        try:
            return int(it.get("number") or 0)
        except (TypeError, ValueError):
            return 0

    obj = [it for it in items if it.get("kind") == "objective"]
    subj = [it for it in items if it.get("kind") != "objective"]
    obj.sort(key=_num)
    subj.sort(key=_num)
    return obj, subj


def _place_objectives(
    group: list[dict[str, Any]],
    y: int,
    page: int,
    inner_w: int,
) -> tuple[int, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    cols = 2 if len(group) > 4 else 1
    col_w = inner_w // cols
    y += 4
    headers = []
    for c in range(cols):
        headers.append({"x": MARGIN + c * col_w + 100, "y": y, "pitch": 48, "page": page})
    y += OBJ_HEAD_H
    rows = (len(group) + cols - 1) // cols
    bubbles: dict[str, Any] = {}
    q_labels: dict[str, Any] = {}
    for idx, it in enumerate(group):
        col = idx // rows if cols > 1 else 0
        row = idx % rows if cols > 1 else idx
        x0 = MARGIN + col * col_w
        cy = y + row * OBJ_ROW_H + OBJ_ROW_H // 2
        q_labels[it["item_id"]] = {"x": x0, "y": cy - 10, "text": f"{it['number']}.", "page": page}
        bx = x0 + 100
        bubbles[it["item_id"]] = {
            letter: {"cx": bx + i * 48, "cy": cy, "r": BUBBLE_R, "page": page} for i, letter in enumerate(LETTERS)
        }
    y += rows * OBJ_ROW_H + 8
    return y, bubbles, q_labels, headers


def _geometry_for_items(homework_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    id_grid = _id_grid_spec(MARGIN, 200)
    tag_size = (TAG_N + 2) * TAG_CELL
    content_y = id_grid["y"] + id_grid["h"] + 16
    geom: dict[str, Any] = {
        "width": PAGE_W,
        "height": PAGE_H,
        "homework_id": homework_id,
        "bubbles": {},
        "subjective": {},
        "q_labels": {},
        "option_headers": [],
        "hw_barcode": {"x": MARGIN, "y": 68, "cell": 14, "h": 20, "n": 32, "markers": True},
        "student_barcode": {"x": MARGIN, "y": 100, "cell": 12, "h": 16, "n": 48, "markers": True},
        "student_text": {"x": MARGIN, "y": 122, "w": 720, "h": 24},
        "id_grid": id_grid,
        "card_tag": {
            "x": PAGE_W - MARGIN - tag_size,
            "y": 24,
            "cell": TAG_CELL,
            "n": TAG_N,
            "w": tag_size,
            "h": tag_size,
        },
        "fiducials": [
            {"x": 8, "y": 8, "s": 18},
            {"x": PAGE_W - 26, "y": 8, "s": 18},
            {"x": 8, "y": PAGE_H - 26, "s": 18},
            {"x": PAGE_W - 26, "y": PAGE_H - 26, "s": 18},
        ],
        "content_y": content_y,
        "page_barcode": {"x": PAGE_W - 280, "y": 68, "cell": 10, "h": 16, "n": 8, "markers": True},
        "section_headers": [],
    }
    obj, subj = _split_kinds(items)
    inner_w = PAGE_W - 2 * MARGIN
    bubbles: dict[str, Any] = {}
    subjective: dict[str, Any] = {}
    q_labels: dict[str, Any] = {}
    option_headers: list[dict[str, Any]] = []
    section_headers: list[dict[str, Any]] = []
    remaining_obj = list(obj)
    remaining_subj = list(subj)
    page = 0
    y = content_y
    need_obj_title = bool(remaining_obj)
    need_subj_title = bool(remaining_subj)

    def _start_y(p: int) -> int:
        return content_y if p == 0 else PAGE_CONT_Y

    while remaining_obj or remaining_subj:
        if remaining_obj:
            if need_obj_title:
                if y + 26 + OBJ_HEAD_H + OBJ_ROW_H > FOOTER_Y:
                    page += 1
                    y = _start_y(page)
                    continue
                section_headers.append({"page": page, "x": MARGIN, "y": y, "text": "一、选择题"})
                y += 26
                need_obj_title = False
            cols = 2 if len(obj) > 4 else 1
            avail = FOOTER_Y - y - 4 - OBJ_HEAD_H
            n_rows_fit = max(0, avail // OBJ_ROW_H)
            cap = n_rows_fit * cols
            if cap <= 0:
                page += 1
                y = _start_y(page)
                need_obj_title = True
                continue
            take = remaining_obj[:cap]
            remaining_obj = remaining_obj[cap:]
            y, more_b, more_l, more_h = _place_objectives(take, y, page, inner_w)
            bubbles.update(more_b)
            q_labels.update(more_l)
            option_headers.extend(more_h)
            continue
        if need_subj_title:
            if y + 26 + SUBJ_MIN_H + 30 > FOOTER_Y:
                page += 1
                y = _start_y(page)
                continue
            section_headers.append({"page": page, "x": MARGIN, "y": y, "text": "二、解答题"})
            y += 26
            need_subj_title = False
        unit = 22 + SUBJ_PREF_H + 8
        n_fit = max(0, (FOOTER_Y - y) // unit)
        box_h = SUBJ_PREF_H
        if n_fit <= 0:
            unit_min = 22 + SUBJ_MIN_H + 8
            n_fit = max(0, (FOOTER_Y - y) // unit_min)
            box_h = SUBJ_MIN_H
        if n_fit <= 0:
            page += 1
            y = _start_y(page)
            need_subj_title = True
            continue
        it = remaining_subj.pop(0)
        q_labels[it["item_id"]] = {
            "x": MARGIN,
            "y": y,
            "text": f"{it['number']}. 主观题作答区",
            "page": page,
        }
        subjective[it["item_id"]] = {"x": MARGIN, "y": y + 22, "w": inner_w, "h": box_h, "page": page}
        y += 22 + box_h + 8

    geom["bubbles"] = bubbles
    geom["subjective"] = subjective
    geom["q_labels"] = q_labels
    geom["option_headers"] = option_headers
    geom["section_headers"] = section_headers
    geom["n_pages"] = page + 1
    missing = [it["item_id"] for it in items if it["item_id"] not in bubbles and it["item_id"] not in subjective]
    if missing:
        raise ValueError(f"答题卡未排入题目: {missing}")
    return geom


def _paint_card_tag(draw: ImageDraw.ImageDraw, spec: dict[str, Any], bits: list[int]) -> None:
    x, y, cell, n = spec["x"], spec["y"], spec["cell"], spec["n"]
    outer = (n + 2) * cell
    draw.rectangle([x, y, x + outer - 1, y + outer - 1], outline=(0, 0, 0), width=2, fill=(255, 255, 255))
    for i in range(n + 2):
        for j in range(n + 2):
            if i in {0, n + 1} or j in {0, n + 1}:
                draw.rectangle(
                    [x + j * cell, y + i * cell, x + (j + 1) * cell - 1, y + (i + 1) * cell - 1],
                    fill=(0, 0, 0),
                )
    padded = list(bits[: n * n]) + [0] * max(0, n * n - len(bits))
    for idx, bit in enumerate(padded):
        rr, cc = divmod(idx, n)
        if bit:
            draw.rectangle(
                [
                    x + (cc + 1) * cell,
                    y + (rr + 1) * cell,
                    x + (cc + 2) * cell - 1,
                    y + (rr + 2) * cell - 1,
                ],
                fill=(0, 0, 0),
            )


def _paint_id_grid(
    draw: ImageDraw.ImageDraw,
    geom: dict[str, Any],
    student_no: str | None,
    tiny: ImageFont.ImageFont,
) -> None:
    grid = geom["id_grid"]
    filled = (student_no or "").upper()[:ID_CHARS].ljust(ID_CHARS, " ")
    draw.text((grid["x"], grid["y"] - 38), "学号填涂（每位一格，把对应字符涂黑）", fill=0, font=tiny)
    for ci, slot in enumerate(grid["slots"]):
        draw.text((grid["x"] + ci * grid["char_w"] + 18, grid["y"] - 20), str(ci + 1), fill=(80, 80, 80), font=tiny)
        want = filled[ci]
        for ch, spec in slot.items():
            cx, cy, r = spec["cx"], spec["cy"], spec["r"]
            on = want == ch and want != " "
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                outline=(0, 0, 0),
                width=1,
                fill=(0, 0, 0) if on else (255, 255, 255),
            )
            if not on:
                draw.text((cx - 5, cy - 7), ch, fill=(70, 70, 70), font=tiny)


def _paint_page(
    homework_id: str,
    items: list[dict[str, Any]],
    geom: dict[str, Any],
    student: dict[str, Any] | None,
    page: int,
) -> Image.Image:
    img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    title_font = _font(28)
    body = _font(20)
    small = _font(16)
    tiny = _font(11)
    student_no = (student or {}).get("student_no")
    name = (student or {}).get("name")
    n_pages = int(geom.get("n_pages") or 1)
    for mark in geom.get("fiducials") or []:
        s = mark["s"]
        draw.rectangle([mark["x"], mark["y"], mark["x"] + s, mark["y"] + s], fill=(0, 0, 0))
    draw.text((MARGIN, 18), "作业答题卡", fill=0, font=title_font)
    draw.text((MARGIN + 210, 26), f"作业 {homework_id[:12]}", fill=0, font=small)
    draw.text((MARGIN + 210, 46), f"第 {page + 1}/{n_pages} 页", fill=(80, 80, 80), font=tiny)
    tag_code = card_tag_code(homework_id, student_no)
    draw.text((geom["card_tag"]["x"] - 210, 28), f"卡号 {tag_code}", fill=0, font=small)
    draw.text((geom["card_tag"]["x"] - 210, 48), "本卡独立标签", fill=(80, 80, 80), font=tiny)
    _paint_card_tag(draw, geom["card_tag"], encode_card_tag(homework_id, student_no))
    hb = geom["hw_barcode"]
    draw.text((hb["x"], hb["y"] - 16), "作业条码", fill=(80, 80, 80), font=tiny)
    _draw_bits(draw, hb["x"], hb["y"], hb["cell"], hb["h"], hw_bits(homework_id), True)
    pb = geom.get("page_barcode") or {}
    if pb:
        _draw_bits(draw, pb["x"], pb["y"], pb["cell"], pb["h"], page_bits(page, int(pb.get("n") or 8)), True)
    st = geom["student_text"]
    if student_no:
        label = f"学号 {student_no}" + (f"    姓名 {name}" if name else "")
    else:
        label = "学号 ________    姓名 ________    （空白卡请自行填涂学号）"
    draw.text((st["x"], st["y"]), label, fill=0, font=body)
    sb = geom["student_barcode"]
    if student_no:
        _draw_bits(draw, sb["x"], sb["y"], sb["cell"], sb["h"], encode_student_no(student_no), True)
    if page == 0:
        _paint_id_grid(draw, geom, student_no, tiny)
    for hdr in geom.get("section_headers") or []:
        if hdr.get("page", 0) != page:
            continue
        draw.text((hdr["x"], hdr["y"]), hdr.get("text") or "", fill=0, font=body)
    for hdr in geom.get("option_headers") or []:
        if hdr.get("page", 0) != page:
            continue
        for i, letter in enumerate(LETTERS):
            cx = hdr["x"] + i * hdr["pitch"]
            try:
                draw.text((cx, hdr["y"]), letter, fill=0, font=small, anchor="mt")
            except TypeError:
                draw.text((cx - 6, hdr["y"]), letter, fill=0, font=small)
    for it in items:
        lab = (geom.get("q_labels") or {}).get(it["item_id"]) or {}
        if lab.get("page", 0) != page:
            continue
        if lab:
            draw.text((lab["x"], lab["y"]), lab.get("text") or "", fill=0, font=body)
        if it["kind"] == "objective":
            for letter, spec in geom["bubbles"][it["item_id"]].items():
                cx, cy, r = spec["cx"], spec["cy"], spec["r"]
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0), width=2, fill=(255, 255, 255))
        else:
            box = geom["subjective"][it["item_id"]]
            draw.rectangle(
                [box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]],
                outline=(0, 0, 0),
                width=2,
            )
    draw.text((MARGIN, PAGE_H - 40), "本地生成 · 禁止外部 API", fill=(80, 80, 80), font=small)
    return img


def render_cards(
    homework_id: str,
    items: list[dict[str, Any]],
    students: list[dict[str, Any]],
) -> dict[str, Any]:
    if not students:
        raise ValueError("禁止生成无名卡：名单为空")
    geom = _geometry_for_items(homework_id, items)
    n_pages = int(geom.get("n_pages") or 1)
    out_dir = homework_dir(homework_id, "cards")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink(missing_ok=True)
    blank_paths: list[str] = []
    for pi in range(n_pages):
        img = _paint_page(homework_id, items, geom, student=None, page=pi)
        if n_pages <= 1:
            bp = out_dir / "_blank.png"
        else:
            bp = out_dir / f"_blank_p{pi + 1}.png"
        img.save(bp)
        blank_paths.append(relpath(bp))
    paths: list[str] = []
    student_cards: dict[str, list[str]] = {}
    for stu in students:
        page_files: list[str] = []
        for pi in range(n_pages):
            img = _paint_page(homework_id, items, geom, student=stu, page=pi)
            name = f"{stu['student_no']}.png" if n_pages <= 1 else f"{stu['student_no']}_p{pi + 1}.png"
            p = out_dir / name
            img.save(p)
            page_files.append(relpath(p))
        student_cards[str(stu["student_no"])] = page_files
        paths.append(page_files[0])
    geom["blank_path"] = blank_paths[0]
    geom["blank_paths"] = blank_paths
    geom["card_paths"] = paths
    geom["student_cards"] = student_cards
    return {
        "homework_id": homework_id,
        "geometry": geom,
        "print_path": relpath(out_dir),
        "count": len(students),
        "n_pages": n_pages,
        "paths": paths,
        "blank_path": blank_paths[0],
        "student_cards": student_cards,
    }


def _item_page(geometry: dict[str, Any], item_id: str) -> int:
    bub = (geometry.get("bubbles") or {}).get(item_id)
    if bub:
        first = next(iter(bub.values()))
        return int(first.get("page") or 0)
    box = (geometry.get("subjective") or {}).get(item_id)
    if box:
        return int(box.get("page") or 0)
    return 0


def fill_bubble(image_path: str | Path, geometry: dict[str, Any], item_id: str, letter: str) -> None:
    path = Path(image_path)
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    spec = geometry["bubbles"][item_id][letter]
    cx, cy, r = spec["cx"], spec["cy"], spec["r"]
    rr = max(3, r - 4)
    draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(0, 0, 0))
    img.save(path)


def write_subjective(image_path: str | Path, geometry: dict[str, Any], item_id: str, lines: list[str]) -> None:
    path = Path(image_path)
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    box = geometry["subjective"][item_id]
    font = _font(20)

    def _w(s: str) -> float:
        if hasattr(font, "getlength"):
            return float(font.getlength(s))
        box = font.getbbox(s)
        return float(box[2] - box[0])

    max_w = box["w"] - 28
    max_y = box["y"] + box["h"] - 10
    y = box["y"] + 10
    x = box["x"] + 12
    for raw in lines:
        text = str(raw).replace("\n", " ")
        while text and y + 24 <= max_y:
            chunk = text
            while _w(chunk) > max_w and len(chunk) > 1:
                chunk = chunk[:-1]
            draw.text((x, y), chunk, fill=(20, 30, 90), font=font)
            y += 26
            text = text[len(chunk) :].lstrip()
        if y + 24 > max_y:
            break
    img.save(path)


def _answer_letter(item: dict[str, Any]) -> str:
    ak = item.get("answer_key")
    if isinstance(ak, dict):
        letter = ak.get("letter") or ""
    else:
        letter = str(ak or "")
    letter = letter.strip().upper()[:1]
    return letter if letter in LETTERS else "A"


def _default_fill_scripts(students: list[dict[str, Any]], items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    obj = [it for it in items if it.get("kind") == "objective"]
    subj = [it for it in items if it.get("kind") == "subjective"]
    wrong = {"A": "B", "B": "C", "C": "D", "D": "A"}
    scripts: dict[str, dict[str, Any]] = {}
    presets = [
        {
            "bubbles": {it["item_id"]: _answer_letter(it) for it in obj},
            "writing": {
                it["item_id"]: ["通项 a_n = 2n-1，项数 n=10", "S = n^2 = 100"] for it in subj
            },
        },
        {
            "bubbles": {it["item_id"]: wrong[_answer_letter(it)] for it in obj},
            "writing": {it["item_id"]: ["不太会", "大概是 50？"] for it in subj},
        },
        {
            "bubbles": {
                it["item_id"]: (_answer_letter(it) if i == 0 else wrong[_answer_letter(it)])
                for i, it in enumerate(obj)
            },
            "writing": {it["item_id"]: ["1+3+…+19", "和为100"] for it in subj},
        },
    ]
    for i, stu in enumerate(students):
        scripts[stu["student_no"]] = presets[i % len(presets)]
    return scripts


def make_filled_scans(
    homework_id: str,
    geometry: dict[str, Any],
    students: list[dict[str, Any]],
    items: list[dict[str, Any]],
    scripts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    import shutil

    if not scripts:
        raise ValueError("缺少学生作答脚本。必须由大模型生成，禁止用模板填卡。")
    card_paths = geometry.get("card_paths") or []
    if card_paths:
        first = Path(card_paths[0])
        if not first.is_absolute():
            from zypg.storage.files import abspath as _abs

            card_dir = _abs(card_paths[0]).parent
        else:
            card_dir = first.parent
    else:
        card_dir = homework_dir(homework_id, "cards")
    scan_dir = homework_dir(homework_id, "scans")
    n_pages = int(geometry.get("n_pages") or 1)
    student_cards = geometry.get("student_cards") or {}
    paths: list[str] = []
    for stu in students:
        no = stu["student_no"]
        srcs = student_cards.get(no)
        if not srcs:
            srcs = [relpath(card_dir / (f"{no}.png" if n_pages <= 1 else f"{no}_p{pi + 1}.png")) for pi in range(n_pages)]
        dests: list[Path] = []
        for pi, src in enumerate(srcs):
            src_path = Path(src)
            if not src_path.is_absolute():
                from zypg.storage.files import abspath as _abs

                src_path = _abs(src)
            if not src_path.exists():
                raise FileNotFoundError(f"找不到空白卡 {src_path}")
            dest = scan_dir / (f"{no}_filled.png" if n_pages <= 1 else f"{no}_filled_p{pi + 1}.png")
            shutil.copy2(src_path, dest)
            dests.append(dest)
        script = scripts.get(no) or {}
        fill_student_no_bubbles(dests[0], geometry, no)
        for item_id, letter in (script.get("bubbles") or {}).items():
            if item_id in geometry.get("bubbles", {}) and letter in geometry["bubbles"][item_id]:
                fill_bubble(dests[_item_page(geometry, item_id)], geometry, item_id, letter)
        for item_id, lines in (script.get("writing") or {}).items():
            if item_id in geometry.get("subjective", {}):
                write_subjective(dests[_item_page(geometry, item_id)], geometry, item_id, list(lines))
        paths.append(relpath(dests[0]))
    return {
        "homework_id": homework_id,
        "count": len(paths),
        "paths": paths,
        "print_path": relpath(scan_dir),
        "scripts": {k: v for k, v in scripts.items() if k in {s["student_no"] for s in students}},
    }


def fill_student_no_bubbles(image_path: str | Path, geometry: dict[str, Any], student_no: str) -> None:
    grid = geometry.get("id_grid") or {}
    slots = grid.get("slots") or []
    if not slots:
        return
    path = Path(image_path)
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    filled = (student_no or "").upper()[:ID_CHARS].ljust(ID_CHARS, " ")
    for ci, slot in enumerate(slots):
        ch = filled[ci]
        if ch == " " or ch not in slot:
            continue
        spec = slot[ch]
        cx, cy, r = spec["cx"], spec["cy"], spec["r"]
        rr = max(3, r - 1)
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(0, 0, 0))
    img.save(path)


def wipe_student_id(image_path: str | Path, geometry: dict[str, Any]) -> None:
    path = Path(image_path)
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    st = geometry.get("student_text") or {}
    if st:
        draw.rectangle(
            [st["x"], st["y"], st["x"] + st.get("w", 600), st["y"] + st.get("h", 28)],
            fill=(255, 255, 255),
        )
    sb = geometry.get("student_barcode") or {}
    if sb:
        width = (sb["n"] + 2) * sb["cell"]
        draw.rectangle(
            [sb["x"], sb["y"] - 2, sb["x"] + width, sb["y"] + sb["h"] + 2],
            fill=(255, 255, 255),
        )
    grid = geometry.get("id_grid") or {}
    if grid:
        draw.rectangle(
            [grid["x"] - 4, grid["y"] - 40, grid["x"] + grid["w"] + 4, grid["y"] + grid["h"] + 4],
            fill=(255, 255, 255),
        )
    tag = geometry.get("card_tag") or {}
    if tag:
        draw.rectangle(
            [tag["x"] - 4, tag["y"] - 4, tag["x"] + tag["w"] + 4, tag["y"] + tag["h"] + 4],
            fill=(255, 255, 255),
        )
        draw.rectangle(
            [tag["x"] - 220, tag["y"], tag["x"] - 4, tag["y"] + 40],
            fill=(255, 255, 255),
        )
    img.save(path)
