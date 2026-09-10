"""Fill 30 student scans on the latest printed answer-card template."""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from zypg.mcp_tools.card_render import make_filled_scans  # noqa: E402
from zypg.storage import mysql  # noqa: E402
from zypg.storage.files import abspath  # noqa: E402

HOMEWORK_ID = "b8e3089ea75e4c0797ed523c851f5c13"
OBJ_IDS = [f"q{i}" for i in range(2, 12)]
KEYS = ["C", "B", "C", "B", "B", "A", "C", "D", "C", "A"]
WRONG = {"A": "B", "B": "C", "C": "D", "D": "A"}
OBJ_PT = 5
SUB_MAX = {"q12": 10, "q13": 10, "q14": 10}
TOTAL = 80  # 10*5 + 10+10+10, skip the imported title box q1


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
    m: list[bool | None] = [True] * 10
    for i in wrong_idx:
        m[i] = False
    for i in skip:
        m[i] = None
    return m


def w_full_12() -> list[str]:
    return [
        "设 f(x)=ax^2+bx+c，由图象开口及过点得 a=-1,b=4,c=-3",
        "所以 f(x)=-x^2+4x-3",
        "对称轴 x=2，开口向下，单调递减区间为 [2,+∞)",
    ]


def w_ok_12() -> list[str]:
    return ["f(x)=-x^2+4x-3", "递减区间 [2,+∞)"]


def w_half_12() -> list[str]:
    return ["解析式 f(x)=-x^2+4x-3", "区间写成 (2,+∞)"]


def w_only_12() -> list[str]:
    return ["f(x)=-x^2+4x-3"]


def w_wrong_12() -> list[str]:
    return ["f(x)=x^2-4x+3", "递增区间 [2,+∞)"]


def w_full_13() -> list[str]:
    return [
        "分类讨论：当 m<1 时，最小值 g(m)=m^2-2m+3",
        "当 m>=1 时，最小值为 2",
        "分段写出 g(m)",
    ]


def w_ok_13() -> list[str]:
    return ["m<1: g(m)=m^2-2m+3", "m>=1: g(m)=2"]


def w_half_13() -> list[str]:
    return ["最小值好像恒为2", "没分类讨论"]


def w_wrong_13() -> list[str]:
    return ["g(m)=m^2-2m", "不用分类"]


def w_full_14() -> list[str]:
    return [
        "日利润 L=(售价-20)×日销售量，配方或求导",
        "当售价为35元时取得最大值",
        "最大利润为450元",
    ]


def w_ok_14() -> list[str]:
    return ["最大利润450元，售价35元"]


def w_half_14() -> list[str]:
    return ["售价应该是35元", "利润我算成400了"]


def w_wrong_14() -> list[str]:
    return ["售价20元利润最大", "利润200元"]


def w_blank() -> list[str]:
    return []


def w_idk() -> list[str]:
    return ["不会做"]


def w_messy() -> list[str]:
    return ["随便写一个二次函数"]


def writing(q12: list[str], q13: list[str], q14: list[str], q1: list[str] | None = None) -> dict:
    out = {"q12": q12, "q13": q13, "q14": q14}
    if q1:
        out["q1"] = q1
    return out


def profiles() -> list[tuple[str, dict, dict]]:
    n = [True] * 10
    f = [False] * 10
    return [
        ("满分", {"bubbles": bubbles(n), "writing": writing(w_full_12(), w_full_13(), w_full_14())}, {"obj": 50, "q12": 10, "q13": 10, "q14": 10}),
        ("满分", {"bubbles": bubbles(n), "writing": writing(w_ok_12(), w_ok_13(), w_ok_14())}, {"obj": 50, "q12": 10, "q13": 10, "q14": 10}),
        ("近满分", {"bubbles": bubbles(mask([2])), "writing": writing(w_full_12(), w_full_13(), w_full_14())}, {"obj": 45, "q12": 10, "q13": 10, "q14": 10}),
        ("近满分", {"bubbles": bubbles(n), "writing": writing(w_half_12(), w_full_13(), w_full_14())}, {"obj": 50, "q12": 6, "q13": 10, "q14": 10}),
        ("优秀", {"bubbles": bubbles(mask([7])), "writing": writing(w_ok_12(), w_ok_13(), w_ok_14())}, {"obj": 45, "q12": 10, "q13": 10, "q14": 8}),
        ("优秀", {"bubbles": bubbles(mask([0, 8])), "writing": writing(w_full_12(), w_full_13(), w_ok_14())}, {"obj": 40, "q12": 10, "q13": 10, "q14": 10}),
        ("中上", {"bubbles": bubbles(mask([1, 5])), "writing": writing(w_ok_12(), w_half_13(), w_ok_14())}, {"obj": 40, "q12": 10, "q13": 5, "q14": 10}),
        ("中上", {"bubbles": bubbles(mask([3, 4, 9])), "writing": writing(w_ok_12(), w_ok_13(), w_half_14())}, {"obj": 35, "q12": 10, "q13": 10, "q14": 6}),
        ("中等", {"bubbles": bubbles(mask([0, 2, 6])), "writing": writing(w_half_12(), w_half_13(), w_ok_14())}, {"obj": 35, "q12": 6, "q13": 5, "q14": 8}),
        ("中等", {"bubbles": bubbles(mask([1, 3, 5, 7])), "writing": writing(w_ok_12(), w_half_13(), w_half_14())}, {"obj": 30, "q12": 10, "q13": 5, "q14": 6}),
        ("中等", {"bubbles": bubbles(mask([2, 8])), "writing": writing(w_half_12(), w_ok_13(), w_wrong_14())}, {"obj": 40, "q12": 6, "q13": 8, "q14": 2}),
        ("中等", {"bubbles": bubbles(mask([0, 1, 4, 9])), "writing": writing(w_only_12(), w_ok_13(), w_ok_14())}, {"obj": 30, "q12": 4, "q13": 10, "q14": 8}),
        ("中下", {"bubbles": bubbles(mask([0, 2, 3, 6, 8])), "writing": writing(w_ok_12(), w_wrong_13(), w_half_14())}, {"obj": 25, "q12": 10, "q13": 2, "q14": 6}),
        ("中下", {"bubbles": bubbles(mask([1, 2, 4, 5, 7])), "writing": writing(w_half_12(), w_half_13(), w_wrong_14())}, {"obj": 25, "q12": 6, "q13": 5, "q14": 2}),
        ("中下", {"bubbles": bubbles(mask([0, 1, 3, 6, 8, 9])), "writing": writing(w_only_12(), w_wrong_13(), w_ok_14())}, {"obj": 20, "q12": 4, "q13": 2, "q14": 8}),
        ("中等", {"bubbles": bubbles(mask([4, 5, 7])), "writing": writing(w_wrong_12(), w_ok_13(), w_ok_14())}, {"obj": 35, "q12": 2, "q13": 10, "q14": 8}),
        ("中上", {"bubbles": bubbles(mask([9])), "writing": writing(w_half_12(), w_half_13(), w_ok_14())}, {"obj": 45, "q12": 6, "q13": 5, "q14": 10}),
        ("优秀", {"bubbles": bubbles(n), "writing": writing(w_ok_12(), w_half_13(), w_ok_14())}, {"obj": 50, "q12": 10, "q13": 5, "q14": 10}),
        ("低分", {"bubbles": bubbles(mask([0, 1, 2, 3, 4, 5, 8])), "writing": writing(w_wrong_12(), w_wrong_13(), w_idk())}, {"obj": 15, "q12": 2, "q13": 2, "q14": 0}),
        ("低分", {"bubbles": bubbles(mask([0, 1, 2, 4, 6, 7])), "writing": writing(w_idk(), w_wrong_13(), w_half_14())}, {"obj": 20, "q12": 0, "q13": 2, "q14": 6}),
        ("中下", {"bubbles": bubbles(mask([1, 3, 5, 7, 8])), "writing": writing(w_idk(), w_ok_13(), w_wrong_14())}, {"obj": 25, "q12": 0, "q13": 10, "q14": 2}),
        ("只做客观", {"bubbles": bubbles(n), "writing": writing(w_blank(), w_blank(), w_blank())}, {"obj": 50, "q12": 0, "q13": 0, "q14": 0}),
        ("乱填", {"bubbles": bubbles(f), "writing": writing(w_messy(), w_idk(), w_messy())}, {"obj": 0, "q12": 1, "q13": 0, "q14": 1}),
        ("只会解析式", {"bubbles": bubbles(mask([0, 2, 3, 5, 6, 8, 9])), "writing": writing(w_full_12(), w_blank(), w_blank())}, {"obj": 15, "q12": 10, "q13": 0, "q14": 0}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2, 3, 4, 5, 6, 7, 8])), "writing": writing(w_idk(), w_idk(), w_idk())}, {"obj": 5, "q12": 0, "q13": 0, "q14": 0}),
        ("几乎空白", {"bubbles": bubbles([None] * 9 + [False]), "writing": writing(w_idk(), w_blank(), w_blank(), q1=["不会"])}, {"obj": 0, "q12": 0, "q13": 0, "q14": 0}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2, 3, 4, 6, 7, 8])), "writing": writing(w_wrong_12(), w_blank(), w_idk())}, {"obj": 10, "q12": 2, "q13": 0, "q14": 0}),
        ("两极", {"bubbles": bubbles(mask([1, 2, 5, 8])), "writing": writing(w_full_12(), w_wrong_13(), w_full_14())}, {"obj": 30, "q12": 10, "q13": 2, "q14": 10}),
        ("漏涂一题", {"bubbles": bubbles(mask([], skip=[4])), "writing": writing(w_ok_12(), w_full_13(), w_half_14())}, {"obj": 45, "q12": 10, "q13": 10, "q14": 6}),
        ("客观全错主观会", {"bubbles": bubbles(f), "writing": writing(w_full_12(), w_full_13(), w_full_14())}, {"obj": 0, "q12": 10, "q13": 10, "q14": 10}),
    ]


def main() -> None:
    tmpl = mysql.get_card_template(HOMEWORK_ID)
    if not tmpl:
        raise SystemExit("找不到新答题卡模板")
    hw = mysql.get_assignment(HOMEWORK_ID)
    students = mysql.list_class_students(hw["class_id"])
    items = mysql.list_items(HOMEWORK_ID)
    if len(students) != 30:
        raise SystemExit(f"班级人数不是30：{len(students)}")
    profs = profiles()
    if len(profs) != 30:
        raise SystemExit(f"档位不是30：{len(profs)}")
    scripts = {}
    summary = []
    for stu, (band, script, exp) in zip(students, profs, strict=True):
        scripts[stu["student_no"]] = script
        total = exp["obj"] + exp["q12"] + exp["q13"] + exp["q14"]
        summary.append(
            {
                "student_no": stu["student_no"],
                "name": stu["name"],
                "band": band,
                "objective": exp["obj"],
                "q12": exp["q12"],
                "q13": exp["q13"],
                "q14": exp["q14"],
                "total": total,
                "percent": round(100 * total / TOTAL, 1),
                "obj_marked": len(script["bubbles"]),
            }
        )
    filled = make_filled_scans(HOMEWORK_ID, tmpl["geometry"], students, items, scripts=scripts)
    dest = abspath(filled["print_path"])
    score_path = dest / "scores.csv"
    with score_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["student_no", "name", "band", "objective", "q12", "q13", "q14", "total", "percent", "obj_marked"],
        )
        w.writeheader()
        w.writerows(summary)
    (dest / "scripts.json").write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")

    downloads = Path(r"C:\Users\Administrator\Downloads") / "新答题卡_30人已作答"
    if downloads.exists():
        shutil.rmtree(downloads)
    downloads.mkdir(parents=True)
    for p in dest.glob("*_filled.png"):
        shutil.copy2(p, downloads / p.name)
    shutil.copy2(score_path, downloads / "scores.csv")
    zip_path = downloads.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(downloads), "zip", downloads)
    print("count", filled["count"])
    print("scans", dest)
    print("zip", zip_path)
    for row in summary:
        print(f"{row['student_no']} {row['name']} {row['band']} {row['total']}/{TOTAL}")


if __name__ == "__main__":
    main()
