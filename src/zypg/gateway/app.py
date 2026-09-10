from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from zypg.config import settings
from zypg.gateway.intent import attach_understood, enrich_extra, format_task_reply, understand_utterance
from zypg.gateway.stream import sse_pack
from zypg.gateway.workspace_api import _bearer, router as workspace_router
from zypg.workspace import actions_from_result, get_or_create_conversation, intent_label
from zypg.llm import chat, chat_stream
from zypg.models import A2AMessage, Intent, ROSTER_REQUIRED
from zypg.orchestrator.cards import orchestrator_card
from zypg.orchestrator.engine import cancel_task, handle_user_task
from zypg.protocol import jsonrpc
from zypg.protocol.a2a import bind_app, dispatch_local
from zypg.protocol.mcp import handle_rpc
from zypg.roster.service import RosterDenied, has_roster, import_roster
from zypg.storage import mysql, redis_store
from zypg.storage.files import file_root, relpath


def _attach_teacher(extra: dict[str, Any] | None, authorization: str | None) -> dict[str, Any]:
    extra = dict(extra or {})
    if extra.get("teacher_id"):
        return extra
    from zypg.auth import teacher_from_token

    teacher = teacher_from_token(_bearer(authorization))
    if teacher:
        extra["teacher_id"] = teacher["teacher_id"]
    return extra


def _needs_roster(skills: list[str]) -> bool:
    return skills[:1] not in (["import_roster"], ["fill_demo_scans"])


async def _understand(text: str, extra: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    understood = await understand_utterance(text, extra)
    extra = attach_understood(extra, understood)
    return understood["intent"], extra

app = FastAPI(title="zypg", version="0.1.0")
app.include_router(workspace_router)
bind_app(app)

_JOBS: dict[str, Any] = {}


class AskBody(BaseModel):
    text: str
    class_id: str | None = None
    homework_id: str | None = None
    conversation_id: str | None = None
    sid: str | None = None
    extra: dict[str, Any] | None = None


@app.on_event("startup")
def _startup() -> None:
    settings.ensure_dirs()
    try:
        mysql.apply_schema()
        mysql.fail_working_tasks("网关重启，未完成的任务已中止")
    except Exception:
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    mysql_ok = False
    redis_ok = False
    errors: list[str] = []
    try:
        mysql_ok = mysql.ping()
    except Exception as exc:
        errors.append(f"mysql: {exc}")
    try:
        redis_ok = redis_store.ping()
    except Exception as exc:
        errors.append(f"redis: {exc}")
    return {"ok": mysql_ok and redis_ok, "mysql": mysql_ok, "redis": redis_ok, "errors": errors}


@app.post("/roster/import")
async def roster_import(
    file: UploadFile = File(...),
    class_name: str = Form("未命名班级"),
    grade: str | None = Form(None),
    subject: str | None = Form(None),
    class_id: str | None = Form(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    dest = file_root() / "rosters"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / (file.filename or "roster.csv")
    path.write_bytes(await file.read())
    extra = _attach_teacher({}, authorization)
    try:
        return import_roster(
            path,
            class_name=class_name,
            grade=grade,
            subject=subject,
            class_id=class_id,
            teacher_id=extra.get("teacher_id"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict[str, Any]:
    return orchestrator_card()


@app.get("/insights/{class_id}")
def insights(class_id: str, homework_id: str | None = None) -> dict[str, Any]:
    if not has_roster(class_id):
        raise HTTPException(403, ROSTER_REQUIRED)
    snaps = mysql.latest_snapshots(class_id)
    hot = redis_store.get_insight_hot(class_id)
    queue = mysql.list_open_reviews(homework_id=homework_id, class_id=class_id)
    return {
        "snapshots": snaps,
        "hot": hot,
        "review_queue": queue,
        "homeworks": mysql.list_homeworks(class_id),
        "students": mysql.list_class_students(class_id),
    }


def _store_assistant(conv: str, payload: dict[str, Any]) -> None:
    mysql.insert_message(conv, "assistant", json.dumps(payload, ensure_ascii=False))


def _history_for_llm(conv: str) -> list[dict[str, str]]:
    msgs = []
    for m in mysql.list_messages(conv):
        content = m.get("content") or ""
        if m["role"] == "assistant" and content[:1] == "{":
            try:
                parsed = json.loads(content)
                content = parsed.get("text") or content
            except json.JSONDecodeError:
                pass
        msgs.append({"role": m["role"], "content": content})
    return msgs


@app.post("/ask/understand")
async def ask_understand(body: AskBody, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    extra = enrich_extra(body.text, _attach_teacher(body.extra, authorization))
    understood = await understand_utterance(body.text, extra)
    intent = understood["intent"]
    return {
        "intent": intent.value,
        "intent_label": intent_label(intent.value),
        "skills": understood.get("skills") or [],
        "slots": understood.get("slots") or {},
    }


@app.post("/ask")
async def ask(body: AskBody, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    sid = body.sid or uuid.uuid4().hex
    extra = enrich_extra(body.text, _attach_teacher(body.extra, authorization))
    intent, extra = await _understand(body.text, extra)
    redis_store.set_session(
        sid,
        {
            "intent": intent.value,
            "class_id": body.class_id,
            "homework_id": body.homework_id,
        },
    )
    conv = body.conversation_id or get_or_create_conversation(body.class_id, body.homework_id)
    mysql.insert_conversation(conv, body.homework_id, body.class_id)
    mysql.insert_message(conv, "user", body.text)
    if intent == Intent.chat:
        msgs = _history_for_llm(conv)
        ctx = ""
        if body.class_id and has_roster(body.class_id):
            cls = mysql.get_class(body.class_id)
            ctx = f"（当前班级 {cls['name'] if cls else body.class_id}，禁止编造成绩）"
        answer = await chat(msgs + ([{"role": "user", "content": ctx}] if ctx else []))
        _store_assistant(
            conv,
            {"kind": "text", "text": answer, "intent": intent.value, "ok": True},
        )
        return {
            "ok": True,
            "intent": intent.value,
            "intent_label": intent_label(intent.value),
            "kind": "text",
            "text": answer,
            "summary": answer,
            "conversation_id": conv,
            "sid": sid,
        }
    skills = extra.get("skills") or extra.get("understood", {}).get("skills") or []
    if _needs_roster(skills) and not has_roster(body.class_id):
        payload = {
            "kind": "refuse",
            "text": ROSTER_REQUIRED,
            "intent": intent.value,
            "ok": False,
        }
        _store_assistant(conv, payload)
        return {
            "ok": False,
            "kind": "refuse",
            "intent": intent.value,
            "intent_label": intent_label(intent.value),
            "error": ROSTER_REQUIRED,
            "summary": ROSTER_REQUIRED,
            "conversation_id": conv,
            "sid": sid,
        }
    result = await handle_user_task(body.text, body.class_id, body.homework_id, extra=extra)
    summary = result.get("summary") or format_task_reply(result)
    if result.get("homework_id"):
        mysql.bind_conversation(conv, result["homework_id"], result.get("class_id") or body.class_id)
    kind = "refuse" if result.get("ok") is False else "result"
    actions = actions_from_result(result)
    _store_assistant(
        conv,
        {"kind": kind, "text": summary, "intent": intent.value, "ok": result.get("ok", True), "actions": actions},
    )
    return {
        **result,
        "kind": kind,
        "summary": summary,
        "actions": actions,
        "intent_label": intent_label(intent.value),
        "conversation_id": conv,
        "sid": sid,
    }


@app.post("/ask/start")
async def ask_start(body: AskBody, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """后台执行任务。浏览器断开或切页不会取消。"""
    import asyncio

    extra = enrich_extra(body.text, _attach_teacher(body.extra, authorization))
    intent, extra = await _understand(body.text, extra)
    if intent == Intent.chat:
        raise HTTPException(400, "闲聊请走对话")
    working = mysql.list_working_tasks(body.homework_id, body.class_id)
    if working:
        raise HTTPException(409, "已有任务在后台运行，请稍候或点取消")
    sid = body.sid or uuid.uuid4().hex
    conv = body.conversation_id or get_or_create_conversation(body.class_id, body.homework_id)
    mysql.insert_conversation(conv, body.homework_id, body.class_id)
    mysql.insert_message(conv, "user", body.text)

    async def job() -> None:
        try:
            result = await handle_user_task(body.text, body.class_id, body.homework_id, extra=extra)
            summary = result.get("summary") or format_task_reply(result)
            if result.get("homework_id"):
                mysql.bind_conversation(conv, result["homework_id"], result.get("class_id") or body.class_id)
            kind = "refuse" if result.get("ok") is False else "result"
            actions = actions_from_result(result)
            _store_assistant(
                conv,
                {
                    "kind": kind,
                    "text": summary,
                    "intent": intent.value,
                    "ok": result.get("ok", True),
                    "actions": actions,
                },
            )
        except Exception as exc:
            mysql.fail_working_tasks(str(exc))
            _store_assistant(
                conv,
                {"kind": "refuse", "text": str(exc), "intent": intent.value, "ok": False},
            )
        finally:
            _JOBS.pop(sid, None)

    _JOBS[sid] = asyncio.create_task(job())
    return {
        "ok": True,
        "started": True,
        "sid": sid,
        "conversation_id": conv,
        "intent": intent.value,
        "intent_label": intent_label(intent.value),
    }


@app.get("/ask/stream")
async def ask_stream_get(
    text: str = Query(...),
    class_id: str | None = None,
    homework_id: str | None = None,
    conversation_id: str | None = None,
    sid: str | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _ask_stream_gen(text, class_id, homework_id, conversation_id, sid, extra={}),
        media_type="text/event-stream",
    )


@app.post("/ask/stream")
async def ask_stream_post(body: AskBody, authorization: str | None = Header(default=None)) -> StreamingResponse:
    return StreamingResponse(
        _ask_stream_gen(
            body.text,
            body.class_id,
            body.homework_id,
            body.conversation_id,
            body.sid,
            extra=enrich_extra(body.text, _attach_teacher(body.extra, authorization)),
        ),
        media_type="text/event-stream",
    )


async def _ask_stream_gen(
    text: str,
    class_id: str | None,
    homework_id: str | None,
    conversation_id: str | None,
    sid: str | None,
    extra: dict[str, Any],
):
    sid = sid or uuid.uuid4().hex
    extra = extra or {}
    conv = conversation_id or get_or_create_conversation(class_id, homework_id)
    intent, extra = await _understand(text, extra)
    redis_store.set_session(
        sid, {"intent": intent.value, "class_id": class_id, "homework_id": homework_id}
    )
    yield sse_pack("intent", {"intent": intent.value, "intent_label": intent_label(intent.value), "sid": sid})
    mysql.insert_conversation(conv, homework_id, class_id)
    mysql.insert_message(conv, "user", text)
    if intent == Intent.chat:
        msgs = _history_for_llm(conv)
        acc = []
        async for tok in chat_stream(msgs):
            acc.append(tok)
            yield sse_pack("token", {"text": tok})
        answer = "".join(acc)
        _store_assistant(conv, {"kind": "text", "text": answer, "intent": intent.value, "ok": True})
        yield sse_pack(
            "done",
            {
                "ok": True,
                "kind": "text",
                "conversation_id": conv,
                "sid": sid,
                "intent": intent.value,
                "intent_label": intent_label(intent.value),
                "summary": answer,
            },
        )
        return
    skills = extra.get("skills") or extra.get("understood", {}).get("skills") or []
    if _needs_roster(skills) and not has_roster(class_id):
        _store_assistant(
            conv, {"kind": "refuse", "text": ROSTER_REQUIRED, "intent": intent.value, "ok": False}
        )
        yield sse_pack("error", {"error": ROSTER_REQUIRED})
        yield sse_pack("token", {"text": ROSTER_REQUIRED})
        yield sse_pack(
            "done",
            {
                "ok": False,
                "kind": "refuse",
                "error": ROSTER_REQUIRED,
                "summary": ROSTER_REQUIRED,
                "intent": intent.value,
                "intent_label": intent_label(intent.value),
                "conversation_id": conv,
                "sid": sid,
            },
        )
        return

    import asyncio

    queue: asyncio.Queue = asyncio.Queue()

    async def progress_cb(ev: dict[str, Any]) -> None:
        await queue.put(("progress", ev))

    async def runner() -> None:
        try:
            result = await handle_user_task(
                text,
                class_id,
                homework_id,
                extra={**extra, "progress_cb": progress_cb},
                progress=progress_cb,
            )
            await queue.put(("done", result))
        except Exception as exc:
            await queue.put(("error", {"error": str(exc)}))

    yield sse_pack("progress", {"skills": skills, "status": "working"})
    task = asyncio.create_task(runner())
    while True:
        kind, data = await queue.get()
        if kind == "progress":
            yield sse_pack("progress", data)
        elif kind == "error":
            yield sse_pack("error", data)
            yield sse_pack("token", {"text": str(data.get("error") or data)})
            yield sse_pack("done", {"ok": False, "conversation_id": conv})
            break
        else:
            summary = data.get("summary") or format_task_reply(data)
            if data.get("homework_id"):
                mysql.bind_conversation(conv, data["homework_id"], data.get("class_id") or class_id)
            kind = "refuse" if data.get("ok") is False else "result"
            actions = actions_from_result(data)
            _store_assistant(
                conv,
                {
                    "kind": kind,
                    "text": summary,
                    "intent": intent.value,
                    "ok": data.get("ok", True),
                    "actions": actions,
                },
            )
            yield sse_pack("token", {"text": summary})
            yield sse_pack(
                "done",
                {
                    **data,
                    "kind": kind,
                    "summary": summary,
                    "actions": actions,
                    "intent_label": intent_label(intent.value),
                    "conversation_id": conv,
                    "sid": sid,
                },
            )
            break
    await task


@app.post("/a2a")
async def a2a(body: dict[str, Any]) -> JSONResponse:
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    try:
        if method == "message/send":
            msg = A2AMessage(
                skill=params.get("skill") or (params.get("message") or {}).get("skill"),
                agent=params.get("agent"),
                payload=params.get("payload") or params.get("message", {}).get("metadata") or {},
            )
            if not msg.skill:
                return JSONResponse(jsonrpc.error(req_id, -32602, "skill required"))
            # 业务门禁：无名单拒绝（chat 不走 /a2a）
            class_id = msg.payload.get("class_id")
            hw = msg.payload.get("homework_id")
            if hw and not class_id:
                row = mysql.get_assignment(hw)
                class_id = row["class_id"] if row else None
                msg.payload.setdefault("class_id", class_id)
            value = await dispatch_local(msg)
            return JSONResponse(jsonrpc.result(req_id, value))
        if method == "tasks/get":
            tid = params.get("task_id") or params.get("id")
            hot = redis_store.get_task(tid)
            row = mysql.get_a2a_task(tid)
            return JSONResponse(jsonrpc.result(req_id, {"redis": hot, "mysql": row}))
        if method == "tasks/cancel":
            tid = params.get("task_id") or params.get("id")
            return JSONResponse(jsonrpc.result(req_id, await cancel_task(tid)))
        return JSONResponse(jsonrpc.error(req_id, -32601, f"method not found: {method}"))
    except RosterDenied as exc:
        return JSONResponse(jsonrpc.error(req_id, 403, str(exc)))
    except Exception as exc:
        return JSONResponse(jsonrpc.error(req_id, -32000, str(exc)))


@app.post("/mcp")
async def mcp(body: dict[str, Any]) -> dict[str, Any]:
    return await handle_rpc(body)


@app.post("/files/save")
async def files_save(file: UploadFile = File(...), kind: str = Form("scans")) -> dict[str, Any]:
    dest = file_root() / kind
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / (file.filename or uuid.uuid4().hex)
    path.write_bytes(await file.read())
    return {"path": relpath(path), "abs": str(path)}
