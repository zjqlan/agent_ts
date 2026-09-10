"""Import 语文练习.md and generate 30 filled answer cards."""
from __future__ import annotations

import csv
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from zypg.agents.homework import _persist  # noqa: E402
from zypg.mcp_tools.card_render import make_filled_scans, render_cards  # noqa: E402
from zypg.mcp_tools.edupaper import parse_paper_file  # noqa: E402
from zypg.storage import mysql  # noqa: E402
from zypg.storage.files import abspath, homework_dir, relpath  # noqa: E402

SRC = Path(r"C:\Users\Administrator\Downloads\语文练习.md")
KEYS = ["A", "B", "C", "D", "B", "A"]
OBJ_IDS = [f"q{i}" for i in range(1, 7)]
WRONG = {"A": "B", "B": "C", "C": "D", "D": "A"}
TOTAL = 36
RUBRICS = {
    7: ["点出主客问答与客之悲", "点出水月之喻或变与不变", "落到精神超越/旷达"],
    8: ["点出比喻/类比论证", "结合积土成山等具体内容", "说明积累成德的表达效果"],
    9: ["默写出东船西舫悄无言，唯见江心秋月白", "说明侧面烘托或余韵留白"],
}


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
    m: list[bool | None] = [True] * 6
    for i in wrong_idx:
        m[i] = False
    for i in skip:
        m[i] = None
    return m


def w7_full() -> list[str]:
    return [
        "苏轼借客之悲慨（哀吾生之须臾、羡长江之无穷），引出主之超然。",
        "用水月之喻讲变与不变，把个体生命放到宇宙时空里审视，实现精神超越。",
    ]


def w7_ok() -> list[str]:
    return ["客悲人生短暂，主用水月说明变与不变，表达旷达胸襟。"]


def w7_half() -> list[str]:
    return ["苏轼写了主客问答，表达了对人生的思考。"]


def w7_wrong() -> list[str]:
    return ["苏轼在写赤壁打仗，客劝他要积极进取建功立业。"]


def w8_full() -> list[str]:
    return [
        "运用比喻论证（类比）。以积土成山、积水成渊类比积善成德，把抽象道理写具体。",
        "连用排比式比喻，增强语势，突出积累的重要性。",
    ]


def w8_ok() -> list[str]:
    return ["比喻论证，用自然现象说明积累才能成德。"]


def w8_half() -> list[str]:
    return ["用了排比，强调要学习。"]


def w8_wrong() -> list[str]:
    return ["举例论证，举了君子的例子来证明学习。"]


def w9_full() -> list[str]:
    return [
        "东船西舫悄无言，唯见江心秋月白。",
        "以环境寂静、月照江心收束，侧面烘托乐曲震撼，营造余韵，强化此时无声胜有声。",
    ]


def w9_ok() -> list[str]:
    return ["东船西舫悄无言，唯见江心秋月白。烘托余音绕梁。"]


def w9_half() -> list[str]:
    return ["东船西舫悄无言。环境很安静。"]


def w9_wrong() -> list[str]:
    return ["大弦嘈嘈如急雨，小弦切切如私语。写琵琶声音很大。"]


def w_blank() -> list[str]:
    return []


def w_idk() -> list[str]:
    return ["不会"]


def writing(a, b, c) -> dict:
    return {"q7": a, "q8": b, "q9": c}


def profiles() -> list[tuple[str, dict, dict]]:
    n = [True] * 6
    f = [False] * 6
    return [
        ("满分", {"bubbles": bubbles(n), "writing": writing(w7_full(), w8_full(), w9_full())}, {"obj": 18, "q7": 6, "q8": 6, "q9": 6}),
        ("满分", {"bubbles": bubbles(n), "writing": writing(w7_ok(), w8_ok(), w9_ok())}, {"obj": 18, "q7": 6, "q8": 6, "q9": 6}),
        ("近满分", {"bubbles": bubbles(mask([3])), "writing": writing(w7_full(), w8_full(), w9_full())}, {"obj": 15, "q7": 6, "q8": 6, "q9": 6}),
        ("近满分", {"bubbles": bubbles(n), "writing": writing(w7_half(), w8_full(), w9_full())}, {"obj": 18, "q7": 3, "q8": 6, "q9": 6}),
        ("优秀", {"bubbles": bubbles(mask([1])), "writing": writing(w7_ok(), w8_ok(), w9_ok())}, {"obj": 15, "q7": 6, "q8": 6, "q9": 5}),
        ("优秀", {"bubbles": bubbles(mask([0, 4])), "writing": writing(w7_full(), w8_full(), w9_ok())}, {"obj": 12, "q7": 6, "q8": 6, "q9": 6}),
        ("中上", {"bubbles": bubbles(mask([2, 5])), "writing": writing(w7_ok(), w8_half(), w9_ok())}, {"obj": 12, "q7": 6, "q8": 3, "q9": 6}),
        ("中上", {"bubbles": bubbles(mask([1, 3])), "writing": writing(w7_ok(), w8_ok(), w9_half())}, {"obj": 12, "q7": 6, "q8": 6, "q9": 3}),
        ("中等", {"bubbles": bubbles(mask([0, 2, 4])), "writing": writing(w7_half(), w8_half(), w9_ok())}, {"obj": 9, "q7": 3, "q8": 3, "q9": 6}),
        ("中等", {"bubbles": bubbles(mask([1, 3, 5])), "writing": writing(w7_ok(), w8_half(), w9_half())}, {"obj": 9, "q7": 6, "q8": 3, "q9": 3}),
        ("中等", {"bubbles": bubbles(mask([4])), "writing": writing(w7_half(), w8_ok(), w9_wrong())}, {"obj": 15, "q7": 3, "q8": 6, "q9": 1}),
        ("中等", {"bubbles": bubbles(mask([0, 5])), "writing": writing(w7_ok(), w8_wrong(), w9_ok())}, {"obj": 12, "q7": 6, "q8": 1, "q9": 6}),
        ("中下", {"bubbles": bubbles(mask([0, 1, 3])), "writing": writing(w7_ok(), w8_wrong(), w9_half())}, {"obj": 9, "q7": 6, "q8": 1, "q9": 3}),
        ("中下", {"bubbles": bubbles(mask([1, 2, 4, 5])), "writing": writing(w7_half(), w8_half(), w9_wrong())}, {"obj": 6, "q7": 3, "q8": 3, "q9": 1}),
        ("中下", {"bubbles": bubbles(mask([0, 2, 3, 5])), "writing": writing(w7_wrong(), w8_ok(), w9_ok())}, {"obj": 6, "q7": 1, "q8": 6, "q9": 6}),
        ("中等", {"bubbles": bubbles(mask([2, 4])), "writing": writing(w7_wrong(), w8_ok(), w9_ok())}, {"obj": 12, "q7": 1, "q8": 6, "q9": 6}),
        ("中上", {"bubbles": bubbles(mask([5])), "writing": writing(w7_half(), w8_half(), w9_ok())}, {"obj": 15, "q7": 3, "q8": 3, "q9": 6}),
        ("优秀", {"bubbles": bubbles(n), "writing": writing(w7_ok(), w8_half(), w9_ok())}, {"obj": 18, "q7": 6, "q8": 3, "q9": 6}),
        ("低分", {"bubbles": bubbles(mask([0, 1, 2, 3, 4])), "writing": writing(w7_wrong(), w8_wrong(), w_idk())}, {"obj": 3, "q7": 1, "q8": 1, "q9": 0}),
        ("低分", {"bubbles": bubbles(mask([0, 1, 2, 4])), "writing": writing(w_idk(), w8_wrong(), w9_half())}, {"obj": 6, "q7": 0, "q8": 1, "q9": 3}),
        ("中下", {"bubbles": bubbles(mask([1, 3, 5])), "writing": writing(w_idk(), w8_ok(), w9_wrong())}, {"obj": 9, "q7": 0, "q8": 6, "q9": 1}),
        ("只做客观", {"bubbles": bubbles(n), "writing": writing(w_blank(), w_blank(), w_blank())}, {"obj": 18, "q7": 0, "q8": 0, "q9": 0}),
        ("乱填", {"bubbles": bubbles(f), "writing": writing(["随便写几句"], w_idk(), ["琵琶很好听"])}, {"obj": 0, "q7": 1, "q8": 0, "q9": 1}),
        ("只会默写", {"bubbles": bubbles(mask([0, 1, 2, 4, 5])), "writing": writing(w_blank(), w_blank(), w9_full())}, {"obj": 3, "q7": 0, "q8": 0, "q9": 6}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2, 3, 4])), "writing": writing(w_idk(), w_idk(), w_idk())}, {"obj": 3, "q7": 0, "q8": 0, "q9": 0}),
        ("几乎空白", {"bubbles": bubbles([None] * 5 + [False]), "writing": writing(w_idk(), w_blank(), w_blank())}, {"obj": 0, "q7": 0, "q8": 0, "q9": 0}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2, 3, 5])), "writing": writing(w7_wrong(), w_blank(), w_idk())}, {"obj": 3, "q7": 1, "q8": 0, "q9": 0}),
        ("两极", {"bubbles": bubbles(mask([1, 4])), "writing": writing(w7_full(), w8_wrong(), w9_full())}, {"obj": 12, "q7": 6, "q8": 1, "q9": 6}),
        ("漏涂一题", {"bubbles": bubbles(mask([], skip=[2])), "writing": writing(w7_ok(), w8_full(), w9_half())}, {"obj": 15, "q7": 6, "q8": 6, "q9": 3}),
        ("客观全错主观会", {"bubbles": bubbles(f), "writing": writing(w7_full(), w8_full(), w9_full())}, {"obj": 0, "q7": 6, "q8": 6, "q9": 6}),
    ]


def pick_class() -> str:
    rows = mysql.fetch_all(
        """
        SELECT c.class_id, COUNT(e.student_id) AS n
        FROM classes c
        JOIN enrollments e ON e.class_id = c.class_id
        GROUP BY c.class_id
        ORDER BY n DESC, c.class_id DESC
        LIMIT 1
        """
    )
    if rows and int(rows[0]["n"]) > 0:
        return rows[0]["class_id"]
    raise SystemExit("找不到已导入名单的班级")


def main() -> None:
    parsed = parse_paper_file(SRC)
    items = parsed["items"]
    if len(items) != 9:
        raise SystemExit(f"题目数量异常：{len(items)}")
    for it in items:
        if it["kind"] == "subjective" and not it.get("rubric"):
            it["rubric"] = RUBRICS.get(int(it["number"]), ["要点正确", "表达清楚"])
    class_id = pick_class()
    students = mysql.list_class_students(class_id)
    if not students:
        raise SystemExit("班级没有学生")
    homework_id = uuid.uuid4().hex
    dest = homework_dir(homework_id, "papers") / SRC.name
    dest.write_bytes(SRC.read_bytes())
    persisted = _persist(
        class_id,
        parsed.get("name") or "语文练习",
        "语文",
        items,
        {"paper_path": relpath(dest), "md_path": relpath(dest)},
        homework_id=homework_id,
    )
    stored = mysql.list_items(homework_id)
    rendered = render_cards(homework_id, stored, students)
    mysql.upsert_card_template(homework_id, rendered["geometry"], rendered["print_path"])
    profs = profiles()
    scripts = {}
    summary = []
    for i, stu in enumerate(students):
        band, script, exp = profs[i % len(profs)]
        scripts[stu["student_no"]] = script
        total = exp["obj"] + exp["q7"] + exp["q8"] + exp["q9"]
        summary.append(
            {
                "student_no": stu["student_no"],
                "name": stu["name"],
                "band": band,
                "objective": exp["obj"],
                "q7": exp["q7"],
                "q8": exp["q8"],
                "q9": exp["q9"],
                "total": total,
                "percent": round(100 * total / TOTAL, 1),
                "obj_marked": len(script["bubbles"]),
            }
        )
    filled = make_filled_scans(homework_id, rendered["geometry"], students, stored, scripts=scripts)
    scan_dir = abspath(filled["print_path"])
    score_path = scan_dir / "scores.csv"
    with score_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["student_no", "name", "band", "objective", "q7", "q8", "q9", "total", "percent", "obj_marked"],
        )
        w.writeheader()
        w.writerows(summary)
    (scan_dir / "scripts.json").write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")
    downloads = Path(r"C:\Users\Administrator\Downloads") / "语文练习_30人已作答"
    if downloads.exists():
        shutil.rmtree(downloads)
    downloads.mkdir(parents=True)
    for p in scan_dir.glob("*_filled*.png"):
        shutil.copy2(p, downloads / p.name)
    shutil.copy2(score_path, downloads / "scores.csv")
    shutil.copy2(SRC, downloads / "语文练习.md")
    zip_path = downloads.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(downloads), "zip", downloads)
    print("homework_id", homework_id)
    print("class_id", class_id)
    print("n_pages", rendered.get("n_pages"))
    print("gradeable", persisted.get("gradeable"))
    print("zip", zip_path)
    for row in summary:
        print(f"{row['student_no']} {row['name']} {row['band']} {row['total']}/{TOTAL}")


if __name__ == "__main__":
    main()
