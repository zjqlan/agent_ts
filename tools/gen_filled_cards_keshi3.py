"""Generate 30 filled answer cards for 课时练习_3 with mixed score bands."""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from zypg.mcp_tools.card_render import make_filled_scans, render_cards  # noqa: E402

HOMEWORK_ID = "keshi_lianxi_3"
OBJ_IDS = [f"q{i}" for i in range(1, 11)]
SUB_IDS = ["q11", "q12", "q13"]
KEYS = ["C", "B", "C", "B", "B", "A", "C", "D", "C", "A"]
WRONG = {"A": "B", "B": "C", "C": "D", "D": "A"}
OBJ_PT = 4
TOTAL = 68


def items() -> list[dict]:
    out = []
    stems = [
        "二次函数开口向下且顶点在第一象限，一定成立的是",
        "函数的对称轴方程",
        "二次函数最小值为2，求参数值",
        "二次函数过三点，求解析式",
        "不等式的解集",
        "图象平移后的解析式",
        "方程有两个不相等实根时参数范围",
        "二次函数满足条件且最大值为8，求解析式",
        "闭区间上最大值与最小值之和",
        "与x轴两交点及对称轴，求另一交点",
        "求二次函数解析式及单调递减区间",
        "求区间上最小值的分段表达式",
        "求日利润最大值及对应售价",
    ]
    scores = [4] * 10 + [8, 10, 10]
    for i, stem in enumerate(stems, 1):
        kind = "objective" if i <= 10 else "subjective"
        it = {
            "item_id": f"q{i}",
            "number": i,
            "kind": kind,
            "stem": stem,
            "score": scores[i - 1],
        }
        if kind == "objective":
            it["answer_key"] = {"letter": KEYS[i - 1]}
            it["options"] = ["A", "B", "C", "D"]
        else:
            it["answer_key"] = {
                "text": [
                    "f(x)=-x^2+4x-3；单调递减区间[2,+∞)",
                    "g(m)=m^2-2m+3 (m<1); 2 (m>=1)",
                    "最大利润450元，售价35元",
                ][i - 11]
            }
        out.append(it)
    return out


def load_students() -> list[dict]:
    path = ROOT / "samples" / "class_roster_30.csv"
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({"student_no": row["student_no"].strip(), "name": row["name"].strip()})
    if len(rows) != 30:
        raise SystemExit(f"expected 30 students, got {len(rows)}")
    return rows


def bubbles(correct_mask: list[bool | None]) -> dict[str, str]:
    out = {}
    for i, flag in enumerate(correct_mask):
        if flag is None:
            continue
        key = KEYS[i]
        out[OBJ_IDS[i]] = key if flag else WRONG[key]
    return out


def w_full_11() -> list[str]:
    return [
        "设 f(x)=ax^2+bx+c，由图象开口及过点得 a=-1,b=4,c=-3",
        "所以 f(x)=-x^2+4x-3",
        "对称轴 x=2，开口向下，单调递减区间为 [2,+∞)",
    ]


def w_ok_11() -> list[str]:
    return ["f(x)=-x^2+4x-3", "递减区间 [2,+∞)"]


def w_half_11() -> list[str]:
    return ["解析式 f(x)=-x^2+4x-3", "好像从2开始递减，写成 (2,+∞)"]


def w_only_11() -> list[str]:
    return ["f(x)=-x^2+4x-3"]


def w_wrong_11() -> list[str]:
    return ["f(x)=x^2-4x+3", "递增区间 [2,+∞)"]


def w_full_12() -> list[str]:
    return [
        "分类讨论：当 m<1 时，最小值在端点或顶点处，g(m)=m^2-2m+3",
        "当 m>=1 时，最小值为 2",
        r"g(m)=\begin{cases} m^2-2m+3, m<1 \\ 2, m>=1 \end{cases}",
    ]


def w_ok_12() -> list[str]:
    return ["m<1: g(m)=m^2-2m+3", "m>=1: g(m)=2"]


def w_half_12() -> list[str]:
    return ["最小值好像恒为2", "没分类讨论"]


def w_wrong_12() -> list[str]:
    return ["g(m)=m^2-2m", "不用分类"]


def w_full_13() -> list[str]:
    return [
        "日利润 L=(售价-20)×日销售量，配方或求导",
        "当售价为35元时取得最大值",
        "最大利润为450元",
    ]


def w_ok_13() -> list[str]:
    return ["最大利润450元，售价35元"]


def w_half_13() -> list[str]:
    return ["售价应该是35元", "利润我算成400了"]


def w_wrong_13() -> list[str]:
    return ["售价20元利润最大", "利润200元"]


def w_blank() -> list[str]:
    return []


def w_idk() -> list[str]:
    return ["不会做"]


def w_messy() -> list[str]:
    return ["随便写一个二次函数", "答案大概是正的"]


def profile_scripts() -> list[tuple[str, dict, dict]]:
    """(band, script, expected_item_scores)."""
    n = [True] * 10
    f = [False] * 10

    def mask(wrong_idx: list[int], skip: list[int] | None = None) -> list[bool | None]:
        skip = skip or []
        m: list[bool | None] = [True] * 10
        for i in wrong_idx:
            m[i] = False
        for i in skip:
            m[i] = None
        return m

    # expected subj scores: q11/8, q12/10, q13/10
    rows: list[tuple[str, dict, dict]] = [
        ("满分", {"bubbles": bubbles(n), "writing": {"q11": w_full_11(), "q12": w_full_12(), "q13": w_full_13()}}, {"obj": 40, "q11": 8, "q12": 10, "q13": 10}),
        ("满分", {"bubbles": bubbles(n), "writing": {"q11": w_ok_11(), "q12": w_ok_12(), "q13": w_ok_13()}}, {"obj": 40, "q11": 8, "q12": 10, "q13": 10}),
        ("近满分", {"bubbles": bubbles(mask([2])), "writing": {"q11": w_full_11(), "q12": w_full_12(), "q13": w_full_13()}}, {"obj": 36, "q11": 8, "q12": 10, "q13": 10}),
        ("近满分", {"bubbles": bubbles(n), "writing": {"q11": w_half_11(), "q12": w_full_12(), "q13": w_full_13()}}, {"obj": 40, "q11": 6, "q12": 10, "q13": 10}),
        ("优秀", {"bubbles": bubbles(mask([7])), "writing": {"q11": w_ok_11(), "q12": w_ok_12(), "q13": w_ok_13()}}, {"obj": 36, "q11": 8, "q12": 10, "q13": 8}),
        ("优秀", {"bubbles": bubbles(mask([0, 8])), "writing": {"q11": w_full_11(), "q12": w_full_12(), "q13": w_ok_13()}}, {"obj": 32, "q11": 8, "q12": 10, "q13": 10}),
        ("中上", {"bubbles": bubbles(mask([1, 5])), "writing": {"q11": w_ok_11(), "q12": w_half_12(), "q13": w_ok_13()}}, {"obj": 32, "q11": 8, "q12": 5, "q13": 10}),
        ("中上", {"bubbles": bubbles(mask([3, 4, 9])), "writing": {"q11": w_ok_11(), "q12": w_ok_12(), "q13": w_half_13()}}, {"obj": 28, "q11": 8, "q12": 10, "q13": 6}),
        ("中等", {"bubbles": bubbles(mask([0, 2, 6])), "writing": {"q11": w_half_11(), "q12": w_half_12(), "q13": w_ok_13()}}, {"obj": 28, "q11": 6, "q12": 5, "q13": 8}),
        ("中等", {"bubbles": bubbles(mask([1, 3, 5, 7])), "writing": {"q11": w_ok_11(), "q12": w_half_12(), "q13": w_half_13()}}, {"obj": 24, "q11": 8, "q12": 5, "q13": 6}),
        ("中等", {"bubbles": bubbles(mask([2, 8])), "writing": {"q11": w_half_11(), "q12": w_ok_12(), "q13": w_wrong_13()}}, {"obj": 32, "q11": 6, "q12": 8, "q13": 2}),
        ("中等", {"bubbles": bubbles(mask([0, 1, 4, 9])), "writing": {"q11": w_only_11(), "q12": w_ok_12(), "q13": w_ok_13()}}, {"obj": 24, "q11": 4, "q12": 10, "q13": 8}),
        ("中下", {"bubbles": bubbles(mask([0, 2, 3, 6, 8])), "writing": {"q11": w_ok_11(), "q12": w_wrong_12(), "q13": w_half_13()}}, {"obj": 20, "q11": 8, "q12": 2, "q13": 6}),
        ("中下", {"bubbles": bubbles(mask([1, 2, 4, 5, 7])), "writing": {"q11": w_half_11(), "q12": w_half_12(), "q13": w_wrong_13()}}, {"obj": 20, "q11": 6, "q12": 5, "q13": 2}),
        ("中下", {"bubbles": bubbles(mask([0, 1, 3, 6, 8, 9])), "writing": {"q11": w_only_11(), "q12": w_wrong_12(), "q13": w_ok_13()}}, {"obj": 16, "q11": 4, "q12": 2, "q13": 8}),
        ("中等", {"bubbles": bubbles(mask([4, 5, 7])), "writing": {"q11": w_wrong_11(), "q12": w_ok_12(), "q13": w_ok_13()}}, {"obj": 28, "q11": 2, "q12": 10, "q13": 8}),
        ("中上", {"bubbles": bubbles(mask([9])), "writing": {"q11": w_half_11(), "q12": w_half_12(), "q13": w_ok_13()}}, {"obj": 36, "q11": 6, "q12": 5, "q13": 10}),
        ("优秀", {"bubbles": bubbles(n), "writing": {"q11": w_ok_11(), "q12": w_half_12(), "q13": w_ok_13()}}, {"obj": 40, "q11": 8, "q12": 5, "q13": 10}),
        ("低分", {"bubbles": bubbles(mask([0, 1, 2, 3, 4, 5, 8])), "writing": {"q11": w_wrong_11(), "q12": w_wrong_12(), "q13": w_idk()}}, {"obj": 12, "q11": 2, "q12": 2, "q13": 0}),
        ("低分", {"bubbles": bubbles(mask([0, 1, 2, 4, 6, 7])), "writing": {"q11": w_idk(), "q12": w_wrong_12(), "q13": w_half_13()}}, {"obj": 16, "q11": 0, "q12": 2, "q13": 6}),
        ("中下", {"bubbles": bubbles(mask([1, 3, 5, 7, 8])), "writing": {"q11": w_idk(), "q12": w_ok_12(), "q13": w_wrong_13()}}, {"obj": 20, "q11": 0, "q12": 10, "q13": 2}),
        ("只做客观", {"bubbles": bubbles(n), "writing": {"q11": w_blank(), "q12": w_blank(), "q13": w_blank()}}, {"obj": 40, "q11": 0, "q12": 0, "q13": 0}),
        ("乱填", {"bubbles": bubbles(f), "writing": {"q11": w_messy(), "q12": w_idk(), "q13": w_messy()}}, {"obj": 0, "q11": 1, "q12": 0, "q13": 1}),
        ("只会第11题", {"bubbles": bubbles(mask([0, 2, 3, 5, 6, 8, 9])), "writing": {"q11": w_full_11(), "q12": w_blank(), "q13": w_blank()}}, {"obj": 12, "q11": 8, "q12": 0, "q13": 0}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2, 3, 4, 5, 6, 7, 8])), "writing": {"q11": w_idk(), "q12": w_idk(), "q13": w_idk()}}, {"obj": 4, "q11": 0, "q12": 0, "q13": 0}),
        ("几乎空白", {"bubbles": bubbles([None] * 9 + [False]), "writing": {"q11": w_idk(), "q12": w_blank(), "q13": w_blank()}}, {"obj": 0, "q11": 0, "q12": 0, "q13": 0}),
        ("很低", {"bubbles": bubbles(mask([0, 1, 2, 3, 4, 6, 7, 8])), "writing": {"q11": w_wrong_11(), "q12": w_blank(), "q13": w_idk()}}, {"obj": 8, "q11": 2, "q12": 0, "q13": 0}),
        ("两极", {"bubbles": bubbles(mask([1, 2, 5, 8])), "writing": {"q11": w_full_11(), "q12": w_wrong_12(), "q13": w_full_13()}}, {"obj": 24, "q11": 8, "q12": 2, "q13": 10}),
        ("漏涂一题", {"bubbles": bubbles(mask([], skip=[4])), "writing": {"q11": w_ok_11(), "q12": w_full_12(), "q13": w_half_13()}}, {"obj": 36, "q11": 8, "q12": 10, "q13": 6}),
        ("客观全错主观会", {"bubbles": bubbles(f), "writing": {"q11": w_full_11(), "q12": w_full_12(), "q13": w_full_13()}}, {"obj": 0, "q11": 8, "q12": 10, "q13": 10}),
    ]
    if len(rows) != 30:
        raise SystemExit(f"need 30 profiles, got {len(rows)}")
    return rows


def main() -> None:
    students = load_students()
    paper_items = items()
    profiles = profile_scripts()
    rendered = render_cards(HOMEWORK_ID, paper_items, students)
    scripts = {}
    summary = []
    for stu, (band, script, exp) in zip(students, profiles, strict=True):
        scripts[stu["student_no"]] = script
        total = exp["obj"] + exp["q11"] + exp["q12"] + exp["q13"]
        summary.append(
            {
                "student_no": stu["student_no"],
                "name": stu["name"],
                "band": band,
                "objective": exp["obj"],
                "q11": exp["q11"],
                "q12": exp["q12"],
                "q13": exp["q13"],
                "total": total,
                "percent": round(100 * total / TOTAL, 1),
                "obj_marked": sum(1 for _ in script["bubbles"]),
            }
        )
    filled = make_filled_scans(
        HOMEWORK_ID,
        rendered["geometry"],
        students,
        paper_items,
        scripts=scripts,
    )

    dest = ROOT / "data" / "files" / "scans" / HOMEWORK_ID
    dest.mkdir(parents=True, exist_ok=True)
    score_path = dest / "scores.csv"
    with score_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["student_no", "name", "band", "objective", "q11", "q12", "q13", "total", "percent", "obj_marked"],
        )
        w.writeheader()
        w.writerows(summary)

    meta = dest / "scripts.json"
    meta.write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")

    downloads = Path(r"C:\Users\Administrator\Downloads") / "课时练习_3_已完成答题卡"
    if downloads.exists():
        shutil.rmtree(downloads)
    downloads.mkdir(parents=True)
    for p in dest.glob("*_filled.png"):
        shutil.copy2(p, downloads / p.name)
    shutil.copy2(score_path, downloads / "scores.csv")
    shutil.copy2(ROOT / "samples" / "class_roster_30.csv", downloads / "roster.csv")

    zip_path = downloads.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(downloads), "zip", downloads)

    print(f"homework_id={HOMEWORK_ID}")
    print(f"blank+named cards: {rendered['print_path']} count={rendered['count']}")
    print(f"filled scans: {filled['print_path']} count={filled['count']}")
    print(f"score csv: {score_path}")
    print(f"downloads: {downloads}")
    print(f"zip: {zip_path}")
    for row in summary:
        print(f"{row['student_no']} {row['name']} {row['band']} {row['total']}/{TOTAL}")


if __name__ == "__main__":
    main()
