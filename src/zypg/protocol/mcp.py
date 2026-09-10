from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from zypg.protocol import jsonrpc
from zypg.protocol.catalog import TOOLS, tool_names

INTERNAL_TOOLS = {
    "generate_exam_paper",
    "parse_paper",
    "render_cards",
    "fill_student_marks",
    "simulate_student_answers",
    "omr_read",
    "omr_match_homework",
    "omr_student_no",
    "omr_crop",
    "ocr_image",
    "score_subjective",
    "render_charts",
}


async def call_internal(name: str, arguments: dict[str, Any] | None = None) -> Any:
    arguments = arguments or {}
    if name == "generate_exam_paper":
        from zypg.mcp_tools.edupaper import generate_exam_paper

        return await generate_exam_paper(arguments)
    if name == "parse_paper":
        from zypg.mcp_tools.edupaper import parse_paper_file

        return parse_paper_file(arguments["path"])
    if name == "render_cards":
        from zypg.mcp_tools.card_render import render_cards

        return render_cards(arguments["homework_id"], arguments["items"], arguments["students"])
    if name == "fill_student_marks":
        from zypg.mcp_tools.card_render import make_filled_scans

        return make_filled_scans(
            arguments["homework_id"],
            arguments["geometry"],
            arguments["students"],
            arguments["items"],
            scripts=arguments["scripts"],
        )
    if name == "simulate_student_answers":
        from zypg.mcp_tools.student_sim import simulate_student_answers

        return await simulate_student_answers(arguments["students"], arguments["items"])
    if name == "omr_read":
        from zypg.mcp_tools.omr import read_bubbles

        return read_bubbles(arguments["scan_path"], arguments["blank_path"], arguments["geometry"])
    if name == "omr_match_homework":
        from zypg.mcp_tools.omr import decode_homework

        return {"ok": decode_homework(arguments["scan_path"], arguments["geometry"])}
    if name == "omr_student_no":
        from zypg.mcp_tools.omr import decode_student_no

        return {"student_no": decode_student_no(arguments["scan_path"], arguments["geometry"], arguments.get("blank_path"))}
    if name == "omr_crop":
        from zypg.mcp_tools.omr import crop_subjective

        return crop_subjective(
            arguments["scan_path"],
            arguments["geometry"],
            arguments["item_id"],
            arguments["dest"],
        )
    if name == "ocr_image":
        from zypg.mcp_tools.ocr import ocr_image

        return await asyncio.to_thread(ocr_image, arguments["path"])
    if name == "score_subjective":
        from zypg.mcp_tools.score_llm import suggest_score

        return await suggest_score(arguments)
    if name == "render_charts":
        from zypg.mcp_tools.charts import render_charts

        return render_charts(arguments["class_id"], arguments.get("homework_id"), arguments.get("pack") or {})
    raise ValueError(f"unknown internal tool {name}")


async def call_external(name: str, arguments: dict[str, Any] | None = None) -> Any:
    arguments = arguments or {}
    if name not in tool_names():
        raise ValueError(f"unknown tool {name}")
    if name == "ask":
        from zypg.orchestrator.engine import handle_user_task

        return await handle_user_task(
            arguments.get("text") or "",
            arguments.get("class_id"),
            arguments.get("homework_id"),
            extra={k: v for k, v in arguments.items() if k not in {"text", "class_id", "homework_id"}},
        )
    if name == "import_roster":
        from zypg.roster.service import import_roster

        return import_roster(
            arguments["path"],
            class_name=arguments.get("class_name") or "未命名班级",
            grade=arguments.get("grade"),
            subject=arguments.get("subject"),
            class_id=arguments.get("class_id"),
            teacher_id=arguments.get("teacher_id"),
        )
    if name == "a2a_send":
        from zypg.models import A2AMessage
        from zypg.protocol.a2a import dispatch_local

        msg = A2AMessage(
            skill=arguments["skill"],
            agent=arguments.get("agent"),
            payload=arguments.get("payload") or {},
        )
        return await dispatch_local(msg)
    skill_map = {
        "generate_paper": "generate_paper",
        "import_paper": "import_paper",
        "generate_cards": "generate_cards",
        "grade_scans": "grade_scans",
        "show_insight": "class_insight",
        "plan_lesson": arguments.get("skill") or "next_focus",
        "accept_llm_scores": "review_queue",
    }
    from zypg.models import A2AMessage
    from zypg.protocol.a2a import dispatch_local

    skill = skill_map[name]
    payload = dict(arguments)
    if name == "accept_llm_scores":
        payload.setdefault("action", arguments.get("action"))
    if name == "show_insight" and arguments.get("student_id"):
        skill = "student_insight"
    return await dispatch_local(A2AMessage(skill=skill, payload=payload))


async def handle_rpc(body: dict[str, Any]) -> dict[str, Any]:
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    try:
        if method == "initialize":
            return jsonrpc.result(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "zypg", "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return jsonrpc.result(req_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            value = await call_external(name, arguments)
            return jsonrpc.result(
                req_id,
                {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, default=str)}]},
            )
        return jsonrpc.error(req_id, -32601, f"method not found: {method}")
    except Exception as exc:
        return jsonrpc.error(req_id, -32000, str(exc))


def stdio_loop() -> None:
    import asyncio

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        body = json.loads(line)
        out = asyncio.run(handle_rpc(body))
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()
