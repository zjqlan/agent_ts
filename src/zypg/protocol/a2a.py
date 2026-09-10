from __future__ import annotations

from typing import Any

from zypg.models import A2AMessage


_APP = None


def bind_app(app: Any) -> None:
    global _APP
    _APP = app


def get_app() -> Any:
    return _APP


SKILL_AGENT = {
    "generate_paper": "homework",
    "import_paper": "homework",
    "generate_cards": "cards",
    "fill_demo_scans": "cards",
    "grade_scans": "cards",
    "review_queue": "cards",
    "class_insight": "insight",
    "student_insight": "insight",
    "commit_long_term": "insight",
    "next_focus": "lesson",
    "term_plan": "lesson",
    "suggest_next_homework": "lesson",
}


def agent_for_skill(skill: str) -> str | None:
    return SKILL_AGENT.get(skill)


async def dispatch_local(message: A2AMessage) -> dict[str, Any]:
    from zypg.orchestrator.cards import get_agent

    name = message.agent or agent_for_skill(message.skill)
    if not name:
        raise ValueError(f"unknown skill: {message.skill}")
    agent = get_agent(name)
    return await agent.handle(message)


async def send_peer(skill: str, payload: dict[str, Any], agent: str | None = None) -> dict[str, Any]:
    """Agent-to-agent: always JSON-RPC over ASGI/HTTP, never PeerAgent.handle()."""
    import uuid

    import httpx

    from zypg.config import settings
    from zypg.protocol import jsonrpc

    body = jsonrpc.request(
        "message/send",
        {
            "skill": skill,
            "agent": agent or agent_for_skill(skill),
            "payload": payload,
            "peer": True,
        },
        id=uuid.uuid4().hex,
    )
    app = get_app()
    if app is not None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://zypg") as client:
            resp = await client.post("/a2a", json=body, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()
    else:
        async with httpx.AsyncClient(base_url=settings.public_base) as client:
            resp = await client.post("/a2a", json=body, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()
    if "error" in data:
        err = data["error"]
        raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
    result = data.get("result")
    if isinstance(result, dict) and result.get("ok") is False:
        raise RuntimeError(result.get("error") or "peer failed")
    return result or {}
