from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from zypg.config import ROOT
from zypg.models import ROSTER_REQUIRED
from zypg.orchestrator.engine import cancel_task
from zypg.roster.service import (
    append_roster,
    export_roster_csv,
    has_roster,
    preview_roster,
    replace_roster,
)
from zypg.storage import mysql
from zypg.storage.files import abspath, assignment_rel_file, file_root, homework_dir, paper_docx_url, relpath
from zypg.workspace import get_or_create_conversation, workspace_state

router = APIRouter()


class GradeRunBody(BaseModel):
    scan_dir: str | None = None
    scan_paths: list[str] | None = None


class ItemPatch(BaseModel):
    answer: str | None = None
    rubric: list[str] | str | None = None
    stem: str | None = None
    knowledge_point: str | None = None
    score: float | None = None


class ReviewBody(BaseModel):
    action: str
    score: float | None = None
    student_id: str | None = None


class LessonSave(BaseModel):
    outline: list[str] | None = None
    plan: list[str] | None = None
    notes: str | None = None


class HomeworkCreate(BaseModel):
    class_id: str
    name: str | None = None
    subject: str | None = None


class HomeworkRename(BaseModel):
    name: str


class MessageEdit(BaseModel):
    text: str


class LoginBody(BaseModel):
    username: str
    password: str
    subject: str | None = None


class TeacherContext(BaseModel):
    last_class_id: str | None = None
    last_homework_id: str | None = None
    last_page: str | None = None
    subject: str | None = None


def _need_class(class_id: str | None) -> str:
    if not class_id:
        raise HTTPException(400, "缺少 class_id")
    return class_id


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    raw = authorization.strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _need_teacher(authorization: str | None) -> dict[str, Any]:
    from zypg.auth import teacher_from_token

    row = teacher_from_token(_bearer(authorization))
    if not row:
        raise HTTPException(401, "请先登录")
    return row


@router.post("/auth/login")
def auth_login(body: LoginBody) -> dict[str, Any]:
    from zypg.auth import login, seed_default_teacher

    seed_default_teacher()
    try:
        out = login(body.username, body.password, body.subject)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not out:
        raise HTTPException(401, "账号或密码不对")
    return {"ok": True, **out}


@router.post("/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    from zypg.auth import logout

    logout(_bearer(authorization))
    return {"ok": True}


@router.get("/auth/me")
def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    teacher = _need_teacher(authorization)
    return {"ok": True, "teacher": teacher}


@router.patch("/auth/me")
def auth_patch_me(body: TeacherContext, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    from zypg.auth import bind_subject, save_context, teacher_from_token

    teacher = teacher_from_token(_bearer(authorization))
    if not teacher:
        raise HTTPException(401, "请先登录")
    if body.subject:
        try:
            bind_subject(teacher["teacher_id"], body.subject)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
    if body.last_class_id is not None or body.last_homework_id is not None or body.last_page is not None:
        save_context(teacher["teacher_id"], body.last_class_id, body.last_homework_id, body.last_page)
    return {"ok": True, "teacher": teacher_from_token(_bearer(authorization))}


@router.get("/ui/state")
def ui_state(
    class_id: str | None = None,
    homework_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    from zypg.auth import teacher_from_token

    teacher = teacher_from_token(_bearer(authorization))
    return workspace_state(class_id, homework_id, teacher_id=(teacher or {}).get("teacher_id"))


@router.post("/ui/homework")
def ui_homework_create(body: HomeworkCreate, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    import uuid

    from zypg.auth import teacher_from_token
    from zypg.subject import teacher_subject

    cid = _need_class(body.class_id)
    if not mysql.get_class(cid):
        raise HTTPException(404, "班级不存在")
    teacher = teacher_from_token(_bearer(authorization))
    tid = (teacher or {}).get("teacher_id")
    name = (body.name or "").strip() or "新对话"
    subject = body.subject or teacher_subject(tid) or (mysql.get_class(cid) or {}).get("subject")
    hid = uuid.uuid4().hex
    mysql.insert_assignment(hid, cid, name, subject, [], None, {})
    mysql.insert_conversation(uuid.uuid4().hex, hid, cid)
    return {"ok": True, "homework_id": hid, "name": name, "class_id": cid}


@router.patch("/ui/homework")
def ui_homework_rename(body: HomeworkRename, homework_id: str = Query(...)) -> dict[str, Any]:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "名称不能空")
    if not mysql.get_assignment(homework_id):
        raise HTTPException(404, "作业不存在")
    mysql.update_assignment_name(homework_id, name)
    return {"ok": True, "homework_id": homework_id, "name": name}


@router.delete("/ui/homework")
def ui_homework_delete(homework_id: str = Query(...)) -> dict[str, Any]:
    if not mysql.get_assignment(homework_id):
        raise HTTPException(404, "作业不存在")
    mysql.delete_homework(homework_id)
    return {"ok": True}


@router.patch("/ui/messages/{message_id}")
def ui_message_edit(message_id: int, body: MessageEdit) -> dict[str, Any]:
    row = mysql.get_message(message_id)
    if not row:
        raise HTTPException(404, "消息不存在")
    text = body.text if body.text is not None else ""
    content = row.get("content") or ""
    if isinstance(content, str) and content[:1] == "{":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("kind"):
            parsed["text"] = text
            content = json.dumps(parsed, ensure_ascii=False)
        else:
            content = text
    else:
        content = text
    mysql.update_message_content(message_id, content)
    return {"ok": True, "id": message_id, "text": text}


@router.delete("/ui/messages/{message_id}")
def ui_message_delete(message_id: int) -> dict[str, Any]:
    if not mysql.get_message(message_id):
        raise HTTPException(404, "消息不存在")
    mysql.delete_message(message_id)
    return {"ok": True}


@router.get("/ui/messages")
def ui_messages(class_id: str | None = None, homework_id: str | None = None) -> dict[str, Any]:
    conv = get_or_create_conversation(class_id, homework_id)
    rows = mysql.list_messages(conv, limit=200)
    messages = []
    for row in rows:
        content = row.get("content") or ""
        parsed = None
        if isinstance(content, str) and content[:1] == "{":
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, dict) and parsed.get("kind"):
            messages.append(
                {
                    "role": row["role"],
                    "text": parsed.get("text") or "",
                    "kind": parsed.get("kind"),
                    "intent": parsed.get("intent"),
                    "actions": parsed.get("actions") or [],
                    "ok": parsed.get("ok"),
                }
            )
        else:
            messages.append({"role": row["role"], "text": content, "kind": "text"})
        messages[-1]["id"] = row.get("id")
    return {"conversation_id": conv, "messages": messages}


@router.get("/ui/roster")
def ui_roster(class_id: str | None = None, q: str | None = None) -> dict[str, Any]:
    cid = _need_class(class_id)
    students = mysql.list_class_students(cid)
    if q:
        needle = q.strip().lower()
        students = [
            s
            for s in students
            if needle in str(s.get("student_no") or "").lower() or needle in str(s.get("name") or "").lower()
        ]
    return {"students": students, "class": mysql.get_class(cid)}


@router.post("/ui/roster/preview")
async def ui_roster_preview(file: UploadFile = File(...)) -> dict[str, Any]:
    dest = file_root() / "rosters"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / (file.filename or "preview.csv")
    path.write_bytes(await file.read())
    try:
        return {**preview_roster(path), "path": str(path), "rel": relpath(path)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/ui/roster/append")
async def ui_roster_append(class_id: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    dest = file_root() / "rosters"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / (file.filename or "append.csv")
    path.write_bytes(await file.read())
    try:
        return append_roster(class_id, path)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/ui/roster/replace")
async def ui_roster_replace(
    class_id: str = Form(...),
    confirm: str = Form("0"),
    class_name: str | None = Form(None),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if confirm not in {"1", "true", "yes"}:
        raise HTTPException(400, "整班替换需要二次确认")
    dest = file_root() / "rosters"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / (file.filename or "replace.csv")
    path.write_bytes(await file.read())
    try:
        return replace_roster(class_id, path, class_name=class_name)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/ui/roster/export")
def ui_roster_export(class_id: str = Query(...)) -> FileResponse:
    path = export_roster_csv(class_id)
    return FileResponse(path, filename="roster.csv", media_type="text/csv")


@router.get("/ui/paper")
def ui_paper(homework_id: str | None = None, class_id: str | None = None) -> dict[str, Any]:
    if not homework_id:
        return {"homework": None, "items": [], "gradeable": None}
    hw = mysql.get_assignment(homework_id)
    if not hw:
        raise HTTPException(404, "作业不存在")
    items = mysql.list_items(homework_id)
    extra = hw.get("extra") or {}
    if not isinstance(extra, dict):
        extra = {}
    gradeable = extra.get("gradeable")
    if gradeable is None:
        gradeable = True
        for it in items:
            if it["kind"] == "objective" and not (it.get("answer_key") or {}).get("letter"):
                gradeable = False
            if it["kind"] == "subjective" and not it.get("rubric"):
                gradeable = False
    layout = extra.get("layout") or {}
    docx = assignment_rel_file(hw, ".docx")
    md = assignment_rel_file(hw, ".md")
    download_url = paper_docx_url(homework_id) if docx else None
    return {
        "homework": hw,
        "items": items,
        "gradeable": gradeable,
        "layout": layout,
        "docx": docx,
        "md": md,
        "download_url": download_url,
        "mock": layout.get("mock"),
    }


@router.patch("/ui/items/{item_id}")
def ui_patch_item(item_id: str, body: ItemPatch, homework_id: str = Query(...)) -> dict[str, Any]:
    row = next((x for x in mysql.list_items(homework_id) if x["item_id"] == item_id), None)
    if not row:
        raise HTTPException(404, "题目不存在")
    answer_key = row.get("answer_key")
    if body.answer is not None:
        if row["kind"] == "objective":
            answer_key = {"letter": body.answer.strip().upper()[:1]}
        else:
            answer_key = {"text": body.answer}
    rubric = row.get("rubric")
    if body.rubric is not None:
        rubric = [body.rubric] if isinstance(body.rubric, str) else body.rubric
    mysql.update_item_fields(
        homework_id,
        item_id,
        answer_key=answer_key,
        rubric=rubric,
        stem=body.stem,
        knowledge_point=body.knowledge_point,
        score=body.score,
    )
    extra = (mysql.get_assignment(homework_id) or {}).get("extra") or {}
    if isinstance(extra, dict):
        extra = dict(extra)
        extra["gradeable"] = _gradeable(mysql.list_items(homework_id))
        mysql.execute(
            "UPDATE assignments SET extra = :extra WHERE homework_id = :id",
            extra=json.dumps(extra, ensure_ascii=False),
            id=homework_id,
        )
    return {"ok": True, "item": next(x for x in mysql.list_items(homework_id) if x["item_id"] == item_id)}


def _gradeable(items: list[dict[str, Any]]) -> bool:
    for it in items:
        if it["kind"] == "objective" and not (it.get("answer_key") or {}).get("letter"):
            return False
        if it["kind"] == "subjective" and not it.get("rubric"):
            return False
    return True


@router.get("/ui/cards")
def ui_cards(homework_id: str | None = None, class_id: str | None = None) -> dict[str, Any]:
    if not homework_id:
        return {"template": None, "paths": [], "students": [], "stale": False}
    tmpl = mysql.get_card_template(homework_id)
    students = mysql.list_class_students(class_id) if class_id else []
    paths: list[str] = []
    print_path = None
    geom = (tmpl or {}).get("geometry") or {}
    stale = bool(tmpl) and not geom.get("id_grid")
    if tmpl and tmpl.get("print_path"):
        print_path = tmpl["print_path"]
        folder = abspath(print_path)
        if folder.exists():
            if geom.get("card_paths"):
                paths = list(geom["card_paths"])
            else:
                paths = [relpath(p) for p in sorted(folder.glob("*.png")) if p.name != "_blank.png" and not p.name.startswith("_blank")]
    return {
        "template": tmpl,
        "paths": paths,
        "print_path": print_path,
        "students": students,
        "stale": stale,
    }


@router.post("/ui/cards/generate")
async def ui_cards_generate(
    homework_id: str | None = None,
    class_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _need_teacher(authorization)
    hid = homework_id or ""
    cid = class_id or ""
    if not hid or not cid:
        raise HTTPException(400, "缺少作业或班级")
    if not has_roster(cid):
        raise HTTPException(400, ROSTER_REQUIRED)
    from zypg.models import A2AMessage
    from zypg.protocol.a2a import dispatch_local

    try:
        out = await dispatch_local(
            A2AMessage(skill="generate_cards", payload={"homework_id": hid, "class_id": cid})
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **(out if isinstance(out, dict) else {"result": out})}


@router.get("/ui/cards.zip")
def ui_cards_zip(homework_id: str = Query(...)) -> FileResponse:
    tmpl = mysql.get_card_template(homework_id)
    if not tmpl or not tmpl.get("print_path"):
        raise HTTPException(404, "还没有答题卡")
    folder = abspath(tmpl["print_path"])
    dest = homework_dir(homework_id, "cards") / "cards.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.glob("*.png")):
            zf.write(p, p.name)
    return FileResponse(dest, filename=f"{homework_id}_cards.zip")


@router.post("/ui/grades/run")
async def ui_grades_run(
    body: GradeRunBody,
    homework_id: str | None = None,
    class_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _need_teacher(authorization)
    hid = homework_id or ""
    cid = class_id or ""
    if not hid or not cid:
        raise HTTPException(400, "缺少作业或班级")
    if not has_roster(cid):
        raise HTTPException(400, ROSTER_REQUIRED)
    from zypg.gateway.intent import resolve_scan_source
    from zypg.models import A2AMessage
    from zypg.orchestrator.engine import _materialize_scan_paths
    from zypg.protocol.a2a import dispatch_local

    paths = [str(x) for x in (body.scan_paths or []) if x]
    if body.scan_dir:
        found, err = resolve_scan_source(body.scan_dir)
        if err:
            raise HTTPException(400, err)
        paths.extend(found)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in paths:
        key = str(Path(p).resolve()) if Path(p).exists() else p
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    if not uniq:
        raise HTTPException(400, "没有可批改的 png/jpg。请上传图片，或填写本机文件夹完整路径。")
    materialized = _materialize_scan_paths(hid, uniq)
    if not materialized:
        raise HTTPException(400, "图片路径无效，网关读不到这些文件。")
    try:
        out = await dispatch_local(
            A2AMessage(
                skill="grade_scans",
                payload={"homework_id": hid, "class_id": cid, "scan_paths": materialized},
            )
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **(out if isinstance(out, dict) else {"result": out})}


@router.get("/ui/grades")
def ui_grades(homework_id: str | None = None, class_id: str | None = None) -> dict[str, Any]:
    if not homework_id or not class_id:
        return {"rows": [], "unmatched": [], "scanned": 0, "expected": 0}
    students = mysql.list_class_students(class_id)
    items = mysql.list_items(homework_id)
    results = mysql.list_item_results(homework_id)
    scans = mysql.list_scans(homework_id)
    reviews = mysql.list_open_reviews(homework_id=homework_id)
    pending_ids = {(r.get("student_id"), r.get("item_id")) for r in reviews}
    by_stu: dict[str, list] = {}
    for r in results:
        by_stu.setdefault(r["student_id"], []).append(r)
    rows = []
    for s in students:
        rs = by_stu.get(s["student_id"]) or []
        obj = [x for x in rs if x.get("source") == "omr"]
        sub = [x for x in rs if x.get("source") in {"ocr_llm", "teacher"}]
        obj_score = sum(float(x["score"]) for x in obj if x.get("score") is not None and not x.get("pending"))
        sub_score = sum(float(x["score"]) for x in sub if x.get("score") is not None)
        pending = any((s["student_id"], it["item_id"]) in pending_ids for it in items) or any(
            x.get("pending") for x in rs
        )
        scan = next((sc for sc in scans if sc.get("student_id") == s["student_id"]), None)
        rows.append(
            {
                "student_id": s["student_id"],
                "student_no": s["student_no"],
                "name": s["name"],
                "objective_score": obj_score,
                "subjective_suggested": sub_score,
                "pending": pending,
                "missing": not rs,
                "scan_path": (scan or {}).get("file_path"),
                "results": rs,
            }
        )
    unmatched = [sc for sc in scans if sc.get("status") in {"unmatched", "bad_id"}]
    return {
        "rows": rows,
        "unmatched": unmatched,
        "scanned": len(scans),
        "graded": len([s for s in scans if s.get("status") == "graded"]),
        "expected": len(students),
        "items": items,
    }


@router.get("/ui/reviews")
def ui_reviews(homework_id: str | None = None, class_id: str | None = None) -> dict[str, Any]:
    items = mysql.list_open_reviews(homework_id=homework_id, class_id=class_id)
    out = []
    for row in items:
        stu = mysql.student_by_id(row["student_id"]) if row.get("student_id") else None
        crop = None
        if row.get("student_id") and row.get("item_id") and row.get("homework_id"):
            p = homework_dir(row["homework_id"], "crops") / f"{row['student_id']}_{row['item_id']}.png"
            if p.exists():
                crop = relpath(p)
        out.append({**row, "student_no": (stu or {}).get("student_no"), "name": (stu or {}).get("name"), "crop": crop})
    missing = []
    if homework_id and class_id:
        graded_ids = {r["student_id"] for r in mysql.list_item_results(homework_id) if r.get("student_id")}
        missing = [s for s in mysql.list_class_students(class_id) if s["student_id"] not in graded_ids]
    return {"items": out, "unsubmitted": missing}


@router.post("/ui/reviews/{review_id}")
async def ui_review_act(review_id: int, body: ReviewBody, class_id: str | None = None) -> dict[str, Any]:
    from zypg.models import A2AMessage
    from zypg.protocol.a2a import dispatch_local

    payload: dict[str, Any] = {"action": body.action, "review_id": review_id, "class_id": class_id}
    if body.score is not None:
        payload["score"] = body.score
    if body.student_id:
        payload["student_id"] = body.student_id
    return await dispatch_local(A2AMessage(skill="review_queue", payload=payload))


@router.get("/ui/insight")
def ui_insight(class_id: str | None = None, homework_id: str | None = None) -> dict[str, Any]:
    cid = _need_class(class_id)
    if not has_roster(cid):
        raise HTTPException(403, ROSTER_REQUIRED)
    short = mysql.latest_class_snapshot(cid, "short")
    payload = (short or {}).get("payload") or {}
    from zypg.agents.insight import LLM_KEEP, _build_class_long, _build_class_short

    long_live = _build_class_long(cid)
    charts = {}
    students = mysql.list_class_students(cid)
    n_results = 0
    if homework_id:
        n_results = len(mysql.list_item_results(homework_id))
        live = _build_class_short(cid, homework_id)
        kept = {k: payload[k] for k in LLM_KEEP if payload.get(k) not in (None, "", [], {})}
        payload = {**payload, **live, **kept}
        payload.pop("charts", None)
    return {
        "short": payload,
        "long": long_live,
        "charts": charts,
        "students": students,
        "has_data": bool(
            payload.get("knowledge_accuracy")
            or payload.get("score_distribution")
            or payload.get("wrong_books")
            or n_results
        ),
        "pending_note": payload.get("pending_note"),
    }


@router.get("/ui/insight/student")
def ui_insight_student(
    class_id: str = Query(...),
    student_id: str = Query(...),
    homework_id: str | None = None,
) -> dict[str, Any]:
    from zypg.agents.insight import LLM_KEEP, _build_student_long, _build_student_short

    live = _build_student_short(class_id, homework_id, student_id)
    snap = mysql.latest_student_snapshot(class_id, student_id, "short")
    saved = (snap or {}).get("payload") or {}
    kept = {k: saved[k] for k in LLM_KEEP if saved.get(k) not in (None, "", [], {})}
    live = {**live, **kept}
    events = mysql.list_mastery(class_id, student_id)
    return {
        "short": live,
        "long": _build_student_long(class_id, student_id),
        "events": events,
        "student": mysql.student_by_id(student_id),
    }


@router.get("/ui/lesson")
def ui_lesson(class_id: str | None = None, homework_id: str | None = None) -> dict[str, Any]:
    cid = _need_class(class_id)
    short = mysql.latest_class_snapshot(cid, "short")
    from zypg.agents.insight import _build_class_long

    payload = (short or {}).get("payload") or {}
    long_payload = _build_class_long(cid)
    notes = _lesson_notes(cid)
    consec = long_payload.get("consecutive_weak") or []
    watch_long = []
    for x in consec:
        if isinstance(x, dict):
            watch_long.append(f"{x.get('student_no')}（{x.get('knowledge_point')}）")
        else:
            watch_long.append(str(x))
    return {
        "must_teach": payload.get("must_teach") or [],
        "llm_review": payload.get("llm_review"),
        "headline": payload.get("headline"),
        "first_teach": payload.get("first_teach"),
        "classroom_moves": payload.get("classroom_moves") or [],
        "watch_who": payload.get("watch_who") or [],
        "outline": notes.get("outline") or [],
        "plan": notes.get("plan") or [],
        "notes": notes.get("notes") or "",
        "continuous_weak": long_payload.get("continuous_weak") or [],
        "consecutive_weak": consec,
        "term_weak_top3": long_payload.get("term_weak_top3") or [],
        "n_commits": long_payload.get("n_commits") or 0,
        "can_trend": bool(long_payload.get("can_trend")),
        "watch_long": watch_long,
        "has_pack": bool(short),
        "pending_note": payload.get("pending_note"),
        "suggested_homework_id": notes.get("suggested_homework_id"),
    }


@router.post("/ui/lesson/save")
def ui_lesson_save(body: LessonSave, class_id: str = Query(...)) -> dict[str, Any]:
    notes = _lesson_notes(class_id)
    if body.outline is not None:
        notes["outline"] = body.outline
    if body.plan is not None:
        notes["plan"] = body.plan
    if body.notes is not None:
        notes["notes"] = body.notes
    _write_lesson_notes(class_id, notes)
    return {"ok": True, **notes}


@router.post("/ui/tasks/{task_id}/cancel")
async def ui_cancel(task_id: str) -> dict[str, Any]:
    try:
        from zypg.gateway.app import _JOBS

        for job in list(_JOBS.values()):
            job.cancel()
    except Exception:
        pass
    return await cancel_task(task_id)


@router.get("/ui/paper.docx")
def ui_paper_docx(homework_id: str = Query(...)) -> FileResponse:
    hw = mysql.get_assignment(homework_id)
    if not hw:
        raise HTTPException(404, "作业不存在")
    stored = assignment_rel_file(hw, ".docx")
    if not stored:
        raise HTTPException(404, "DOCX 不存在")
    p = abspath(stored)
    return FileResponse(
        p,
        filename=p.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/ui/paper.md")
def ui_paper_md(homework_id: str = Query(...)) -> FileResponse:
    hw = mysql.get_assignment(homework_id)
    if not hw:
        raise HTTPException(404, "作业不存在")
    stored = assignment_rel_file(hw, ".md")
    if not stored:
        raise HTTPException(404, "Markdown 不存在")
    p = abspath(stored)
    return FileResponse(p, filename=p.name, media_type="text/markdown")


@router.get("/ui/file")
def ui_file(path: str = Query(...)) -> FileResponse:
    p = abspath(path)
    root = file_root().resolve()
    try:
        p.resolve().relative_to(root)
    except ValueError:
        try:
            p.resolve().relative_to(ROOT.resolve())
        except ValueError as exc:
            raise HTTPException(403, "路径不允许") from exc
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(p)


def _lesson_notes(class_id: str) -> dict[str, Any]:
    path = file_root() / "lessons" / f"{class_id}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_lesson_notes(class_id: str, notes: dict[str, Any]) -> None:
    dest = file_root() / "lessons"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{class_id}.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
