from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
    chat = "chat"
    task = "task"
    pipeline = "pipeline"


class A2APart(BaseModel):
    kind: str = "text"
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class A2AMessage(BaseModel):
    skill: str
    agent: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parts: list[A2APart] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HomeworkArtifact(BaseModel):
    homework_id: str
    class_id: str
    name: str
    items: list[dict[str, Any]]
    paper_path: str | None = None
    gradeable: bool = True


class InsightPack(BaseModel):
    class_id: str
    homework_id: str | None = None
    scope: str
    window: str
    pending_note: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentCard(BaseModel):
    name: str
    description: str
    skills: list[str]
    peer: bool = True


ROSTER_REQUIRED = "请先导入班级名单"

FORBIDDEN_PROFILE_TERMS = (
    "性格",
    "家庭",
    "差生",
    "心理",
    "预测高考",
    "高考分",
)
