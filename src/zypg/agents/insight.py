from __future__ import annotations

import json
from typing import Any

from zypg.agents.base import PeerAgent
from zypg.config import settings
from zypg.llm import LLMError, complete_json
from zypg.models import A2AMessage, FORBIDDEN_PROFILE_TERMS, InsightPack
from zypg.protocol.mcp import call_internal
from zypg.roster.service import require_roster
from zypg.storage import mysql, redis_store

CLASS_REVIEW_SYSTEM = (
    "你是任课教师，根据已给班级统计写讲评要点，不要编造数字。"
    "口吻像跟同事交代明天课：具体、可执行、用人话。"
    "只输出 JSON："
    '{"headline":str,"comment":str,"first_teach":str,'
    '"watch_who":[{"student_no":str,"why":str}],'
    '"next_focus":str,"classroom_moves":[str],"must_teach_why":[str]}。'
    "headline 一句话；comment 4～8 句；first_teach 全班先讲哪题/哪点；"
    "watch_who 只点名单里出现的学号，why 必须引用已给数据；"
    "classroom_moves 3～5 条课堂上能立刻做的事。"
    "禁止写「未标注」。没有知识点名称时用第几题和题干来说。"
    "禁止人格、差生、家庭、心理、高考预测。"
)

STUDENT_COACH_SYSTEM = (
    "你是任课教师，根据该生已给作答写个人辅导建议，不要编造分数。"
    "只输出 JSON："
    '{"headline":str,"comment":str,"strengths":[str],"needs":[str],"next_steps":[str]}。'
    "用学号称呼，对人话、可执行。禁止人格、差生、家庭、心理、高考预测。"
)

LLM_KEEP = (
    "llm_review",
    "llm_model",
    "headline",
    "first_teach",
    "watch_who",
    "next_focus",
    "classroom_moves",
    "must_teach_why",
    "coach",
)


class InsightAgent(PeerAgent):
    name = "insight"
    description = "班级与个人学情，短长期快照"

    def skills(self) -> list[str]:
        return ["class_insight", "student_insight", "commit_long_term"]

    async def handle(self, message: A2AMessage) -> dict[str, Any]:
        p = message.payload
        require_roster(p.get("class_id"))
        if message.skill == "class_insight":
            return await self._class_insight(p)
        if message.skill == "student_insight":
            return await self._student_insight(p)
        if message.skill == "commit_long_term":
            return await self._commit(p)
        raise ValueError(f"unknown skill {message.skill}")

    async def _class_insight(self, p: dict[str, Any]) -> dict[str, Any]:
        class_id = p["class_id"]
        homework_id = p.get("homework_id") or _latest_hw(class_id)
        await _ensure_item_knowledge_points(homework_id)
        short = _build_class_short(class_id, homework_id)
        longp = _build_class_long(class_id)
        charts = await call_internal(
            "render_charts",
            {
                "class_id": class_id,
                "homework_id": homework_id,
                "pack": {**short, "mastery_heat": longp.get("mastery_heat") or {}},
            },
        )
        short["charts"] = charts
        try:
            await _fill_class_review(short, longp)
        except LLMError as exc:
            short["llm_error"] = str(exc)
            short["llm_review"] = short.get("llm_review") or ""
            _save_pack(homework_id, class_id, "class", "short", None, short)
            _save_pack(None, class_id, "class", "long", None, longp)
            redis_store.set_insight_hot(class_id, {"short": short, "long": longp})
            raise LLMError(f"学情讲评需要大模型：{exc}") from exc
        _save_pack(homework_id, class_id, "class", "short", None, short)
        _save_pack(None, class_id, "class", "long", None, longp)
        redis_store.set_insight_hot(class_id, {"short": short, "long": longp})
        return {
            "class": InsightPack(
                class_id=class_id,
                homework_id=homework_id,
                scope="class",
                window="short",
                pending_note=short.get("pending_note"),
                payload=short,
            ).model_dump(),
            "long": longp,
        }

    async def _student_insight(self, p: dict[str, Any]) -> dict[str, Any]:
        class_id = p["class_id"]
        student_id = p.get("student_id")
        if not student_id:
            raise ValueError("请说明学号，例如「看看学号 S02 的学情」或「学生1情况」。")
        homework_id = p.get("homework_id") or _latest_hw(class_id)
        await _ensure_item_knowledge_points(homework_id)
        short = _build_student_short(class_id, homework_id, student_id)
        longp = _build_student_long(class_id, student_id)
        try:
            await _fill_student_coach(short, longp)
        except LLMError as exc:
            short["llm_error"] = str(exc)
            _save_pack(homework_id, class_id, "student", "short", student_id, short)
            _save_pack(None, class_id, "student", "long", student_id, longp)
            raise LLMError(f"个人学情需要大模型：{exc}") from exc
        _save_pack(homework_id, class_id, "student", "short", student_id, short)
        _save_pack(None, class_id, "student", "long", student_id, longp)
        return {"short": short, "long": longp, "scope": "student"}

    async def _commit(self, p: dict[str, Any]) -> dict[str, Any]:
        homework_id = p["homework_id"]
        hw = mysql.get_assignment(homework_id)
        if not hw:
            raise ValueError("作业不存在")
        from zypg.agents.insight_term import build_class_long, commit_mastery

        n = commit_mastery(homework_id, hw["class_id"])
        longp = build_class_long(hw["class_id"])
        _save_pack(None, hw["class_id"], "class", "long", None, longp)
        return {
            "ok": True,
            "events": n,
            "n_commits": longp.get("n_commits"),
            "can_trend": longp.get("can_trend"),
            "term_weak_top3": longp.get("term_weak_top3") or [],
        }


def _latest_hw(class_id: str) -> str | None:
    rows = mysql.list_homeworks(class_id)
    return rows[0]["homework_id"] if rows else None


def _save_pack(
    homework_id: str | None,
    class_id: str,
    scope: str,
    window: str,
    student_id: str | None,
    payload: dict[str, Any],
) -> None:
    text = str(payload)
    for term in FORBIDDEN_PROFILE_TERMS:
        if term in text:
            raise ValueError(f"画像禁止出现：{term}")
    mysql.insert_snapshot(homework_id, class_id, scope, window, student_id, payload)


async def _fill_class_review(short: dict[str, Any], longp: dict[str, Any]) -> None:
    facts = {
        "average": short.get("average"),
        "max_total": short.get("max_total"),
        "n_submitted": short.get("n_submitted"),
        "n_students": short.get("n_students"),
        "missing_cards": (short.get("missing_cards") or [])[:20],
        "knowledge_accuracy": {
            k: round(float(v), 3) for k, v in (short.get("knowledge_accuracy") or {}).items()
        },
        "must_teach": short.get("must_teach") or [],
        "hard_items": (short.get("hard_items") or [])[:12],
        "score_bands": short.get("score_bands") or {},
        "watch_candidates": (short.get("watch_candidates") or [])[:8],
        "wrong_counts": short.get("wrong_counts") or {},
        "pending_note": short.get("pending_note"),
        "continuous_weak": (longp.get("continuous_weak") or [])[:8],
    }
    review = await complete_json(
        "根据下列班级统计写讲评要点，不要编造数字：\n" + json.dumps(facts, ensure_ascii=False),
        system=CLASS_REVIEW_SYSTEM,
        temperature=0.3,
        require=True,
    )
    comment = (review.get("comment") or review.get("headline") or "").strip()
    if not comment:
        raise LLMError("大模型未返回学情讲评，已中止。")
    short["headline"] = (review.get("headline") or "").strip() or comment.split("。")[0]
    short["llm_review"] = comment
    short["first_teach"] = (review.get("first_teach") or "").strip()
    short["watch_who"] = _watch_lines(review.get("watch_who"))
    short["next_focus"] = (review.get("next_focus") or "").strip()
    short["classroom_moves"] = _str_list(review.get("classroom_moves"))
    short["must_teach_why"] = _str_list(review.get("must_teach_why"))
    short["llm_model"] = settings.llm_model


async def _fill_student_coach(short: dict[str, Any], longp: dict[str, Any]) -> None:
    if not short.get("n_results"):
        short["headline"] = "还没有这份作业的作答记录"
        short["llm_review"] = "库里还没有该生的成绩。请先确认扫描已匹配学号。"
        return
    facts = {
        "student_no": short.get("student_no"),
        "total": short.get("total"),
        "max_total": short.get("max_total"),
        "class_avg": short.get("class_avg"),
        "delta": short.get("delta"),
        "rank": short.get("rank"),
        "n_submitted": short.get("n_submitted"),
        "wrong_book": [
            {
                "item_id": w.get("item_id"),
                "number": w.get("number"),
                "knowledge_point": w.get("knowledge_point"),
                "score": w.get("score"),
                "max_score": w.get("max_score"),
                "stem": _brief_stem(w.get("stem")),
            }
            for w in (short.get("wrong_book") or [])[:12]
        ],
        "scores": [
            {
                "item_id": s.get("item_id"),
                "number": s.get("number"),
                "kind": s.get("kind"),
                "score": s.get("score"),
                "max_score": s.get("max_score"),
                "is_correct": s.get("is_correct"),
                "pending": s.get("pending"),
                "knowledge_point": s.get("knowledge_point"),
            }
            for s in (short.get("scores") or [])[:20]
        ],
        "kp_vs_class": short.get("kp_vs_class") or {},
        "mastery": longp.get("mastery") or {},
        "pending_note": short.get("pending_note"),
    }
    review = await complete_json(
        "根据下列学生学情写个人辅导建议，不要编造分数：\n" + json.dumps(facts, ensure_ascii=False),
        system=STUDENT_COACH_SYSTEM,
        temperature=0.3,
        require=True,
    )
    comment = (review.get("comment") or review.get("headline") or "").strip()
    if not comment:
        raise LLMError("大模型未返回个人学情，已中止。")
    short["headline"] = (review.get("headline") or "").strip() or comment.split("。")[0]
    short["llm_review"] = comment
    short["coach"] = {
        "strengths": _str_list(review.get("strengths")),
        "needs": _str_list(review.get("needs")),
        "next_steps": _str_list(review.get("next_steps")),
    }
    short["llm_model"] = settings.llm_model


def _str_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    out: list[str] = []
    for x in v:
        if isinstance(x, dict):
            t = "：".join(str(x.get(k) or "") for k in ("student_no", "why", "text") if x.get(k))
            if t:
                out.append(t)
        else:
            s = str(x).strip()
            if s:
                out.append(s)
    return out


def _watch_lines(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    out: list[str] = []
    for x in v:
        if isinstance(x, dict):
            no = str(x.get("student_no") or x.get("who") or "").strip()
            why = str(x.get("why") or x.get("reason") or "").strip()
            if no and why:
                out.append(f"{no}：{why}")
            elif no or why:
                out.append(no or why)
        else:
            s = str(x).strip()
            if s:
                out.append(s)
    return out


def _brief_stem(text: Any, n: int = 40) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


_BLANK_KP = {"", "未标注", "未指定知识点", "none", "null", "n/a"}


def _has_real_kp(it: dict[str, Any] | None) -> bool:
    v = str((it or {}).get("knowledge_point") or "").strip()
    return bool(v) and v.lower() not in _BLANK_KP


def _kp_of(it: dict[str, Any] | None) -> str:
    if _has_real_kp(it):
        return str(it.get("knowledge_point")).strip()
    n = (it or {}).get("number") or (it or {}).get("item_id") or "?"
    return f"第{n}题"


def _stem_key(stem: Any) -> str:
    return " ".join(str(stem or "").split())[:48]


async def _ensure_item_knowledge_points(homework_id: str | None) -> None:
    if not homework_id:
        return
    items = mysql.list_items(homework_id)
    missing = [it for it in items if not _has_real_kp(it)]
    if not missing:
        return
    hw = mysql.get_assignment(homework_id) or {}
    hints = hw.get("knowledge_points") or []
    if isinstance(hints, str):
        hints = [hints]
    if len(hints) == len(items) and all(str(x).strip() for x in hints):
        for it, kp in zip(items, hints):
            if not _has_real_kp(it):
                mysql.update_item_fields(homework_id, it["item_id"], knowledge_point=str(kp).strip())
        return
    others = mysql.fetch_all(
        """
        SELECT stem, knowledge_point FROM items
        WHERE knowledge_point IS NOT NULL AND TRIM(knowledge_point) <> ''
          AND homework_id <> :hw
        """,
        hw=homework_id,
    )
    idx = {_stem_key(r["stem"]): r["knowledge_point"] for r in others if _has_real_kp(r)}
    still = []
    for it in missing:
        kp = idx.get(_stem_key(it.get("stem")))
        if kp:
            mysql.update_item_fields(homework_id, it["item_id"], knowledge_point=str(kp).strip())
        else:
            still.append(it)
    if not still:
        return
    payload = {
        "subject": hw.get("subject"),
        "title": hw.get("name"),
        "hints": [str(x) for x in hints if str(x).strip()][:12],
        "items": [
            {
                "item_id": it["item_id"],
                "number": it.get("number"),
                "kind": it.get("kind"),
                "stem": _brief_stem(it.get("stem"), 80),
            }
            for it in still
        ],
    }
    data = await complete_json(
        "为下列题目补知识点短标签（4～12字），紧扣题干，禁止输出未标注：\n"
        + json.dumps(payload, ensure_ascii=False),
        system=(
            "你是高中教师。只输出 JSON {\"points\":{item_id:知识点}}。"
            "每个 item_id 一个短标签。禁止未标注、禁止空字符串。"
        ),
        temperature=0.2,
        require=True,
    )
    points = data.get("points") if isinstance(data.get("points"), dict) else data
    for it in still:
        kp = str((points or {}).get(it["item_id"]) or "").strip()
        if kp and kp.lower() not in _BLANK_KP:
            mysql.update_item_fields(homework_id, it["item_id"], knowledge_point=kp)


def _build_class_short(class_id: str, homework_id: str | None) -> dict[str, Any]:
    students = mysql.list_class_students(class_id)
    if not homework_id:
        return {
            "knowledge_accuracy": {},
            "must_teach": [],
            "score_distribution": [],
            "missing_cards": [s["student_no"] for s in students],
            "pending_note": None,
            "window": "short",
            "scope": "class",
        }
    items = mysql.list_items(homework_id)
    results = mysql.list_item_results(homework_id)
    pending_any = any(_is_pending(r) for r in results)
    by_item: dict[str, list] = {}
    per_stu: dict[str, float] = {}
    for r in results:
        by_item.setdefault(r["item_id"], []).append(r)
        if r.get("score") is not None and not _is_pending(r):
            per_stu[r["student_id"]] = per_stu.get(r["student_id"], 0) + float(r["score"])
    scores = list(per_stu.values())
    kp_stats: dict[str, list[float]] = {}
    item_stats: list[dict[str, Any]] = []
    item_accuracy: dict[str, float] = {}
    for it in items:
        kp = _kp_of(it)
        rows = [
            x
            for x in by_item.get(it["item_id"], [])
            if x.get("is_correct") is not None and not _is_pending(x)
        ]
        n_wrong = sum(1 for x in rows if x["is_correct"] == 0)
        acc = (sum(1 for x in rows if x["is_correct"] == 1) / len(rows)) if rows else None
        if rows:
            kp_stats.setdefault(kp, []).append(acc or 0)
        max_s = float(it.get("score") or 0)
        scored = [float(x["score"]) for x in by_item.get(it["item_id"], []) if x.get("score") is not None and not _is_pending(x)]
        avg_s = (sum(scored) / len(scored)) if scored else None
        label = f"第{it.get('number') or it['item_id']}题"
        if acc is not None:
            item_accuracy[label] = acc
        item_stats.append(
            {
                "item_id": it["item_id"],
                "number": it.get("number"),
                "label": label,
                "kind": it.get("kind"),
                "knowledge_point": kp,
                "stem": _brief_stem(it.get("stem")),
                "n": len(rows),
                "n_wrong": n_wrong,
                "accuracy": acc,
                "max_score": max_s,
                "avg_score": avg_s,
            }
        )
    kp_acc = {
        kp: sum(arr) / len(arr)
        for kp, arr in kp_stats.items()
        if str(kp).strip() not in _BLANK_KP
    }
    must = [kp for kp, v in kp_acc.items() if v < 0.6]
    got_students = {r["student_id"] for r in results if r.get("student_id")}
    missing = [s["student_no"] for s in students if s["student_id"] not in got_students]
    avg = (sum(scores) / len(scores)) if scores else 0
    max_total = sum(float(it.get("score") or 0) for it in items)
    hard_items = [
        it
        for it in item_stats
        if (it.get("accuracy") is not None and it["accuracy"] < 0.6)
        or (
            it.get("avg_score") is not None
            and it.get("max_score")
            and it["avg_score"] < 0.6 * it["max_score"]
        )
    ]
    hard_items.sort(key=lambda x: (x.get("accuracy") if x.get("accuracy") is not None else 1.0, -(x.get("n_wrong") or 0)))
    if not must:
        must = [it["label"] for it in hard_items[:6] if it.get("label")]
    id_to_no = {s["student_id"]: s["student_no"] for s in students}
    ranked = sorted(per_stu.items(), key=lambda kv: kv[1])
    cutoff = max_total * 0.6 if max_total else None
    watch: list[dict[str, Any]] = []
    seen: set[str] = set()
    n_sub = len(per_stu)
    bottom_n = max(1, (n_sub + 4) // 5) if n_sub else 0
    for sid, sc in ranked[:bottom_n]:
        no = id_to_no.get(sid, sid)
        if no in seen:
            continue
        why = f"本卷 {round(sc, 1)}" + (f"/{round(max_total, 1)}" if max_total else "")
        if cutoff is not None and sc < cutoff:
            why += "，未到六成"
        watch.append({"student_no": no, "score": sc, "why": why})
        seen.add(no)
    wrong_books = _wrong_books(students, items, results)
    wrong_counts = {no: len(book) for no, book in wrong_books.items() if book}
    for no, n_w in sorted(wrong_counts.items(), key=lambda kv: -kv[1])[:5]:
        if no in seen:
            continue
        watch.append({"student_no": no, "why": f"错题 {n_w} 道"})
        seen.add(no)
        if len(watch) >= 8:
            break
    bands = _score_bands(scores, max_total)
    return {
        "knowledge_accuracy": kp_acc,
        "must_teach": must,
        "score_distribution": scores,
        "score_bands": bands,
        "missing_cards": missing,
        "average": avg,
        "max_total": max_total,
        "n_submitted": n_sub,
        "pending_note": "含待确认" if pending_any else None,
        "window": "short",
        "scope": "class",
        "homework_id": homework_id,
        "n_students": len(students),
        "wrong_books": wrong_books,
        "wrong_counts": wrong_counts,
        "item_stats": item_stats,
        "item_accuracy": item_accuracy,
        "hard_items": hard_items[:12],
        "watch_candidates": watch[:8],
        "item_grid": _item_grid(students, items, results),
    }


def _item_grid(students, items, results) -> list[dict[str, Any]]:
    by = {(r.get("student_id"), r.get("item_id")): r for r in results}
    cols = [(it["item_id"], f"第{it.get('number') or it['item_id']}题") for it in items]
    grid: list[dict[str, Any]] = []
    for s in students:
        row: dict[str, Any] = {"学号": s.get("student_no")}
        for iid, lab in cols:
            r = by.get((s.get("student_id"), iid))
            if not r:
                row[lab] = "缺"
            elif _is_pending(r):
                row[lab] = "待"
            elif r.get("is_correct") == 1:
                row[lab] = "对"
            elif r.get("is_correct") == 0:
                row[lab] = "错"
            else:
                row[lab] = "—"
        grid.append(row)
    return grid


def _score_bands(scores: list[float], max_total: float) -> dict[str, int]:
    if not scores:
        return {}
    if not max_total:
        return {"已交卡": len(scores)}
    high = mid = low = 0
    for s in scores:
        ratio = s / max_total
        if ratio >= 0.8:
            high += 1
        elif ratio >= 0.6:
            mid += 1
        else:
            low += 1
    return {"八成以上": high, "六到八成": mid, "未到六成": low}


def _wrong_books(students, items, results) -> dict[str, list]:
    item_map = {i["item_id"]: i for i in items}
    out: dict[str, list] = {}
    for s in students:
        book = []
        for r in results:
            if r["student_id"] != s["student_id"]:
                continue
            if r.get("is_correct") == 0:
                it = item_map.get(r["item_id"]) or {}
                book.append(
                    {
                        "item_id": r["item_id"],
                        "number": it.get("number"),
                        "stem": it.get("stem"),
                        "knowledge_point": it.get("knowledge_point"),
                    }
                )
        out[s["student_no"]] = book
    return out


def _build_class_long(class_id: str) -> dict[str, Any]:
    from zypg.agents.insight_term import build_class_long

    return build_class_long(class_id)


def _build_student_short(class_id: str, homework_id: str | None, student_id: str) -> dict[str, Any]:
    stu = mysql.student_by_id(student_id)
    if not homework_id:
        return {"scope": "student", "window": "short", "wrong_book": [], "scores": [], "results": []}
    items = mysql.list_items(homework_id)
    item_map = {i["item_id"]: i for i in items}
    results = mysql.list_item_results(homework_id, student_id)
    all_results = mysql.list_item_results(homework_id)
    pending = any(_is_pending(r) for r in results)
    wrong = []
    scores = []
    total = 0.0
    has_score = False
    stu_kp: dict[str, list[int]] = {}
    for r in results:
        it = item_map.get(r["item_id"]) or {}
        max_s = float(it.get("score") or 0)
        sc = r.get("score")
        if sc is not None and not _is_pending(r):
            total += float(sc)
            has_score = True
        kp = _kp_of(it)
        if r.get("is_correct") is not None and not _is_pending(r):
            stu_kp.setdefault(kp, []).append(1 if r["is_correct"] == 1 else 0)
        if _is_pending(r):
            status = "待确认"
        elif r.get("is_correct") == 1:
            status = "对"
        elif r.get("is_correct") == 0:
            status = "错"
        else:
            status = "—"
        scores.append(
            {
                "item_id": r["item_id"],
                "number": it.get("number"),
                "kind": it.get("kind"),
                "stem": _brief_stem(it.get("stem")),
                "knowledge_point": kp,
                "score": sc,
                "max_score": max_s,
                "pending": _is_pending(r),
                "is_correct": r.get("is_correct"),
                "source": r.get("source"),
                "status": status,
            }
        )
        wrong_flag = r.get("is_correct") == 0
        if not wrong_flag and sc is not None and max_s > 0 and float(sc) < 0.6 * max_s:
            wrong_flag = True
        if wrong_flag:
            wrong.append(
                {
                    "item_id": r["item_id"],
                    "number": it.get("number"),
                    "stem": it.get("stem"),
                    "knowledge_point": kp,
                    "score": sc,
                    "max_score": max_s,
                    "pending": _is_pending(r),
                }
            )
    max_total = sum(float(it.get("score") or 0) for it in items)
    per_stu: dict[str, float] = {}
    class_kp: dict[str, list[int]] = {}
    for r in all_results:
        if r.get("score") is not None and not _is_pending(r) and r.get("student_id"):
            per_stu[r["student_id"]] = per_stu.get(r["student_id"], 0) + float(r["score"])
        it = item_map.get(r["item_id"]) or {}
        kp = _kp_of(it)
        if r.get("is_correct") is not None and not _is_pending(r):
            class_kp.setdefault(kp, []).append(1 if r["is_correct"] == 1 else 0)
    class_avg = (sum(per_stu.values()) / len(per_stu)) if per_stu else None
    delta = (total - class_avg) if has_score and class_avg is not None else None
    rank = None
    if has_score and per_stu:
        ordered = sorted(per_stu.values(), reverse=True)
        rank = ordered.index(per_stu.get(student_id, total)) + 1 if student_id in per_stu else None
    kp_vs = {}
    for kp, bits in stu_kp.items():
        mine = sum(bits) / len(bits) if bits else None
        pool = class_kp.get(kp) or []
        cls = sum(pool) / len(pool) if pool else None
        kp_vs[kp] = {
            "student": round(mine, 3) if mine is not None else None,
            "class": round(cls, 3) if cls is not None else None,
        }
    return {
        "scope": "student",
        "window": "short",
        "student_no": stu["student_no"] if stu else student_id,
        "wrong_book": wrong,
        "results": results,
        "scores": scores,
        "n_results": len(results),
        "pending_note": "含待确认" if pending else None,
        "homework_id": homework_id,
        "class_id": class_id,
        "total": total if has_score else None,
        "max_total": max_total,
        "class_avg": class_avg,
        "delta": delta,
        "rank": rank,
        "n_submitted": len(per_stu),
        "kp_vs_class": kp_vs,
    }


def _build_student_long(class_id: str, student_id: str) -> dict[str, Any]:
    from zypg.agents.insight_term import build_student_long

    return build_student_long(class_id, student_id)


def _is_pending(row: dict[str, Any]) -> bool:
    v = row.get("pending")
    if v in (None, "", False):
        return False
    try:
        return int(v) != 0
    except (TypeError, ValueError):
        return bool(v)
