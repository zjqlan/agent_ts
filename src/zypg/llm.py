from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from zypg.config import settings

SYSTEM_GUARD = (
    "你是高中单科老师的教学助手。只讨论学科、作业、知识掌握（会/弱/未测）。"
    "禁止人格贬义、家庭评价、心理诊断、差生标签、预测高考分。"
    "禁止编造学生成绩；没有数据就说明没有。"
)

SCORE_SYSTEM = (
    "你给主观题建议分，不是官方分。输入已匿名，只有 student_id。"
    "根据题干、评分点和学生作答给出 suggested_score（0 到满分）、"
    "confidence（0 到 1）和简短 comment。"
    "只输出 JSON：{\"suggested_score\": number, \"confidence\": number, \"comment\": string}。"
    "禁止人格、家庭、心理、高考预测。"
)

JsonBackend = Callable[[str, str], Awaitable[dict[str, Any]] | dict[str, Any]]
_json_backend: JsonBackend | None = None


class LLMError(RuntimeError):
    pass


def set_json_backend(fn: JsonBackend | None) -> None:
    global _json_backend
    _json_backend = fn


def llm_configured() -> bool:
    return bool(settings.llm_api_key and settings.llm_base_url and settings.llm_model)


def require_llm() -> None:
    if not llm_configured() and _json_backend is None:
        raise LLMError("未配置大模型。请在 .env 设置 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL。")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }


def _chat_url() -> str:
    return settings.llm_base_url.rstrip("/") + "/chat/completions"


def _embed_url() -> str:
    return settings.llm_base_url.rstrip("/") + "/embeddings"


def _parse_json_content(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(content[start : end + 1])
            return data if isinstance(data, dict) else {}
        return {}


async def chat(messages: list[dict[str, str]], temperature: float = 0.3) -> str:
    if not llm_configured():
        return "未配置大模型密钥，无法聊天。请在 .env 中设置 LLM_API_KEY。"
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": SYSTEM_GUARD}, *messages],
        "temperature": temperature,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(_chat_url(), headers=_headers(), json=body)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def chat_stream(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    if not llm_configured():
        yield "未配置大模型密钥，无法聊天。请在 .env 中设置 LLM_API_KEY。"
        return
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": SYSTEM_GUARD}, *messages],
        "temperature": 0.3,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", _chat_url(), headers=_headers(), json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content") or ""
                if text:
                    yield text


async def complete_json(
    user: str,
    system: str = SCORE_SYSTEM,
    *,
    temperature: float = 0.2,
    require: bool = True,
) -> dict[str, Any]:
    if _json_backend is not None:
        out = _json_backend(user, system)
        if hasattr(out, "__await__"):
            out = await out  # type: ignore[assignment]
        if not isinstance(out, dict):
            out = {}
        if require and not out:
            raise LLMError("大模型返回空 JSON。")
        return out
    require_llm()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    content = await _chat_content(messages, temperature=temperature, json_object=True)
    data = _parse_json_content(content)
    if require and not data:
        raise LLMError("大模型未返回合法 JSON，已中止，不会用模板凑数。")
    return data


async def _chat_content(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    json_object: bool,
) -> str:
    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_object:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(_chat_url(), headers=_headers(), json=body)
        if resp.status_code >= 400 and json_object:
            body.pop("response_format", None)
            resp = await client.post(_chat_url(), headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def try_embed(text: str) -> list[float] | None:
    if not llm_configured():
        return None
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                _embed_url(),
                headers=_headers(),
                json={"model": settings.embedding_model, "input": text},
            )
            if resp.status_code >= 400:
                return None
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception:
        return None
