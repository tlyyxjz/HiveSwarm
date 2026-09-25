"""work 层 —— 技能池 / 借还 / 装配 / 发现 / 准入.

M4 SkillAdmission : 技能进池前的准入闸门(fail-closed, 唯一注册入口)
M5 SkillDiscovery : 运行时技能发现(候选区 -> 筛查 -> 装配)

导入顺序注意: admission 不依赖 discovery; discovery 依赖 admission (单向).
"""
from layers.work.admission import (
    AdmissionGate,
    AdmissionReport,
    AdmissionRule,
    AdmissionSubject,
    Finding,
    ScanContext,
    Severity,
    SkillNotAdmittedError,
    TrustLevel,
    Verdict,
)
from layers.work.discovery import (
    DiscoveryResult,
    EntryPointSource,
    GitHubRepoSource,
    LocalPackSource,
    PoolSource,
    ScoredCandidate,
    ScreeningOutcome,
    SearchQuery,
    SkillCandidate,
    SkillDiscovery,
    SkillSource,
    build_default_discovery,
    score_candidate,
)

__all__ = [
    # admission
    "AdmissionGate",
    "AdmissionReport",
    "AdmissionRule",
    "AdmissionSubject",
    "Finding",
    "ScanContext",
    "Severity",
    "SkillNotAdmittedError",
    "TrustLevel",
    "Verdict",
    # discovery
    "DiscoveryResult",
    "EntryPointSource",
    "GitHubRepoSource",
    "LocalPackSource",
    "PoolSource",
    "ScoredCandidate",
    "ScreeningOutcome",
    "SearchQuery",
    "SkillCandidate",
    "SkillDiscovery",
    "SkillSource",
    "build_default_discovery",
    "score_candidate",
]
