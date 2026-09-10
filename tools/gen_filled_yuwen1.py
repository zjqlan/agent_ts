"""Generate filled answer cards for 语文练习_1.docx without importing into a class."""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from zypg.mcp_tools.card_render import make_filled_scans, render_cards  # noqa: E402
from zypg.storage.files import abspath  # noqa: E402

HOMEWORK_ID = "yuwen_lianxi_1"
KEYS = ["A", "D", "C"]
OBJ_IDS = ["q1", "q2", "q3"]
WRONG = {"A": "B", "B": "C", "C": "D", "D": "A"}
TOTAL = 15
ROSTER = ROOT / "samples" / "class_roster_30.csv"
OUT_DIR = Path(r"C:\Users\Administrator\Downloads") / "语文练习_1_已作答答题卡"


def items() -> list[dict]:
    return [
        {
            "item_id": "q1",
            "number": 1,
            "kind": "objective",
            "stem": "加点词语解释完全正确的一项",
            "score": 3,
            "options": ["A", "B", "C", "D"],
            "answer_key": {"letter": "A"},
        },
        {
            "item_id": "q2",
            "number": 2,
            "kind": "objective",
            "stem": "加点虚词意义和用法完全相同的一组",
            "score": 3,
            "options": ["A", "B", "C", "D"],
            "answer_key": {"letter": "D"},
        },
        {
            "item_id": "q3",
            "number": 3,
            "kind": "objective",
            "stem": "对《劝学》比喻论证分析不恰当的一项",
            "score": 3,
            "options": ["A", "B", "C", "D"],
            "answer_key": {"letter": "C"},
        },
        {
            "item_id": "q4",
            "number": 4,
            "kind": "subjective",
            "stem": "说明荀子‘学不可以已’的三层逻辑依据",
            "score": 6,
            "answer_key": {
                "text": "改变本性；借助外物与积累；专一恒久"
            },
            "rubric": ["改变本性", "借助外物/积累", "专一恒久"],
        },
    ]


def load_students() -> list[dict]:
    rows = []
    with ROSTER.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({"student_no": row["student_no"].strip(), "name": row["name"].strip()})
    if not rows:
        raise SystemExit("名单为空")
    return rows


def bubbles(correct_mask: list[bool | None]) -> dict[str, str]:
    out = {}
    for i, flag in enumerate(correct_mask):
        if flag is None:
            continue
        key = KEYS[i]
        out[OBJ_IDS[i]] = key if flag else WRONG[key]
    return out


def mask(wrong_idx: list[int], skip: list[int] | None = None) -> list[bool | None]:
    skip = skip or []
    m: list[bool | None] = [True] * 3
    for i in wrong_idx:
        m[i] = False
    for i in skip:
        m[i] = None
    return m


def w_full() -> list[str]:
    return [
        "第一层：学习能改变本性（木受绳则直，金就砺则利）；",
        "第二层：学习贵在借助外物与坚持积累（假舆马、积土成山）；",
        "第三层：学习须专一恒久（锲而不舍、用心一也）。",
    ]


def w_ok() -> list[str]:
    return ["学能改变本性，还要善假于物、不断积累，并且持之以恒、用心专一。"]


def w_two() -> list[str]:
    return ["学习可以改变人，还要靠积累。锲而不舍那一层我没写全。"]


def w_one() -> list[str]:
    return ["学不可以已是因为学习能让人变聪明、变有学问。"]


def w_wrong() -> list[str]:
    return ["荀子认为人要听从老师，不要自己思考，所以学不可以已。"]


def w_blank() -> list[str]:
    return []


def w_idk() -> list[str]:
    return ["不会"]


def profiles() -> list[tuple[str, dict, dict]]:
    n, f = [True] * 3, [False] * 3
    return [
        ("满分", {"bubbles": bubbles(n), "writing": {"q4": w_full()}}, {"obj": 9, "q4": 6}),
        ("满分", {"bubbles": bubbles(n), "writing": {"q4": w_ok()}}, {"obj": 9, "q4": 6}),
        ("近满分", {"bubbles": bubbles(mask([2])), "writing": {"q4": w_full()}}, {"obj": 6, "q4": 6}),
        ("近满分", {"bubbles": bubbles(n), "writing": {"q4": w_two()}}, {"obj": 9, "q4": 4}),
        ("优秀", {"bubbles": bubbles(mask([1])), "writing": {"q4": w_ok()}}, {"obj": 6, "q4": 6}),
        ("优秀", {"bubbles": bubbles(mask([0])), "writing": {"q4": w_full()}}, {"obj": 6, "q4": 6}),
        ("中上", {"bubbles": bubbles(mask([0, 2])), "writing": {"q4": w_ok()}}, {"obj": 3, "q4": 6}),
        ("中上", {"bubbles": bubbles(mask([1])), "writing": {"q4": w_two()}}, {"obj": 6, "q4": 4}),
        ("中等", {"bubbles": bubbles(mask([0, 1])), "writing": {"q4": w_ok()}}, {"obj": 3, "q4": 6}),
        ("中等", {"bubbles": bubbles(mask([2])), "writing": {"q4": w_two()}}, {"obj": 6, "q4": 4}),
        ("中等", {"bubbles": bubbles(n), "writing": {"q4": w_one()}}, {"obj": 9, "q4": 2}),
        ("中等", {"bubbles": bubbles(mask([0])), "writing": {"q4": w_two()}}, {"obj": 6, "q4": 4}),
        ("中下", {"bubbles": bubbles(mask([0, 1])), "writing": {"q4": w_one()}}, {"obj": 3, "q4": 2}),
        ("中下", {"bubbles": bubbles(mask([1, 2])), "writing": {"q4": w_two()}}, {"obj": 3, "q4": 4}),
        ("中下", {"bubbles": bubbles(mask([0, 2])), "writing": {"q4": w_one()}}, {"obj": 3, "q4": 2}),
        ("中等", {"bubbles": bubbles(mask([1])), "writing": {"q4": w_one()}}, {"obj": 6, "q4": 2}),
        ("中上", {"bubbles": bubbles(mask([2])), "writing": {"q4": w_ok()}}, {"obj": 6, "q4": 6}),
        ("优秀", {"bubbles": bubbles(n), "writing": {"q4": w_two()}}, {"obj": 9, "q4": 4}),
        ("低分", {"bubbles": bubbles(mask([0, 1])), "writing": {"q4": w_wrong()}}, {"obj": 3, "q4": 1}),
        ("低分", {"bubbles": bubbles(mask([0, 2])), "writing": {"q4": w_idk()}}, {"obj": 3, "q4": 0}),
        ("中下", {"bubbles": bubbles(mask([1, 2])), "writing": {"q4": w_ok()}}, {"obj": 3, "q4": 6}),
        ("只做客观", {"bubbles": bubbles(n), "writing": {"q4": w_blank()}}, {"obj": 9, "q4": 0}),
        ("乱填", {"bubbles": bubbles(f), "writing": {"q4": ["学习很重要，要天天学。"]}}, {"obj": 0, "q4": 1}),
        ("只会简答", {"bubbles": bubbles(f), "writing": {"q4": w_full()}}, {"obj": 0, "q4": 6}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2])), "writing": {"q4": w_idk()}}, {"obj": 0, "q4": 0}),
        ("几乎空白", {"bubbles": bubbles([None, None, False]), "writing": {"q4": w_idk()}}, {"obj": 0, "q4": 0}),
        ("很低", {"bubbles": bubbles(mask([0, 2])), "writing": {"q4": w_wrong()}}, {"obj": 3, "q4": 1}),
        ("两极", {"bubbles": bubbles(mask([0, 1])), "writing": {"q4": w_full()}}, {"obj": 3, "q4": 6}),
        ("漏涂一题", {"bubbles": bubbles(mask([], skip=[1])), "writing": {"q4": w_ok()}}, {"obj": 6, "q4": 6}),
        ("客观全错主观会", {"bubbles": bubbles(f), "writing": {"q4": w_ok()}}, {"obj": 0, "q4": 6}),
    ]


def main() -> None:
    students = load_students()
    paper = items()
    rendered = render_cards(HOMEWORK_ID, paper, students)
    profs = profiles()
    if len(profs) < len(students):
        raise SystemExit("档位不足")
    scripts = {}
    summary = []
    for stu, (band, script, exp) in zip(students, profs):
        scripts[stu["student_no"]] = script
        total = exp["obj"] + exp["q4"]
        summary.append(
            {
                "student_no": stu["student_no"],
                "name": stu["name"],
                "band": band,
                "objective": exp["obj"],
                "q4": exp["q4"],
                "total": total,
                "percent": round(100 * total / TOTAL, 1),
                "obj_marked": len(script["bubbles"]),
            }
        )
    filled = make_filled_scans(HOMEWORK_ID, rendered["geometry"], students, paper, scripts=scripts)
    scan_dir = abspath(filled["print_path"])
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    for p in scan_dir.glob("*_filled*.png"):
        shutil.copy2(p, OUT_DIR / p.name)
    score_path = OUT_DIR / "scores.csv"
    with score_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["student_no", "name", "band", "objective", "q4", "total", "percent", "obj_marked"],
        )
        w.writeheader()
        w.writerows(summary)
    shutil.copy2(ROSTER, OUT_DIR / "roster.csv")
    (OUT_DIR / "scripts.json").write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = OUT_DIR.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(OUT_DIR), "zip", OUT_DIR)
    print("not imported to class")
    print("count", filled["count"], "pages", rendered.get("n_pages"))
    print("dir", OUT_DIR)
    print("zip", zip_path)
    for row in summary:
        print(f"{row['student_no']} {row['name']} {row['band']} {row['total']}/{TOTAL}")


if __name__ == "__main__":
    main()
