from __future__ import annotations

from zypg.mcp_tools.card_render import fill_bubble, render_cards
from zypg.mcp_tools.omr import read_bubbles
from zypg.storage.files import abspath


def test_omr_follows_pixels_not_json(tmp_path, monkeypatch):
    items = [
        {"item_id": "q1", "kind": "objective", "number": 1, "stem": "第1题"},
        {"item_id": "q2", "kind": "objective", "number": 2, "stem": "第2题"},
    ]
    students = [{"student_id": "s1", "student_no": "S01", "name": "张一"}]
    answer_key = {"q1": "A", "q2": "C"}

    out = render_cards("hw_omr_pixel_a", items, students)
    geom = out["geometry"]
    scan = abspath(out["paths"][0])
    blank = abspath(out["blank_path"])
    fill_bubble(scan, geom, "q1", "A")
    marks = read_bubbles(scan, blank, geom)
    assert marks["q1"] == "A"

    out2 = render_cards("hw_omr_pixel_c", items, students)
    geom2 = out2["geometry"]
    scan2 = abspath(out2["paths"][0])
    blank2 = abspath(out2["blank_path"])
    fill_bubble(scan2, geom2, "q1", "C")
    marks2 = read_bubbles(scan2, blank2, geom2)
    assert marks2["q1"] == "C"
    assert answer_key["q1"] == "A"
    assert geom2 == out2["geometry"]
