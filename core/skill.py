"""Skill — 技能包契约 ABC.

职责:定义"一个 skill 是什么、怎么被借、怎么被还、怎么自检". 技能池
(Pool) 只看 SkillManifest,不看具体实现.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillManifest:
    """技能元数据. 写到 manifest.toml,Pool 借的时候读这个."""

    name: str                # "agentvet_l1"
    api_version: str         # "1.0" — 跟核心要求匹配
    min_core_version: str = "0.0.0"
    description: str = ""
    tags: tuple[str, ...] = ()
    health_check_interval_s: int = 60


@dataclass
class SkillHealth:
    """技能健康度. 低于阈值 Pool 自动 retirement."""

    name: str
    success_count: int = 0
    failure_count: int = 0
    last_check_ts: float = 0.0
    last_error: str = ""

    @property
    def error_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.failure_count / total if total else 0.0


class Skill(ABC):
    """一个技能. Pool.checkout() 调 checkout() 借出, return_back() 调 release()."""

    def __init__(self, manifest: SkillManifest) -> None:
        self.manifest = manifest

    @abstractmethod
    def run(self, input_data: dict) -> dict:
        """执行技能. 同步阻塞或 async 都可以,实现自己定."""

    async def health_check(self) -> SkillHealth:
        """异步自检. 默认实现 = 没失败就 100%."""
        return SkillHealth(name=self.manifest.name)
