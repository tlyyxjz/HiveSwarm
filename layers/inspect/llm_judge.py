"""LLMJudge — 用 LLM 给结果打分, 没 key 时降级到规则 score.

跟 validator 不同: validator 是硬规则 (确定性), judge 是软标准 (模糊性).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from stub.llm_litellm import chat as llm_chat

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeScore:
    """LLM 打分结果."""

    score: float  # 0-1
    reason: str
    is_llm: bool  # True=真 LLM 打, False=规则降级


def _has_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


def _rule_based_score(text: str) -> float:
    """没 LLM key 时的兜底规则: 文本长度 / 包含关键词 → 一个 0-1 分."""
    if not text:
        return 0.0
    score = 0.5  # 基础分
    if 50 <= len(text) <= 2000:
        score += 0.3
    # 包含"完成/成功/ok" 加分
    if any(kw in text.lower() for kw in ("完成", "成功", "ok", "success", "done")):
        score += 0.2
    return min(score, 1.0)


async def judge(observation: str, expected: str = "") -> JudgeScore:
    """给一个 observation 打分.

    Args:
        observation: 实际产出(任务结果)
        expected: 期望产出(可选, 用于比较)

    Returns:
        JudgeScore(score, reason, is_llm)
    """
    if _has_key():
        try:
            prompt = (
                f"观察(实际产出): {observation}\n"
                f"期望: {expected or '(无)'}\n"
                "请给一个 0-1 的分数, 衡量产出质量. 只回复数字."
            )
            raw = llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
            ).strip()
            # 抽数字
            score = _extract_score(raw)
            return JudgeScore(score=score, reason=f"llm: {raw[:50]}", is_llm=True)
        except Exception as exc:  # noqa: BLE001
            _log.warning("LLM judge failed, fallback to rule: %s", exc)

    # 降级
    return JudgeScore(
        score=_rule_based_score(observation),
        reason="rule-based (no LLM key)",
        is_llm=False,
    )


def _extract_score(text: str) -> float:
    """从 LLM 输出抠 0-1 数字."""
    import re

    m = re.search(r"(\d+\.?\d*)", text)
    if not m:
        return 0.5
    val = float(m.group(1))
    # 容错: 0-100 → 0-1
    if val > 1.0:
        val = val / 100.0
    return max(0.0, min(1.0, val))
