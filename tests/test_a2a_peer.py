from __future__ import annotations

from pathlib import Path

from zypg.agents.base import PeerAgent
from zypg.orchestrator.cards import agent_cards, all_agents
from zypg.protocol.catalog import tool_names


def test_four_peer_agents_skills():
    agents = all_agents()
    assert set(agents) == {"homework", "cards", "insight", "lesson"}
    for name, agent in agents.items():
        assert isinstance(agent, PeerAgent)
        assert agent.name == name
        skills = agent.skills()
        assert skills, name
        card = next(c for c in agent_cards() if c.name == name)
        assert card.skills == skills
        assert card.peer is True


def test_cards_does_not_import_homework_privates():
    src = Path(__file__).resolve().parents[1] / "src" / "zypg" / "agents" / "cards.py"
    text = src.read_text(encoding="utf-8")
    assert "HomeworkAgent" not in text
    assert "agents.homework" not in text
    assert "from zypg.agents.homework" not in text
    assert "import zypg.agents.homework" not in text


def test_mcp_tools_list_matches_catalog(db):
    from fastapi.testclient import TestClient

    from zypg.gateway.app import app

    client = TestClient(app)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = [t["name"] for t in r.json()["result"]["tools"]]
    assert names == tool_names()
