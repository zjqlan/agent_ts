from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "ask",
        "description": "老师自然语言，走网关意图分类与编排",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "class_id": {"type": "string"},
                "homework_id": {"type": "string"},
                "conversation_id": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "import_roster",
        "description": "导入班级名单 CSV/XLSX",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "class_name": {"type": "string"},
                "grade": {"type": "string"},
                "subject": {"type": "string"},
                "class_id": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "generate_paper",
        "description": "按科目知识点生成试卷",
        "inputSchema": {"type": "object", "properties": {"class_id": {"type": "string"}}},
    },
    {
        "name": "import_paper",
        "description": "导入 md/docx 试卷",
        "inputSchema": {
            "type": "object",
            "properties": {"class_id": {"type": "string"}, "path": {"type": "string"}},
            "required": ["class_id", "path"],
        },
    },
    {
        "name": "generate_cards",
        "description": "按名单生成本地答题卡，不调外部 API",
        "inputSchema": {
            "type": "object",
            "properties": {"class_id": {"type": "string"}, "homework_id": {"type": "string"}},
            "required": ["class_id", "homework_id"],
        },
    },
    {
        "name": "grade_scans",
        "description": "扫描件 OMR + 主观题建议分",
        "inputSchema": {
            "type": "object",
            "properties": {
                "homework_id": {"type": "string"},
                "scan_paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["homework_id", "scan_paths"],
        },
    },
    {
        "name": "show_insight",
        "description": "班级/个人学情短长期快照",
        "inputSchema": {
            "type": "object",
            "properties": {"class_id": {"type": "string"}, "homework_id": {"type": "string"}},
            "required": ["class_id"],
        },
    },
    {
        "name": "accept_llm_scores",
        "description": "确认或覆盖主观题建议分",
        "inputSchema": {
            "type": "object",
            "properties": {
                "review_id": {"type": "integer"},
                "action": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["review_id", "action"],
        },
    },
    {
        "name": "plan_lesson",
        "description": "备课提纲 / 学期规划 / 下一份作业建议",
        "inputSchema": {
            "type": "object",
            "properties": {
                "class_id": {"type": "string"},
                "homework_id": {"type": "string"},
                "skill": {"type": "string"},
            },
            "required": ["class_id"],
        },
    },
    {
        "name": "a2a_send",
        "description": "向某个同级 Agent 发送 A2A 消息",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "agent": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["skill"],
        },
    },
]


def tool_names() -> list[str]:
    return [t["name"] for t in TOOLS]
