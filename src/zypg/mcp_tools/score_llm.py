from __future__ import annotations

from typing import Any, Callable

from zypg.llm import LLMError, complete_json, llm_configured

ScoreBackend = Callable[[dict[str, Any]], dict[str, Any]]
_backend: ScoreBackend | None = None
LOW_CONF = 0.6


def set_backend(fn: ScoreBackend | None) -> None:
    global _backend
    _backend = fn


async def suggest_score(payload: dict[str, Any]) -> dict[str, Any]:
    """payload: stem, rubric, answer, ocr_text, max_score, student_id (anonymous)."""
    if _backend is not None:
        return _backend(payload)
    if not llm_configured() and _backend is None:
        return {
            "suggested_score": None,
            "confidence": 0.0,
            "comment": "未配置大模型，主观题进入老师确认队列",
            "queued": True,
            "reason": "no_llm",
        }
    user = (
        f"student_id={payload.get('student_id')}\n"
        f"满分={payload.get('max_score')}\n"
        f"题干={payload.get('stem')}\n"
        f"评分点={payload.get('rubric')}\n"
        f"参考答案={payload.get('answer')}\n"
        f"学生作答={payload.get('ocr_text')}\n"
        "根据作答与评分点给建议分。不要因为作答像印刷体就给满分；对了才给分。"
    )
    try:
        data = await complete_json(user, require=True)
    except LLMError as exc:
        return {
            "suggested_score": None,
            "confidence": 0.0,
            "comment": str(exc),
            "queued": True,
            "reason": "llm_error",
        }
    try:
        score = float(data.get("suggested_score"))
    except (TypeError, ValueError):
        score = None
    try:
        conf = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    low = score is None or conf < LOW_CONF
    from zypg.config import settings as _settings

    return {
        "suggested_score": score,
        "confidence": conf,
        "comment": data.get("comment") or "",
        "queued": low,
        "reason": "low_confidence" if low else "needs_confirm",
        "llm_model": _settings.llm_model,
    }
