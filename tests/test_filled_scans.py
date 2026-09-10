from zypg.mcp_tools.card_render import _default_fill_scripts, make_filled_scans, render_cards
from zypg.mcp_tools.omr import read_bubbles
from zypg.storage.files import abspath


def test_three_filled_student_cards_leave_blanks_untouched():
    items = [
        {"item_id": "q1", "kind": "objective", "number": 1, "answer_key": {"letter": "A"}},
        {"item_id": "q2", "kind": "objective", "number": 2, "answer_key": {"letter": "C"}},
        {"item_id": "q3", "kind": "subjective", "number": 3},
    ]
    students = [
        {"student_id": "s1", "student_no": "S01", "name": "张一"},
        {"student_id": "s2", "student_no": "S02", "name": "李二"},
        {"student_id": "s3", "student_no": "S03", "name": "王三"},
    ]
    out = render_cards("hw_filled_demo", items, students)
    scripts = _default_fill_scripts(students, items)
    filled = make_filled_scans("hw_filled_demo", out["geometry"], students, items, scripts=scripts)
    assert filled["count"] == 3
    geom = out["geometry"]
    blank = abspath(out["blank_path"])
    s01 = read_bubbles(abspath(filled["paths"][0]), blank, geom)
    s02 = read_bubbles(abspath(filled["paths"][1]), blank, geom)
    assert s01["q1"] == "A" and s01["q2"] == "C"
    assert s02["q1"] == "B" and s02["q2"] == "D"
    print_s01 = read_bubbles(abspath(out["paths"][0]), blank, geom)
    assert print_s01.get("q1") != "A"
