from __future__ import annotations

import json
import uuid
from typing import Any

from zypg.config import settings
from zypg.roster.service import has_roster
from zypg.storage import mysql, redis_store

STAGE_LABELS = {
    "no_roster": "未导入名单",
    "no_paper": "未选题",
    "ready_cards": "已选题待出卡",
    "ready_grade": "已出卡待收回",
    "grading": "批改中",
    "review": "待确认",
    "insight": "已出学情",
}

NAV = [
    ("chat", "对话"),
    ("roster", "名单"),
    ("paper", "试卷"),
    ("cards", "答题卡"),
    ("grade", "批改"),
    ("queue", "确认队列"),
    ("insight", "学情"),
    ("lesson", "备课"),
]

LOCKED_PAGES = {
    "no_roster": {"paper", "cards", "grade", "queue", "insight", "lesson"},
    "no_paper": {"cards", "grade"},
    "ready_cards": {"grade"},
    "grading": {"insight", "lesson"},
}


def derive_stage(
    *,
    has_roster: bool,
    has_homework: bool,
    has_items: bool,
    has_cards: bool,
    n_results: int,
    n_open_reviews: int,
    has_insight: bool,
    grading: bool,
) -> str:
    if not has_roster:
        return "no_roster"
    if grading:
        return "grading"
    if not has_homework or not has_items:
        return "no_paper"
    if not has_cards:
        return "ready_cards"
    if n_results <= 0:
        return "ready_grade"
    if n_open_reviews > 0:
        return "review"
    if has_insight:
        return "insight"
    return "review"


def page_lock(stage: str, page: str) -> str:
    """lock | empty | open — 与规划第 5 节对齐。"""
    if page == "chat":
        return "open"
    if page == "roster":
        return "open"
    if stage == "no_roster" and page != "roster":
        return "lock"
    if stage == "no_paper":
        if page in {"cards", "grade"}:
            return "lock"
        if page in {"queue", "insight", "lesson"}:
            return "empty"
        return "open"
    if stage == "ready_cards":
        if page == "grade":
            return "lock"
        if page in {"queue", "insight", "lesson"}:
            return "empty"
        return "open"
    if stage == "ready_grade":
        if page in {"queue", "insight", "lesson"}:
            return "empty"
        return "open"
    if stage == "grading":
        return "open"
    if stage == "review":
        return "open"
    return "open"


def get_or_create_conversation(class_id: str | None, homework_id: str | None) -> str:
    row = mysql.find_conversation(class_id, homework_id)
    if row:
        return str(row["conversation_id"])
    cid = uuid.uuid4().hex
    mysql.insert_conversation(cid, homework_id, class_id)
    return cid


def workspace_state(class_id: str | None, homework_id: str | None, teacher_id: str | None = None) -> dict[str, Any]:
    if teacher_id:
        mysql.claim_orphan_classes(teacher_id)
    classes = mysql.list_classes(teacher_id)
    if not class_id and classes:
        class_id = classes[0]["class_id"]
    cls = mysql.get_class(class_id) if class_id else None
    students = mysql.list_class_students(class_id) if class_id else []
    roster_ok = has_roster(class_id)
    homeworks = mysql.list_homeworks(class_id) if class_id else []
    if homework_id and class_id:
        hw = mysql.get_assignment(homework_id)
        if not hw or hw.get("class_id") != class_id:
            homework_id = None
    if not homework_id and homeworks:
        homework_id = homeworks[0]["homework_id"]
    hw = mysql.get_assignment(homework_id) if homework_id else None
    items = mysql.list_items(homework_id) if homework_id else []
    tmpl = mysql.get_card_template(homework_id) if homework_id else None
    results = mysql.list_item_results(homework_id) if homework_id else []
    reviews = mysql.list_open_reviews(homework_id=homework_id, class_id=class_id) if class_id else []
    insight = bool(class_id and mysql.has_class_insight(class_id, homework_id))
    working = mysql.list_working_tasks(homework_id=homework_id, class_id=class_id)
    grading = any(t.get("skill") == "grade_scans" for t in working)
    if working:
        tid = working[0].get("task_id")
        extra = redis_store.get_task(tid) if tid else {}
        parsed: dict[str, Any] = {}
        for k, v in (extra or {}).items():
            if isinstance(v, str) and v[:1] in "{[\"":
                try:
                    parsed[k] = json.loads(v)
                    continue
                except Exception:
                    pass
            parsed[k] = v
        for k in ("done", "total"):
            v = parsed.get(k)
            if isinstance(v, str) and v.isdigit():
                parsed[k] = int(v)
        working[0] = {**working[0], **parsed}
    stage = derive_stage(
        has_roster=roster_ok,
        has_homework=bool(hw),
        has_items=bool(items),
        has_cards=bool(tmpl),
        n_results=len(results),
        n_open_reviews=len(reviews),
        has_insight=insight,
        grading=grading,
    )
    conv = get_or_create_conversation(class_id, homework_id)
    locks = {key: page_lock(stage, key) for key, _ in NAV}
    return {
        "class_id": class_id,
        "homework_id": homework_id,
        "conversation_id": conv,
        "class": cls,
        "classes": classes,
        "homeworks": [
            {"homework_id": h["homework_id"], "name": h["name"], "subject": h.get("subject")} for h in homeworks
        ],
        "n_students": len(students),
        "n_items": len(items),
        "has_cards": bool(tmpl),
        "n_results": len(results),
        "queue_count": len(reviews),
        "has_insight": insight,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "locks": locks,
        "active_task": working[0] if working else None,
        "llm_configured": bool(settings.llm_api_key and settings.llm_model),
        "teacher_subject": (mysql.get_teacher(teacher_id) or {}).get("subject") or "" if teacher_id else "",
    }


def actions_from_result(result: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for item in result.get("results") or []:
        skill = item.get("skill")
        r = item.get("result") or {}
        if r.get("ok") is False:
            continue
        if skill == "import_roster":
            actions.append({"label": "去名单页", "page": "roster"})
        elif skill in {"generate_paper", "import_paper", "suggest_next_homework"}:
            actions.append({"label": "在试卷页查看", "page": "paper"})
        elif skill == "generate_cards":
            actions.append({"label": "去预览", "page": "cards"})
        elif skill == "grade_scans":
            if r.get("queued"):
                actions.append({"label": "去确认队列", "page": "queue"})
            else:
                actions.append({"label": "在批改页查看", "page": "grade"})
        elif skill in {"class_insight", "student_insight"}:
            actions.append({"label": "在学情页查看", "page": "insight"})
        elif skill in {"next_focus", "term_plan"}:
            actions.append({"label": "在备课页查看", "page": "lesson"})
        elif skill == "review_queue":
            actions.append({"label": "去确认队列", "page": "queue"})
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for a in actions:
        if a["page"] in seen:
            continue
        seen.add(a["page"])
        out.append(a)
    return out


def intent_label(intent: str | None) -> str:
    return {"chat": "闲聊", "task": "单任务", "pipeline": "闭环"}.get(intent or "", intent or "")
