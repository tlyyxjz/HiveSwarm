"""LLMBrain — 调 LiteLLM 拆任务 + 决策。

没有 LLM key 时降级到 MockBrain, 产生固定 Plan。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from core.brain import Brain, Plan, SubTask
from core.events import Event, EventBus, EventType
from stub.llm_litellm import (
    ConfigurationError,
    dispatch_async,
    resolve_ollama,
)
from stub.llm_litellm import chat as llm_chat

_log = logging.getLogger(__name__)


class PlanParseError(ValueError):
    """LLM 输出无法解析为 Plan."""


def _extract_json(text: str) -> dict:
    """LLM 经常包 markdown 围栏, 这里宽容地抠 JSON。"""
    text = text.strip()
    # 1. 直接就是 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. ```json ... ``` 围栏
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 最外层 { ... } 抠出来 (非贪婪, 防止 greedy 吞太多)
    m = re.search(r"\{[\s\S]*?\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise PlanParseError(f"no JSON in LLM output: {text!r}")


def _dict_to_plan(d: dict, original: str) -> Plan:
    """dict → Plan. 缺字段抛错."""
    if "task_id" not in d:
        raise PlanParseError("missing task_id")
    if "subtasks" not in d or not isinstance(d["subtasks"], list):
        raise PlanParseError("missing or empty subtasks")
    subs: list[SubTask] = []
    for s in d["subtasks"]:
        if "sub_id" not in s or "intent" not in s:
            raise PlanParseError("subtask missing sub_id/intent")
        subs.append(
            SubTask(
                sub_id=str(s["sub_id"]),
                intent=str(s["intent"]),
                required_skills=tuple(s.get("required_skills", []) or []),
                depends_on=tuple(s.get("depends_on", []) or []),
                acceptance=str(s.get("acceptance", "")),
            )
        )
    return Plan(
        task_id=str(d["task_id"]),
        original_request=original,
        subtasks=subs,
        rationale=str(d.get("rationale", "")),
    )


class MockBrain(Brain):
    """没 LLM key 时用的降级 Brain — 输出固定 Plan."""

    async def plan(self, request: str, context: dict | None = None) -> Plan:
        req_lower = request.lower()
        if any(kw in req_lower for kw in ("抓", "爬", "fetch", "crawl")):
            return self._dag_crawl_then_process(request)
        if "ppt" in req_lower or "演示" in request:
            subs = [
                SubTask("s1", "采集数据", required_skills=("data_collect",)),
                SubTask("s2", "写大纲", required_skills=("outline",), depends_on=("s1",)),
                SubTask("s3", "排版", required_skills=("layout",), depends_on=("s2",)),
                SubTask("s4", "导出", required_skills=("export",), depends_on=("s3",)),
            ]
        elif "扫描" in request or "scan" in req_lower:
            subs = [
                SubTask("s1", "L1 扫描", required_skills=("agentvet_l1",)),
                SubTask("s2", "L2 扫描", required_skills=("agentvet_l2",), depends_on=("s1",)),
            ]
        else:
            subs = [SubTask("s1", "默认子任务", required_skills=())]
        return Plan(
            task_id="mock-" + str(hash(request))[:8],
            original_request=request,
            subtasks=subs,
            rationale="mock brain (no LLM key configured)",
        )

    def _dag_crawl_then_process(self, request: str) -> Plan:
        subs = [
            SubTask("s1", "抓取数据", required_skills=("http_fetch",)),
            SubTask("s2", "提取链接", required_skills=("url_extract",), depends_on=("s1",)),
            SubTask("s3", "后续处理", required_skills=(), depends_on=("s2",)),
        ]
        return Plan(
            task_id="mock-" + str(hash(request))[:8],
            original_request=request,
            subtasks=subs,
            rationale="DAG chain: http_fetch → url_extract → (user-defined post-process)",
        )

    async def decide(self, plan: Plan, observations: list[dict]) -> tuple[str, str]:
        failures = sum(1 for o in observations if not o.get("ok"))
        if failures >= 3:
            return "halt", f"too many failures: {failures}"
        if failures >= 1:
            return "switch", f"retry with different approach (failures={failures})"
        return "continue", "all good"


class LLMBrain(Brain):
    """真 LLM Brain — 配置驱动模型选择。

    客户在 [[providers]] 配模型, active_provider 指定当前用哪个。
    配置驱动失败或不可达 → MockBrain 降级。
    """

    def __init__(
        self,
        system_prompt: str,
        model: str = "minimax-m3-plus",
        max_retries: int = 2,
        bus: EventBus | None = None,
        cfg=None,
    ) -> None:
        self._prompt = system_prompt
        self._model = model
        self._max_retries = max_retries
        self._bus = bus
        self._cfg = cfg
        self._mock = MockBrain()

    def _has_key(self) -> bool:
        # 1. 配置驱动：有 providers 注册表 + active_provider 真存在 → 视为可用
        if self._cfg and self._cfg.brain.providers:
            from stub.llm_litellm import _find_provider

            if _find_provider(self._cfg.brain.active_provider, self._cfg.brain.providers):
                return True
        # 2. 环境变量回退
        import os

        if bool(
            os.getenv("MINIMAX_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        ):
            return True
        # 3. Ollama 真测可达性 (同步壳包 async ping)
        try:
            import asyncio

            result = resolve_ollama(self._cfg)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            if result is not None:
                return True
        except Exception as exc:
            _log.debug("ollama resolve failed: %s", exc, exc_info=True)
        return False

    async def plan(self, request: str, context: dict | None = None) -> Plan:
        if not self._has_key():
            return await self._mock.plan(request, context)

        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                msgs = [
                    {"role": "system", "content": self._prompt},
                    {"role": "user", "content": request},
                ]
                if self._cfg:
                    raw = await dispatch_async(msgs, cfg=self._cfg)
                else:
                    raw = llm_chat(msgs, model=self._model)
                d = _extract_json(raw)
                plan = _dict_to_plan(d, request)
                self._emit(EventType.TASK_STARTED, {"plan_id": plan.task_id, "sub_count": len(plan.subtasks)})
                return plan
            except (PlanParseError, ConfigurationError) as exc:
                last_err = exc
                _log.warning(
                    "LLM plan attempt %d failed: %s", attempt, exc, exc_info=True
                )
            except Exception as exc:
                last_err = exc
                _log.warning(
                    "LLM plan attempt %d unexpected: %s", attempt, exc, exc_info=True
                )

        _log.warning("falling back to mock brain after %d failures", self._max_retries + 1)
        return await self._mock.plan(request, context)

    async def decide(self, plan: Plan, observations: list[dict]) -> tuple[str, str]:
        return await self._mock.decide(plan, observations)

    def _emit(self, et: EventType, payload: dict) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(Event(type=et, payload=payload))
        except Exception:
            _log.warning("emit failed", exc_info=True)