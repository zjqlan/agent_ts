from __future__ import annotations

from typing import Any

from zypg.agents.base import PeerAgent
from zypg.agents.cards import CardsAgent
from zypg.agents.homework import HomeworkAgent
from zypg.agents.insight import InsightAgent
from zypg.agents.lesson import LessonAgent
from zypg.models import AgentCard

_AGENTS: dict[str, PeerAgent] | None = None


def all_agents() -> dict[str, PeerAgent]:
    global _AGENTS
    if _AGENTS is None:
        _AGENTS = {
            "homework": HomeworkAgent(),
            "cards": CardsAgent(),
            "insight": InsightAgent(),
            "lesson": LessonAgent(),
        }
    return _AGENTS


def get_agent(name: str) -> PeerAgent:
    agents = all_agents()
    if name not in agents:
        raise KeyError(name)
    return agents[name]


def agent_cards() -> list[AgentCard]:
    out = []
    for a in all_agents().values():
        out.append(
            AgentCard(
                name=a.name,
                description=a.description,
                skills=list(a.skills()),
                peer=True,
            )
        )
    return out


def orchestrator_card() -> dict[str, Any]:
    cards = [c.model_dump() for c in agent_cards()]
    skills = []
    for c in cards:
        skills.extend(c["skills"])
    return {
        "name": "zypg-orchestrator",
        "description": "A2A 编排器：发现 Agent Card、按老师点名派发、写 task 状态。四个业务 Agent 同级，不是 1→2→3→4 流水线。不持有业务逻辑。",
        "skills": skills,
        "peers": cards,
    }
