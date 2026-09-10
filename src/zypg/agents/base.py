from __future__ import annotations

from typing import Any

from zypg.models import A2AMessage


class PeerAgent:
    name: str = ""
    description: str = ""

    def skills(self) -> list[str]:
        raise NotImplementedError

    async def handle(self, message: A2AMessage) -> dict[str, Any]:
        raise NotImplementedError
