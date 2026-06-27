"""配置加载 — 读 toml, 返回 Config dataclass, 带类型校验.

设计:
  - default.toml 是基线
  - mvp.toml / production.toml 是 override
  - loader 合并 → 返回 Config dataclass
  - 缺关键字段 → 抛 ConfigError(早失败, 不要运行时爆炸)
"""
from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """配置错误. 区别于运行时错误, 表示"启动时就该炸"."""


@dataclass(frozen=True)
class ProviderCfg:
    """单个 LLM 提供商配置。客户在 [[providers]] 里定义。"""
    name: str
    type: str                    # "ollama" | "anthropic" | "openai"
    base_url: str
    model: str
    api_key: str
    tier: str = "standard"       # free | standard | premium | enterprise
    description: str = ""

    def resolve_key(self) -> str:
        """${VAR} → os.environ[VAR]，否则原样返回。"""
        import os, re
        m = re.match(r'^\$\{(\w+)\}$', self.api_key)
        if m:
            return os.environ.get(m.group(1), "")
        return self.api_key


@dataclass(frozen=True)
class BrainCfg:
    llm_provider: str
    llm_model: str
    planner_system_prompt: str
    active_provider: str = ""
    embedding_provider: str = ""
    embedding_model: str = "bge-m3:latest"
    providers: tuple[ProviderCfg, ...] = ()


@dataclass(frozen=True)
class RepairCfg:
    strategy: str
    max_retries: int
    retry_delay_s: float
    pause_threshold: int


@dataclass(frozen=True)
class MonitorCfg:
    bus: str
    dashboard: str
    dashboard_port: int
    log_path: str
    log_max_size_mb: int


@dataclass(frozen=True)
class MemoryCfg:
    backend: str
    path: str
    ttl_days: int
    embedding_model: str = "bge-m3:latest"
    batch_size: int = 20
    window_days: int = 30


@dataclass(frozen=True)
class AuthCfg:
    provider: str
    default_user: str


@dataclass(frozen=True)
class AuditCfg:
    provider: str
    path: str


@dataclass(frozen=True)
class BillingCfg:
    provider: str


@dataclass(frozen=True)
class TenantCfg:
    provider: str


@dataclass(frozen=True)
class RecoveryCfg:
    provider: str
    base_delay_s: float


@dataclass(frozen=True)
class TelemetryCfg:
    provider: str


@dataclass(frozen=True)
class GovernanceCfg:
    provider: str


@dataclass(frozen=True)
class GatewayCfg:
    host: str
    port: int
    workers: int
    log_level: str


@dataclass(frozen=True)
class SkillsCfg:
    enabled: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    """完整配置. frozen 防止业务层意外改."""

    brain: BrainCfg
    repair: RepairCfg
    monitor: MonitorCfg
    memory: MemoryCfg
    auth: AuthCfg
    audit: AuditCfg
    billing: BillingCfg
    tenant: TenantCfg
    recovery: RecoveryCfg
    telemetry: TelemetryCfg
    governance: GovernanceCfg
    gateway: GatewayCfg
    skills: SkillsCfg
    source_files: tuple[str, ...] = field(default_factory=tuple)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _require(d: dict[str, Any], key: str, section: str) -> Any:
    if key not in d:
        raise ConfigError(f"missing required key: [{section}].{key}")
    return d[key]


def _parse(raw: dict[str, Any], sources: tuple[str, ...]) -> Config:
    try:
        # 解析 [[providers]] 注册表
        providers_raw = raw.get("providers", []) or []
        providers = tuple(
            ProviderCfg(
                name=p["name"],
                type=p.get("type", "anthropic"),
                base_url=p.get("base_url", ""),
                model=p.get("model", ""),
                api_key=p.get("api_key", ""),
                tier=p.get("tier", "standard"),
                description=p.get("description", ""),
            )
            for p in providers_raw
        )

        brain_raw = raw["brain"]
        return Config(
            brain=BrainCfg(
                llm_provider=_require(brain_raw, "llm_provider", "brain"),
                llm_model=brain_raw.get("llm_model", "qwen3:8b"),
                planner_system_prompt=_require(
                    brain_raw, "planner_system_prompt", "brain"
                ),
                active_provider=brain_raw.get("active_provider", ""),
                embedding_provider=brain_raw.get("embedding_provider", ""),
                embedding_model=brain_raw.get("embedding_model", "bge-m3:latest"),
                providers=providers,
            ),
            repair=RepairCfg(
                strategy=_require(raw["repair"], "strategy", "repair"),
                max_retries=int(_require(raw["repair"], "max_retries", "repair")),
                retry_delay_s=float(_require(raw["repair"], "retry_delay_s", "repair")),
                pause_threshold=int(
                    _require(raw["repair"], "pause_threshold", "repair")
                ),
            ),
            monitor=MonitorCfg(
                bus=_require(raw["monitor"], "bus", "monitor"),
                dashboard=_require(raw["monitor"], "dashboard", "monitor"),
                dashboard_port=int(
                    _require(raw["monitor"], "dashboard_port", "monitor")
                ),
                log_path=_require(raw["monitor"], "log_path", "monitor"),
                log_max_size_mb=int(
                    _require(raw["monitor"], "log_max_size_mb", "monitor")
                ),
            ),
            memory=MemoryCfg(
                backend=_require(raw["memory"], "backend", "memory"),
                path=_require(raw["memory"], "path", "memory"),
                ttl_days=int(_require(raw["memory"], "ttl_days", "memory")),
                embedding_model=raw["memory"].get("embedding_model", "bge-m3:latest"),
                batch_size=int(raw["memory"].get("batch_size", 20)),
                window_days=int(raw["memory"].get("window_days", 30)),
            ),
            auth=AuthCfg(
                provider=_require(raw["auth"], "provider", "auth"),
                default_user=_require(raw["auth"], "default_user", "auth"),
            ),
            audit=AuditCfg(
                provider=_require(raw["audit"], "provider", "audit"),
                path=_require(raw["audit"], "path", "audit"),
            ),
            billing=BillingCfg(provider=_require(raw["billing"], "provider", "billing")),
            tenant=TenantCfg(provider=_require(raw["tenant"], "provider", "tenant")),
            recovery=RecoveryCfg(
                provider=_require(raw["recovery"], "provider", "recovery"),
                base_delay_s=float(
                    _require(raw["recovery"], "base_delay_s", "recovery")
                ),
            ),
            telemetry=TelemetryCfg(
                provider=_require(raw["telemetry"], "provider", "telemetry")
            ),
            governance=GovernanceCfg(
                provider=_require(raw["governance"], "provider", "governance")
            ),
            gateway=GatewayCfg(
                host=_require(raw["gateway"], "host", "gateway"),
                port=int(_require(raw["gateway"], "port", "gateway")),
                workers=int(_require(raw["gateway"], "workers", "gateway")),
                log_level=_require(raw["gateway"], "log_level", "gateway"),
            ),
            skills=SkillsCfg(
                enabled=tuple(raw.get("skills", {}).get("enabled", []) or []),
            ),
            source_files=sources,
        )
    except KeyError as exc:
        raise ConfigError(f"missing section: {exc}") from exc


def _deep_merge(base: dict, override: dict) -> dict:
    """override 浅覆盖, 列表直接替换."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(
    override_path: str | Path | None = None,
    *,
    default_path: str | Path = "config/default.toml",
) -> Config:
    """加载配置. default.toml 必读, override 可选(覆盖式合并)."""
    default = _read_toml(Path(default_path))
    sources = (str(default_path),)
    if override_path is not None:
        override = _read_toml(Path(override_path))
        merged = _deep_merge(default, override)
        sources = (str(default_path), str(override_path))
    else:
        merged = default
    return _parse(merged, sources)


if __name__ == "__main__":  # pragma: no cover
    # 命令行 smoke: python -m stub.config_loader [mvp]
    which = sys.argv[1] if len(sys.argv) > 1 else None
    cfg = load_config(f"config/{which}.toml" if which else None)
    print(f"loaded from: {cfg.source_files}")
    print(f"  brain.llm = {cfg.brain.llm_model}")
    print(f"  repair.strategy = {cfg.repair.strategy}")
    print(f"  monitor.port = {cfg.monitor.dashboard_port}")
