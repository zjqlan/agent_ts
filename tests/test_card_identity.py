from __future__ import annotations

from zypg.mcp_tools.card_render import render_cards, wipe_student_id
from zypg.mcp_tools.omr import decode_homework, decode_student_no
from zypg.storage.files import abspath


def test_cards_have_id_grid_and_unique_tag():
    items = [
        {"item_id": "q1", "kind": "objective", "number": 1, "answer_key": {"letter": "A"}},
        {"item_id": "q2", "kind": "subjective", "number": 2},
    ]
    students = [
        {"student_id": "s1", "student_no": "S01", "name": "张一"},
        {"student_id": "s2", "student_no": "S02", "name": "李二"},
    ]
    out = render_cards("hw_id_tag_demo", items, students)
    geom = out["geometry"]
    assert "id_grid" in geom and len(geom["id_grid"]["slots"]) == 8
    assert "card_tag" in geom
    blank = abspath(out["blank_path"])
    s01 = abspath(out["paths"][0])
    s02 = abspath(out["paths"][1])
    assert decode_homework(s01, geom)
    assert decode_homework(blank, geom)
    assert decode_student_no(s01, geom, blank) == "S01"
    assert decode_student_no(s02, geom, blank) == "S02"
    assert decode_student_no(blank, geom, blank) is None
    wipe_student_id(s02, geom)
    assert decode_student_no(s02, geom, blank) is None


def test_card_layout_fits_page():
    items = [
        {"item_id": f"q{i}", "kind": "subjective" if i in {1, 12, 13, 14} else "objective", "number": i}
        for i in range(1, 15)
    ]
    students = [{"student_id": "s1", "student_no": "S01", "name": "张一"}]
    out = render_cards("hw_layout_fit", items, students)
    geom = out["geometry"]
    for box in geom["subjective"].values():
        assert box["y"] + box["h"] <= 1754 - 40
    assert set(geom["subjective"]) == {"q1", "q12", "q13", "q14"}
    assert len(geom["bubbles"]) == 10
    left_cx = geom["bubbles"]["q2"]["A"]["cx"]
    right_cx = geom["bubbles"]["q7"]["A"]["cx"]
    assert left_cx < right_cx
    assert geom["bubbles"]["q3"]["A"]["cy"] > geom["bubbles"]["q2"]["A"]["cy"]
    obj_y = geom["bubbles"]["q2"]["A"]["cy"]
    sub_y = min(box["y"] for box in geom["subjective"].values() if box.get("page", 0) == 0) if any(
        box.get("page", 0) == 0 for box in geom["subjective"].values()
    ) else 10**9
    if sub_y < 10**9:
        assert obj_y < sub_y
    assert geom["bubbles"]["q2"]["A"].get("page", 0) <= min(b.get("page", 0) for b in geom["subjective"].values())
    assert geom.get("n_pages", 1) >= 1
    if geom["n_pages"] > 1:
        assert len(out["student_cards"]["S01"]) == geom["n_pages"]
    assert geom["option_headers"]
