from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from zypg.config import ROOT
from zypg.gateway.intent import (
    attach_understood,
    collect_scan_images,
    enrich_extra,
    format_task_reply,
    understand_utterance,
)
from zypg.models import A2AMessage, Intent, ROSTER_REQUIRED
from zypg.protocol.a2a import dispatch_local
from zypg.roster.service import has_roster, import_roster
from zypg.storage import mysql, redis_store
from zypg.storage.files import abspath, homework_dir

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]] | None

SAMPLE_ROSTER = ROOT / "samples" / "roster.example.csv"
SAMPLE_PAPER = ROOT / "samples" / "paper.example.md"


async def handle_user_task(
    text: str,
    class_id: str | None,
    homework_id: str | None,
    extra: dict[str, Any] | None = None,
    progress: ProgressCb = None,
) -> dict[str, Any]:
    extra = enrich_extra(text, extra or {})
    understood = await understand_utterance(text, extra)
    extra = attach_understood(extra, understood)
    intent = understood["intent"]
    slots = dict(understood.get("slots") or {})
    skills = extra.get("skills") or understood.get("skills") or []
    if intent == Intent.chat:
        return {"ok": True, "intent": intent.value, "action": "chat"}
    extra_roster = extra.get("path") or extra.get("roster_path")
    skipped_roster = False
    if "import_roster" in skills and has_roster(class_id) and not extra_roster:
        skills = [s for s in skills if s != "import_roster"]
        extra["skills"] = skills
        skipped_roster = True
    if not skills:
        if skipped_roster:
            msg = "这个班已经有名单了，不用再导入。需要出卡或批改请直接说。"
            return {"ok": True, "intent": intent.value, "summary": msg}
        msg = "请点名要调用的 Agent，例如「只出卡」「看看这班学情」「备课提纲」。不会自动按 1→2→3→4 跑。"
        return {"ok": False, "intent": intent.value, "error": msg, "summary": msg}
    allow_without_roster = skills[:1] in (["import_roster"], ["fill_demo_scans"])
    if not allow_without_roster and not has_roster(class_id):
        return {"ok": False, "intent": intent.value, "error": ROSTER_REQUIRED, "summary": ROSTER_REQUIRED}
    payload = {
        "class_id": class_id,
        "homework_id": homework_id,
        "text": text,
        **slots,
        **{k: v for k, v in extra.items() if k not in {"skills", "progress_cb"} and not callable(v)},
    }
    try:
        from zypg.subject import enforce_teacher_subject

        enforce_teacher_subject(skills, payload)
    except ValueError as exc:
        return {"ok": False, "intent": intent.value, "error": str(exc), "summary": str(exc)}
    session: dict[str, Any] = {"class_id": class_id, "homework_id": homework_id}
    _fill_default_paths(payload, skills)
    hid = payload.get("homework_id") or _latest_homework(payload.get("class_id"))
    if hid:
        payload["homework_id"] = hid
        session["homework_id"] = hid
    _merge_scan_paths(payload)
    skills = _maybe_skip_fill_if_scans_exist(skills, payload.get("homework_id"))
    # 学生自己填卡。只有老师明确要求「写好的答题卡」才走大模型代答。
    results = []
    last = None
    for skill in skills:
        if last and isinstance(last, dict):
            if last.get("homework_id"):
                payload["homework_id"] = last.get("homework_id")
                session["homework_id"] = last.get("homework_id")
            if last.get("class_id"):
                payload["class_id"] = last.get("class_id")
                session["class_id"] = last.get("class_id")
        _prepare_skill_payload(skill, payload)
        task_id = uuid.uuid4().hex
        stored_payload = {k: v for k, v in payload.items() if not callable(v)}
        redis_store.set_task(task_id, {"status": "submitted", "skill": skill})
        mysql.upsert_a2a_task(task_id, payload.get("homework_id"), skill, "submitted", stored_payload, None)
        redis_store.set_task(task_id, {"status": "working", "skill": skill})
        mysql.upsert_a2a_task(task_id, payload.get("homework_id"), skill, "working", stored_payload, None)

        async def _progress(ev: dict[str, Any]) -> None:
            redis_store.set_task(
                task_id,
                {
                    "status": "working",
                    "skill": skill,
                    "done": ev.get("done"),
                    "total": ev.get("total"),
                    "message": ev.get("message") or "",
                },
            )
            if progress:
                await progress(ev)

        payload["progress_cb"] = _progress
        from zypg.gateway.intent import AGENT_BY_SKILL

        await _progress(
            {
                "task_id": task_id,
                "skill": skill,
                "agent": AGENT_BY_SKILL.get(skill, skill),
                "status": "working",
                "done": 0,
                "total": max(len(payload.get("scan_paths") or []), 1) if skill == "grade_scans" else 1,
                "message": "已开始",
            }
        )
        try:
            last = await _run_skill(skill, payload)
            payload.pop("progress_cb", None)
            if isinstance(last, dict) and last.get("ok") is False:
                raise RuntimeError(str(last.get("error") or "任务失败"))
            mysql.upsert_a2a_task(task_id, payload.get("homework_id"), skill, "completed", stored_payload, last)
            redis_store.set_task(task_id, {"status": "completed", "skill": skill})
            redis_store.delete_task(task_id)
            results.append({"task_id": task_id, "skill": skill, "result": last})
            if isinstance(last, dict):
                if last.get("class_id"):
                    session["class_id"] = last["class_id"]
                    payload["class_id"] = last["class_id"]
                if last.get("homework_id"):
                    session["homework_id"] = last["homework_id"]
                    payload["homework_id"] = last["homework_id"]
        except Exception as exc:
            payload.pop("progress_cb", None)
            mysql.upsert_a2a_task(
                task_id, payload.get("homework_id"), skill, "failed", stored_payload, {"error": str(exc)}
            )
            redis_store.set_task(task_id, {"status": "failed", "skill": skill})
            redis_store.delete_task(task_id)
            out = {
                "ok": False,
                "intent": intent.value,
                "error": str(exc),
                "results": results,
                **session,
            }
            out["summary"] = format_task_reply(out)
            return out
    out = {"ok": True, "intent": intent.value, "skills": skills, "results": results, **session}
    out["summary"] = format_task_reply(out)
    return out


async def _run_skill(skill: str, payload: dict[str, Any]) -> dict[str, Any]:
    if skill == "import_roster":
        path = payload.get("path") or payload.get("roster_path")
        if not path:
            raise ValueError("请在对话中附上 CSV/XLSX，或说「导入示例名单」")
        return import_roster(
            path,
            class_name=payload.get("class_name") or "未命名班级",
            grade=payload.get("grade"),
            subject=payload.get("subject"),
            class_id=payload.get("class_id"),
            teacher_id=payload.get("teacher_id"),
        )
    if skill == "review_queue" and payload.get("review_action") == "accept_all":
        items = mysql.list_open_reviews(payload.get("homework_id"), payload.get("class_id"))
        done = []
        for row in items:
            done.append(
                await dispatch_local(
                    A2AMessage(
                        skill="review_queue",
                        payload={"action": "accepted", "review_id": row["id"], "class_id": payload.get("class_id")},
                    )
                )
            )
        return {"accepted": len(done), "status": "accepted", "items": []}
    if skill == "fill_demo_scans":
        await _ensure_demo_homework(payload)
    return await dispatch_local(A2AMessage(skill=skill, payload=payload))


async def _ensure_demo_homework(payload: dict[str, Any]) -> None:
    if not has_roster(payload.get("class_id")):
        info = import_roster(
            SAMPLE_ROSTER,
            class_name=payload.get("class_name") or "验收班",
            grade=payload.get("grade") or "高一",
            subject=payload.get("subject") or "数学",
            class_id=payload.get("class_id"),
            teacher_id=payload.get("teacher_id"),
        )
        payload["class_id"] = info["class_id"]
    if not payload.get("homework_id"):
        paper = await dispatch_local(
            A2AMessage(
                skill="import_paper",
                payload={"class_id": payload["class_id"], "path": str(SAMPLE_PAPER)},
            )
        )
        payload["homework_id"] = paper["homework_id"]
    if not mysql.get_card_template(payload["homework_id"]):
        await dispatch_local(
            A2AMessage(
                skill="generate_cards",
                payload={"class_id": payload["class_id"], "homework_id": payload["homework_id"]},
            )
        )


def _fill_default_paths(payload: dict[str, Any], skills: list[str]) -> None:
    if "import_roster" in skills and not payload.get("path") and not payload.get("roster_path"):
        if payload.get("use_sample_roster"):
            payload["path"] = str(SAMPLE_ROSTER)
    if "import_paper" in skills and not payload.get("path") and not payload.get("paper_path"):
        if payload.get("use_sample_paper"):
            payload["path"] = str(SAMPLE_PAPER)
    if payload.get("roster_path") and not payload.get("path") and "import_roster" in skills:
        payload["path"] = payload["roster_path"]
    if payload.get("paper_path") and not payload.get("path") and "import_paper" in skills:
        payload["path"] = payload["paper_path"]


def _prepare_skill_payload(skill: str, payload: dict[str, Any]) -> None:
    if skill == "student_insight" and not payload.get("student_id"):
        no = payload.get("student_no")
        if no:
            row = mysql.student_by_no(no)
            if row:
                payload["student_id"] = row["student_id"]
        if not payload.get("student_id") and payload.get("student_ordinal") and payload.get("class_id"):
            roster = mysql.list_class_students(payload["class_id"])
            idx = int(payload["student_ordinal"]) - 1
            if 0 <= idx < len(roster):
                payload["student_id"] = roster[idx]["student_id"]
        if not payload.get("student_id"):
            raise ValueError("请说明学号，例如「看看学号 S02 的学情」或「学生1情况」。")
    if skill == "review_queue":
        action = payload.get("review_action") or payload.get("action") or "list"
        if action == "accept_all":
            payload["review_action"] = "accept_all"
        elif action in {"accepted", "overridden"}:
            payload["action"] = action
            if not payload.get("review_id") and payload.get("review_index"):
                items = mysql.list_open_reviews(payload.get("homework_id"), payload.get("class_id"))
                idx = int(payload["review_index"]) - 1
                if 0 <= idx < len(items):
                    payload["review_id"] = items[idx]["id"]
        else:
            payload["action"] = "list"
    if skill == "grade_scans" and not payload.get("scan_paths"):
        hid = payload.get("homework_id") or _latest_homework(payload.get("class_id"))
        payload["homework_id"] = hid
        if payload.get("scan_dir"):
            from zypg.gateway.intent import resolve_scan_source

            found, err = resolve_scan_source(str(payload["scan_dir"]))
            if err:
                raise ValueError(err)
            payload["scan_paths"] = found
        elif hid:
            filled = _any_scan_images(hid)
            if filled:
                payload["scan_paths"] = filled
                payload["scan_source"] = "scans"
            elif payload.get("use_card_scans"):
                raise ValueError(
                    "没有学生填好的扫描件。请上传答题卡图片，或给出本机文件夹路径。"
                    "系统不会让大模型替学生作答，也不会拿空白打印卡去批改。"
                )
            else:
                raise ValueError(
                    "请上传学生填好的答题卡图片（png/jpg），或给出本机文件夹路径。"
                    "批改不会调用大模型替学生作答。"
                )
        else:
            raise ValueError("还没有本次作业。请先出题/导入试卷，再上传学生填好的卡批改。")
    if skill == "import_paper" and not payload.get("path"):
        raise ValueError("请在对话中附上 md/docx/pdf，或说「导入示例试卷」")
    if skill == "generate_cards" and not payload.get("homework_id"):
        raise ValueError("还没有试卷。请先说「导入示例试卷」或「按等差数列出题」。")


def _latest_homework(class_id: str | None) -> str | None:
    if not class_id:
        return None
    rows = mysql.list_homeworks(class_id)
    return rows[0]["homework_id"] if rows else None


def _maybe_skip_fill_if_scans_exist(skills: list[str], homework_id: str | None) -> list[str]:
    if homework_id and _any_scan_images(homework_id) and "fill_demo_scans" in skills and "grade_scans" in skills:
        return [s for s in skills if s != "fill_demo_scans"]
    return skills


def _filled_scan_pngs(homework_id: str) -> list[str]:
    folder = homework_dir(homework_id, "scans")
    if not folder.exists():
        return []
    return [str(p) for p in sorted(folder.glob("*_filled.png"))]


def _any_scan_images(homework_id: str) -> list[str]:
    folder = homework_dir(homework_id, "scans")
    if not folder.exists():
        return []
    filled = _filled_scan_pngs(homework_id)
    if filled:
        return filled
    imgs: list[Path] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        imgs.extend(folder.glob(ext))
    return [str(p) for p in sorted(set(imgs)) if p.name != "_blank.png"]


def _merge_scan_paths(payload: dict[str, Any]) -> None:
    paths: list[str] = []
    raw = payload.get("scan_paths")
    if isinstance(raw, list):
        paths.extend(str(x) for x in raw if x)
    elif raw:
        paths.append(str(raw))
    for p in payload.get("local_paths") or []:
        paths.extend(collect_scan_images(str(p)))
    if payload.get("scan_dir"):
        from zypg.gateway.intent import resolve_scan_source

        found, err = resolve_scan_source(str(payload["scan_dir"]))
        if err:
            raise ValueError(err)
        paths.extend(found)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in paths:
        key = str(Path(p).resolve()) if Path(p).exists() else p
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    hid = payload.get("homework_id")
    if uniq and hid:
        payload["scan_paths"] = _materialize_scan_paths(str(hid), uniq)
    elif uniq:
        payload["scan_paths"] = uniq


def _materialize_scan_paths(homework_id: str, paths: list[str]) -> list[str]:
    dest_dir = homework_dir(homework_id, "scans")
    out: list[str] = []
    for sp in paths:
        src = Path(sp)
        if not src.is_file():
            src = Path(abspath(sp)) if not src.is_absolute() else src
        if not src.is_file():
            continue
        dest = dest_dir / src.name
        if dest.resolve() != src.resolve():
            dest.write_bytes(src.read_bytes())
        out.append(str(dest))
    return out


def _card_pngs(homework_id: str) -> list[str]:
    tmpl = mysql.get_card_template(homework_id)
    if not tmpl or not tmpl.get("print_path"):
        return []
    folder = abspath(tmpl["print_path"])
    if not folder.exists():
        return []
    return [str(p) for p in sorted(Path(folder).glob("*.png")) if p.name != "_blank.png"]


async def cancel_task(task_id: str) -> dict[str, Any]:
    redis_store.set_task(task_id, {"status": "canceled"})
    row = mysql.get_a2a_task(task_id)
    mysql.upsert_a2a_task(
        task_id, row.get("homework_id") if row else None, row.get("skill") if row else "", "canceled", None, None
    )
    redis_store.delete_task(task_id)
    return {"ok": True, "status": "canceled", "task_id": task_id}
