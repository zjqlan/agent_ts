from __future__ import annotations

from collections import defaultdict
from typing import Any

from zypg.storage import mysql

_BLANK = {"", "未标注", "未指定知识点", "none", "null"}


def _pending(row: dict[str, Any] | None) -> bool:
    if not row:
        return True
    v = row.get("pending")
    if v in (None, "", False):
        return False
    try:
        return int(v) != 0
    except (TypeError, ValueError):
        return bool(v)


def _kp(it: dict[str, Any] | None) -> str:
    v = str((it or {}).get("knowledge_point") or "").strip()
    if v and v.lower() not in _BLANK:
        return v
    n = (it or {}).get("number") or (it or {}).get("item_id") or "?"
    return f"第{n}题"


def _dummy_kp(kp: str) -> bool:
    s = str(kp or "").strip()
    if not s or s.lower() in _BLANK:
        return True
    return s.startswith("第") and s.endswith("题")


def _passed(row: dict[str, Any], item: dict[str, Any]) -> bool | None:
    if _pending(row):
        return None
    if item.get("kind") == "subjective":
        mx = float(item.get("score") or 0)
        sc = row.get("score")
        if sc is None or mx <= 0:
            return None
        return float(sc) >= 0.6 * mx
    if row.get("is_correct") is None:
        return None
    return int(row["is_correct"]) == 1


def list_committed_homeworks(class_id: str) -> list[dict[str, Any]]:
    return mysql.fetch_all(
        """
        SELECT DISTINCT a.homework_id, a.name, a.created_at
        FROM mastery_events m
        JOIN assignments a ON a.homework_id = m.homework_id
        WHERE a.class_id = :cid
        ORDER BY a.created_at ASC, a.homework_id ASC
        """,
        cid=class_id,
    )


def class_kp_accuracy(homework_id: str) -> dict[str, dict[str, Any]]:
    items = mysql.list_items(homework_id)
    results = mysql.list_item_results(homework_id)
    by_item: dict[str, list] = defaultdict(list)
    for r in results:
        by_item[r["item_id"]].append(r)
    stats: dict[str, list[int]] = defaultdict(list)
    for it in items:
        kp = _kp(it)
        for r in by_item.get(it["item_id"], []):
            ok = _passed(r, it)
            if ok is None:
                continue
            stats[kp].append(1 if ok else 0)
    out = {}
    for kp, bits in stats.items():
        if not bits:
            continue
        out[kp] = {"accuracy": sum(bits) / len(bits), "n": len(bits)}
    return out


def student_score_rate(homework_id: str, student_id: str) -> dict[str, Any] | None:
    items = mysql.list_items(homework_id)
    full = sum(float(it.get("score") or 0) for it in items)
    results = mysql.list_item_results(homework_id, student_id)
    got = 0.0
    n_conf = 0
    for r in results:
        if _pending(r) or r.get("score") is None:
            continue
        got += float(r["score"])
        n_conf += 1
    if n_conf == 0 or full <= 0:
        return None
    return {"score": got, "full_score": full, "rate": got / full}


def class_avg_rate(homework_id: str) -> float | None:
    students = {r["student_id"] for r in mysql.list_item_results(homework_id) if r.get("student_id")}
    rates = []
    for sid in students:
        one = student_score_rate(homework_id, sid)
        if one:
            rates.append(one["rate"])
    if not rates:
        return None
    return sum(rates) / len(rates)


def commit_mastery(homework_id: str, class_id: str) -> int:
    items = mysql.list_items(homework_id)
    students = mysql.list_class_students(class_id)
    results = mysql.list_item_results(homework_id)
    by = {(r["student_id"], r["item_id"]): r for r in results}
    grouped: dict[str, list] = defaultdict(list)
    for it in items:
        grouped[_kp(it)].append(it)
    mysql.delete_mastery_for_homework(homework_id)
    n = 0
    for stu in students:
        sid = stu["student_id"]
        for kp, its in grouped.items():
            bits = []
            for it in its:
                row = by.get((sid, it["item_id"]))
                if not row:
                    continue
                ok = _passed(row, it)
                if ok is None:
                    continue
                bits.append(1 if ok else 0)
            if not bits:
                mastery = "untested"
            elif sum(bits) / len(bits) >= 0.8:
                mastery = "mastered"
            else:
                mastery = "weak"
            mysql.insert_mastery(sid, homework_id, kp, mastery)
            n += 1
    return n


def build_class_long(class_id: str) -> dict[str, Any]:
    hws = list_committed_homeworks(class_id)
    students = {s["student_id"]: s["student_no"] for s in mysql.list_class_students(class_id)}
    events = mysql.list_mastery(class_id)
    heat: dict[str, dict[str, str]] = {}
    by_pair: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    hw_order = [h["homework_id"] for h in hws]
    hw_name = {h["homework_id"]: h.get("name") or h["homework_id"] for h in hws}
    ev_by_hw: dict[str, list] = defaultdict(list)
    for e in events:
        no = students.get(e["student_id"], e["student_id"])
        heat.setdefault(no, {})[e["knowledge_point"]] = e["mastery"]
        ev_by_hw[e["homework_id"]].append(e)
        by_pair[(e["student_id"], e["knowledge_point"])].append((e["homework_id"], e["mastery"]))

    kp_trend: list[dict[str, Any]] = []
    last_acc: dict[str, float] = {}
    ever_must: set[str] = set()
    acc_series: dict[str, list[float]] = defaultdict(list)
    for hw in hws:
        accs = class_kp_accuracy(hw["homework_id"])
        for kp, info in accs.items():
            if _dummy_kp(kp):
                continue
            a = float(info["accuracy"])
            kp_trend.append(
                {
                    "homework_id": hw["homework_id"],
                    "homework_name": hw_name[hw["homework_id"]],
                    "knowledge_point": kp,
                    "accuracy": round(a, 4),
                    "n": info["n"],
                }
            )
            acc_series[kp].append(a)
            last_acc[kp] = a
            if a < 0.6:
                ever_must.add(kp)

    weakest_latest = sorted(last_acc, key=lambda k: last_acc[k])[:5]
    default_kps = sorted(ever_must | set(weakest_latest))

    term_weak = []
    for kp, arr in acc_series.items():
        if not arr:
            continue
        term_weak.append({"knowledge_point": kp, "avg_accuracy": round(sum(arr) / len(arr), 4), "n_hw": len(arr)})
    term_weak.sort(key=lambda x: x["avg_accuracy"])
    term_weak_top3 = term_weak[:3]

    consecutive_weak: list[dict[str, Any]] = []
    if len(hw_order) >= 2:
        latest = { (e["student_id"], e["knowledge_point"]): e["mastery"] for e in ev_by_hw.get(hw_order[-1], []) }
        prev = { (e["student_id"], e["knowledge_point"]): e["mastery"] for e in ev_by_hw.get(hw_order[-2], []) }
        seen = set()
        for sid, kp in set(latest) | set(prev):
            if latest.get((sid, kp)) != "weak" or prev.get((sid, kp)) != "weak":
                continue
            key = (sid, kp)
            if key in seen:
                continue
            seen.add(key)
            streak = 0
            for hid in reversed(hw_order):
                m = next((e["mastery"] for e in ev_by_hw.get(hid, []) if e["student_id"] == sid and e["knowledge_point"] == kp), "untested")
                if m == "weak":
                    streak += 1
                else:
                    break
            consecutive_weak.append(
                {
                    "student_id": sid,
                    "student_no": students.get(sid, sid),
                    "knowledge_point": kp,
                    "streak": streak,
                    "last_homework": hw_name[hw_order[-1]],
                }
            )
        consecutive_weak.sort(key=lambda r: (-r["streak"], r["student_no"], r["knowledge_point"]))

    n_commits = len(hws)
    return {
        "window": "long",
        "scope": "class",
        "n_commits": n_commits,
        "can_trend": n_commits >= 2,
        "homework_ids": hw_order,
        "kp_trend": kp_trend,
        "trend_kps": default_kps,
        "consecutive_weak": consecutive_weak,
        "continuous_weak": sorted({r["student_no"] for r in consecutive_weak}),
        "term_weak_top3": term_weak_top3,
        "mastery_heat": heat,
        "mastery_events": len(events),
    }


def build_student_long(class_id: str, student_id: str) -> dict[str, Any]:
    hws = list_committed_homeworks(class_id)
    events = mysql.list_mastery(class_id, student_id)
    kps: dict[str, str] = {}
    grid: list[dict[str, Any]] = []
    by_hw: dict[str, dict[str, str]] = defaultdict(dict)
    for e in events:
        kps[e["knowledge_point"]] = e["mastery"]
        by_hw[e["homework_id"]][e["knowledge_point"]] = e["mastery"]
    hw_name = {h["homework_id"]: h.get("name") or h["homework_id"] for h in hws}
    score_trend = []
    class_trend = []
    for hw in hws:
        hid = hw["homework_id"]
        mine = student_score_rate(hid, student_id)
        cls = class_avg_rate(hid)
        if mine:
            score_trend.append(
                {
                    "homework_id": hid,
                    "homework_name": hw_name[hid],
                    "rate": round(mine["rate"], 4),
                    "score": mine["score"],
                    "full_score": mine["full_score"],
                }
            )
        if cls is not None:
            class_trend.append({"homework_id": hid, "rate": round(cls, 4)})
        for kp, m in by_hw.get(hid, {}).items():
            grid.append(
                {
                    "homework_id": hid,
                    "homework_name": hw_name[hid],
                    "knowledge_point": kp,
                    "mastery": m,
                }
            )

    consecutive = []
    hw_order = [h["homework_id"] for h in hws]
    if len(hw_order) >= 2:
        kset = {g["knowledge_point"] for g in grid}
        for kp in sorted(kset):
            last = by_hw.get(hw_order[-1], {}).get(kp, "untested")
            prev = by_hw.get(hw_order[-2], {}).get(kp, "untested")
            if last == "weak" and prev == "weak":
                since = hw_name[hw_order[-2]]
                streak = 0
                start = hw_order[-1]
                for hid in reversed(hw_order):
                    if by_hw.get(hid, {}).get(kp) == "weak":
                        streak += 1
                        start = hid
                    else:
                        break
                consecutive.append(
                    {
                        "knowledge_point": kp,
                        "streak": streak,
                        "since_homework": hw_name.get(start, start),
                    }
                )

    n = min(3, len(score_trend), len(class_trend))
    vs = None
    if n:
        s = sum(x["rate"] for x in score_trend[-n:]) / n
        c = sum(x["rate"] for x in class_trend[-n:]) / n
        vs = {
            "n": n,
            "student_rate": round(s, 4),
            "class_rate": round(c, 4),
            "delta": round(s - c, 4),
        }

    return {
        "scope": "student",
        "window": "long",
        "class_id": class_id,
        "student_id": student_id,
        "n_commits": len(hws),
        "can_trend": len(score_trend) >= 2,
        "mastery": kps,
        "labels": ["mastered", "weak", "untested"],
        "score_trend": score_trend,
        "mastery_grid": grid,
        "consecutive": consecutive,
        "vs_class": vs,
    }
