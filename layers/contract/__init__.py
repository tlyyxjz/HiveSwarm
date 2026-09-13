"""contract — 榫卯三机制的核心包 (M1 断言契约层起步).

依赖方向约束: contract → core / layers.inspect (只读 validator 原语),
不 import repair / work / monitor (防止循环, 见 docs/榫卯改造方案.md).
"""
from layers.contract.assertion import (
    VALIDATOR_NAMES,
    Assertion,
    AssertionKind,
    AssertionOrigin,
    AssertionStatus,
    build_predicate,
)
from layers.contract.compiler import (
    AssertionCompiler,
    CandidateAssertion,
    CandidateConstraint,
    CompileReport,
    Rejection,
)
from layers.contract.ledger import (
    AssertionLedger,
    EdgeType,
    FalsificationRecord,
)

__all__ = [
    "VALIDATOR_NAMES",
    "Assertion",
    "AssertionKind",
    "AssertionOrigin",
    "AssertionStatus",
    "build_predicate",
    "AssertionCompiler",
    "CandidateAssertion",
    "CandidateConstraint",
    "CompileReport",
    "Rejection",
    "AssertionLedger",
    "EdgeType",
    "FalsificationRecord",
]
