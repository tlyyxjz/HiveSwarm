"""SkillAdmission — 技能准入闸门 (M4).

问题: 技能一旦来自外部(第三方 pip 包 / GitHub 仓库 / 用户上传), **它本身就是
不可信输入**. 主流做法是"先装上, 事后扫一遍"; 本层是"扫过了才装上".

与 Bandit / Semgrep 的关系(说清楚, 免得被当成重复造轮子):
  1. **能复用的复用了**: 危险模式规则的编号直接对齐 Bandit (B102/B301/B307/
     B602/B603/B506/...), 语义一致. 将来把 Bandit 当后端接进来即可, 本层的
     规则接口不用改(见 docs/任务单_T16).
  2. **不复用的部分, 是三条本层才需要的行为**:
     - Bandit 允许被扫对象用 `# nosec` 自我豁免 -> 外部技能不能有这种权力,
       否则恶意技能加一行注释就过闸. 本层把"出现自我豁免标记"**记成 findings**.
     - Bandit 是 CLI 报告工具, 扫完不拦谁. 本层是闸门: `register_if_admitted()`
       是技能进池的唯一入口, 非 ALLOW 直接 raise.
     - Bandit 崩了就没有报告, 调用方很容易读成"没问题". 本层 fail-closed:
       扫描器异常 -> QUARANTINE, 不是 ALLOW.

裁决三态:
  ALLOW       -> 可注册进池
  QUARANTINE  -> 留观, 需人工审, 不进池
  DENY        -> 拒绝, 不进池

依赖方向: admission -> core.skill + core.events (只读); 不 import discovery /
pool 的运行时对象(用 TYPE_CHECKING + 结构化入参), 避免与 work 层成环。
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from core.skill import Skill

if TYPE_CHECKING:
    from core.events import EventBus
    from layers.work.pool import SkillPool

_log = logging.getLogger(__name__)

# 本层认定的核心契约版本。技能的 api_version 主版本必须与之一致。
SUPPORTED_API_MAJOR = "1"

# 扫描规模上限: 防"塞一个 2GB 文件把闸门拖死"这种低成本 DoS。
_MAX_FILE_BYTES = 512 * 1024
_MAX_FILES = 200

# 只做文本类检查的扩展名; 代码规则只扫 _CODE_EXTS。
_TEXT_EXTS = frozenset(
    {".py", ".md", ".toml", ".json", ".txt", ".sh", ".cfg", ".ini", ".yaml", ".yml"}
)
_CODE_EXTS = frozenset({".py", ".sh"})


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(str, Enum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    DENY = "deny"


class TrustLevel(str, Enum):
    """来源可信度。决定同一批 findings 落到哪个 verdict。"""

    FIRST_PARTY = "first_party"  # 本仓库 skills/ 下的包, 已进版本控制、被人看过
    SIGNED = "signed"  # 带校验和/签名的已审包
    UNVERIFIED = "unverified"  # GitHub 搜到的 / 用户上传的, 没人看过


# 严重度 x 可信度 -> 裁决。表驱动, 不写 if 瀑布。
_DEFAULT_POLICY: dict[TrustLevel, dict[Severity, Verdict]] = {
    TrustLevel.FIRST_PARTY: {
        Severity.CRITICAL: Verdict.DENY,
        Severity.HIGH: Verdict.DENY,
        Severity.MEDIUM: Verdict.ALLOW,
        Severity.LOW: Verdict.ALLOW,
    },
    TrustLevel.SIGNED: {
        Severity.CRITICAL: Verdict.DENY,
        Severity.HIGH: Verdict.QUARANTINE,
        Severity.MEDIUM: Verdict.ALLOW,
        Severity.LOW: Verdict.ALLOW,
    },
    TrustLevel.UNVERIFIED: {
        Severity.CRITICAL: Verdict.DENY,
        Severity.HIGH: Verdict.DENY,
        Severity.MEDIUM: Verdict.QUARANTINE,
        Severity.LOW: Verdict.ALLOW,
    },
}


class SkillNotAdmittedError(RuntimeError):
    """技能没过准入闸门, 拒绝注册。带完整报告, 便于排障与审计。"""

    def __init__(self, report: AdmissionReport) -> None:
        self.report = report
        rules = ", ".join(sorted({f.rule_id for f in report.findings})) or "none"
        super().__init__(
            f"skill {report.subject_name!r} not admitted: verdict={report.verdict.value} "
            f"(trust={report.trust.value}, rules={rules})"
        )


# ── 数据模型 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    """一条命中。rule_id 对齐 Bandit 编号(可直接类比查文档), HS-* 是本层自有规则。"""

    rule_id: str
    severity: Severity
    message: str
    file: str = ""
    line: int = 0
    evidence: str = ""  # 命中原文片段(截断), 让人不用点开文件就能判断

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "evidence": self.evidence,
        }


@dataclass
class AdmissionSubject:
    """被审对象。这是本层对外的唯一入参形态 —— 不依赖 discovery 的类型。

    discovery 把候选转成 subject 再送进来, 依赖方向因此是单向的。
    """

    name: str
    trust: TrustLevel = TrustLevel.UNVERIFIED
    source_root: Path | None = None  # 技能包根目录(本地包 / 已下载到本地)
    source_kind: str = "inline"  # local_pack | github_repo | inline
    remote_url: str = ""
    manifest: dict = field(default_factory=dict)
    declared_api_version: str = ""
    declared_min_core_version: str = "0.0.0"

    @classmethod
    def from_pack_dir(
        cls,
        root: Path,
        *,
        trust: TrustLevel = TrustLevel.UNVERIFIED,
        source_kind: str = "local_pack",
    ) -> AdmissionSubject:
        """从技能包目录建 subject。manifest.toml 解析失败不抛 —— 交给规则判它。"""
        manifest = _read_manifest(root)
        pack = manifest.get("pack", {}) if isinstance(manifest, dict) else {}
        return cls(
            name=str(pack.get("name") or root.name),
            trust=trust,
            source_root=Path(root),
            source_kind=source_kind,
            manifest=manifest,
            declared_api_version=str(pack.get("api_version", "")),
            declared_min_core_version=str(pack.get("min_core_version", "0.0.0")),
        )


# 有些技能包会在 manifest.toml 顶部写一行 `"""说明"""` —— 那不是合法 TOML,
# 但它是**书写习惯**而不是**风险信号**, 所以剥离后再解析(本仓库自己的 3 个包
# 就是这么写的, 见 docs/任务单_T16 交付说明). 剥离条件收得很紧: 只有"独占一行
# 且整行仅一段三引号"才动; 真写坏的 manifest 依然要报出来, 不能被容忍吞掉.
_PREAMBLE_RE = re.compile(r'^[ \t]*"""[^"]*"""[ \t]*\r?\n')


def _read_manifest(root: Path) -> dict:
    """读 manifest.toml。失败返回空 dict(由规则报缺失, 不在读取层抛)。"""
    path = Path(root) / "manifest.toml"
    if not path.is_file():
        return {}
    try:
        try:
            import tomllib
        except ModuleNotFoundError:  # py3.10
            import tomli as tomllib  # type: ignore[no-redef]

        text = path.read_text(encoding="utf-8", errors="replace")
        stripped = _PREAMBLE_RE.sub("", text, count=1)
        if stripped != text:
            _log.info("stripped non-TOML preamble line from %s", path)
        data = tomllib.loads(stripped)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        _log.warning("manifest parse failed for %s: %s", root, exc)
        return {}


@dataclass
class AdmissionReport:
    """判决书。每条 verdict 都必须能追到 findings, 不留"凭感觉拒绝"。"""

    subject_name: str
    verdict: Verdict
    trust: TrustLevel
    findings: tuple[Finding, ...] = ()
    scanner_status: dict[str, str] = field(default_factory=dict)
    files_scanned: int = 0
    skipped: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def max_severity(self) -> Severity | None:
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        found = [f.severity for f in self.findings]
        return max(found, key=order.index) if found else None

    def to_dict(self) -> dict:
        return {
            "subject": self.subject_name,
            "verdict": self.verdict.value,
            "trust": self.trust.value,
            "files_scanned": self.files_scanned,
            "skipped": list(self.skipped),
            "scanner_status": dict(self.scanner_status),
            "findings": [f.to_dict() for f in self.findings],
        }


# ── 规则 ─────────────────────────────────────────────────────────────────


class AdmissionRule(ABC):
    """一条准入规则。evaluate 返回 findings; 抛异常 = 闸门自己坏了, 由 Gate 兜底。"""

    rule_id: str = "HS-000"

    @abstractmethod
    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        """返回命中的 findings。空列表 = 本条通过。"""


@dataclass
class ScanContext:
    """扫描期缓存。文件只读一次, 规则之间共享, 避免每条规则都去 walk 目录。"""

    root: Path | None
    files: list[Path] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, root: Path | None) -> ScanContext:
        ctx = cls(root=None)
        if root is None:
            return ctx
        root = Path(root)
        if not root.is_dir():
            ctx.skipped.append(f"source_root not a directory: {root}")
            return ctx
        ctx.root = root.resolve()
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            # symlink 逃逸: resolve 后仍须在 root 之内, 否则不读(防读系统文件)。
            # 平台差异(2026-09-25 实测): Windows 非开发者模式下 symlink_to 会返回成功,
            # 但生成的是"哑链接"(is_file() 为 False, rglob 也不列出) —— 该平台上这个
            # 攻击面不存在; 这条检查是给 POSIX 兜底的, 不能省。
            try:
                real = p.resolve()
            except OSError:
                ctx.skipped.append(f"unresolvable: {p}")
                continue
            if not real.is_relative_to(ctx.root):
                ctx.skipped.append(f"symlink escape: {p}")
                continue
            if p.suffix.lower() not in _TEXT_EXTS:
                continue
            if len(ctx.files) >= _MAX_FILES:
                ctx.skipped.append(f"file cap reached ({_MAX_FILES}); rest not scanned")
                break
            try:
                if real.stat().st_size > _MAX_FILE_BYTES:
                    ctx.skipped.append(f"oversize: {p}")
                    continue
                ctx.texts[str(p.relative_to(root))] = real.read_text(
                    encoding="utf-8", errors="replace"
                )
                ctx.files.append(p)
            except OSError as exc:
                ctx.skipped.append(f"unreadable: {p} ({exc})")
        return ctx

    def iter_texts(self, exts: frozenset[str] | None = None) -> list[tuple[str, str]]:
        if exts is None:
            return list(self.texts.items())
        return [(f, t) for f, t in self.texts.items() if Path(f).suffix.lower() in exts]


class ManifestIntegrityRule(AdmissionRule):
    """manifest 该有的都得有。缺失字段的技能无法被安全地当作依赖装配。"""

    rule_id = "HS-001"

    _NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        pack = subject.manifest.get("pack", {}) if isinstance(subject.manifest, dict) else {}
        if not subject.manifest:
            out.append(
                Finding(
                    self.rule_id,
                    Severity.HIGH,
                    "缺少 manifest.toml(或无 [pack] 段), 无法判定版本与用途",
                    file="manifest.toml",
                )
            )
            return out
        for key, sev in (("name", Severity.HIGH), ("api_version", Severity.HIGH),
                         ("description", Severity.LOW)):
            if not str(pack.get(key, "")).strip():
                out.append(
                    Finding(self.rule_id, sev, f"manifest [pack].{key} 缺失或为空", "manifest.toml")
                )
        name = str(pack.get("name", ""))
        if name and not self._NAME_RE.match(name):
            out.append(
                Finding(
                    self.rule_id,
                    Severity.MEDIUM,
                    f"manifest name 不符合命名约束(仅 [A-Za-z0-9_.-], <=64): {name!r}",
                    "manifest.toml",
                )
            )
        return out


class ApiCompatibilityRule(AdmissionRule):
    """版本不兼容的技能装进来会以运行时错误的形式炸在别处, 所以拦在准入。"""

    rule_id = "HS-002"

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        ver = subject.declared_api_version.strip()
        if not ver:
            return out  # 缺失由 HS-001 报, 不重复计
        major = ver.split(".")[0]
        if major != SUPPORTED_API_MAJOR:
            out.append(
                Finding(
                    self.rule_id,
                    Severity.HIGH,
                    f"api_version 主版本不匹配: 技能声明 {ver}, 核心支持 {SUPPORTED_API_MAJOR}.x",
                    "manifest.toml",
                )
            )
        min_core = subject.declared_min_core_version.strip()
        if min_core and min_core != "0.0.0" and _parse_version(min_core) > _parse_version("0.1.0"):
            out.append(
                Finding(
                    self.rule_id,
                    Severity.MEDIUM,
                    f"技能要求 min_core_version >= {min_core}, 高于当前核心 0.1.0",
                    "manifest.toml",
                )
            )
        return out


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in v.split("."):
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts) or (0,)


class DangerousCallRule(AdmissionRule):
    """危险调用/字面量。rule_id 对齐 Bandit, 便于直接查上游文档解释严重度。"""

    rule_id = "HS-003"

    # (bandit rule_id, 正则, 严重度, 说明)
    PATTERNS: tuple[tuple[str, str, Severity, str], ...] = (
        ("B102", r"\bexec\s*\(", Severity.CRITICAL, "exec() 执行动态构造的代码"),
        ("B307", r"(?<![\w.])eval\s*\(", Severity.CRITICAL, "eval() 执行动态构造的代码"),
        ("B301", r"\bpickle\.loads?\s*\(", Severity.CRITICAL, "pickle 反序列化可执行任意代码"),
        ("B602", r"shell\s*=\s*True", Severity.HIGH, "subprocess shell=True, 有命令注入面"),
        ("B603", r"\bos\.system\s*\(", Severity.HIGH, "os.system 直接把字符串交给 shell"),
        ("B604", r"\bos\.popen\s*\(", Severity.HIGH, "os.popen 直接把字符串交给 shell"),
        ("B506", r"\byaml\.load\s*\((?!\s*[^)]*Loader)", Severity.MEDIUM,
         "yaml.load 未指定 SafeLoader"),
        ("B105", r"(?i)\b(password|passwd|secret|api_key|apikey|access_token)\s*=\s*"
                 r"[\"'][^\"'\s]{6,}[\"']", Severity.MEDIUM, "硬编码凭据字符串"),
        ("B310", r"\burllib\.request\.urlopen\s*\(", Severity.LOW, "urllib 直接外联(单独出现仅记录)"),
        ("B108", r"[\"']/tmp/[\w./-]*[\"']", Severity.LOW, "硬编码 /tmp 路径, 多租户下会互相踩"),
        ("B324", r"\b(?:hashlib\.)?(?:md5|sha1)\s*\(", Severity.LOW, "已破哈希算法"),
        ("B322", r"(?<![\w.])input\s*\(", Severity.LOW, "input() 读取 stdin(agent 场景下语义可疑)"),
    )

    def __init__(self) -> None:
        self._compiled = [
            (rid, re.compile(pat), sev, msg) for rid, pat, sev, msg in self.PATTERNS
        ]

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        for fname, text in ctx.iter_texts(_CODE_EXTS):
            for rid, rx, sev, msg in self._compiled:
                for m in rx.finditer(text):
                    out.append(
                        Finding(
                            rid,
                            sev,
                            msg,
                            file=fname,
                            line=text.count("\n", 0, m.start()) + 1,
                            evidence=_clip(text, m.start(), m.end()),
                        )
                    )
        return out


class ExfiltrationRule(AdmissionRule):
    """单看"读文件"或"发 HTTP"都正常; 同一文件里两者同时出现才判重。

    这条是本层比逐条正则更强的理由: 判定的是**能力组合**, 不是孤立 token。

    ⚠️ 口径必须精确: 裸 `os.environ` / `getenv()` 不算凭据来源 —— 设代理变量
    (`os.environ.pop("NO_PROXY")`) 也会命中, 那是误报. 只认两种真信号:
      ① 敏感**文件**路径(.ssh/id_rsa/.aws/credentials/.env/...)
      ② 名字里带凭据语义的**环境变量**(environ["GITHUB_TOKEN"] / getenv("..._SECRET"))
    """

    rule_id = "HS-010"

    _SENSITIVE_FILE = re.compile(
        r"(?i)(\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.aws/config|\.npmrc|"
        r"\.pypirc|\.git-credentials|\.netrc|/etc/shadow|\.docker/config\.json|"
        r"[/\\\"']\.env\b)"
    )
    _ENV_SECRET = re.compile(
        r"(?i)(?:environ(?:\.get)?\s*[\(\[]\s*|getenv\s*\(\s*)"
        r"[\"'][^\"']*(?:secret|token|api[_-]?key|password|passwd|credential|private)[^\"']*[\"']"
    )
    _SINKS = re.compile(
        r"(?i)(httpx\.|requests\.(get|post|put)|urllib\.request|urlopen\s*\(|"
        r"socket\.socket|paramiko\.|ftplib\.|smtplib\.)"
    )

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        for fname, text in ctx.iter_texts(_CODE_EXTS):
            if not self._SINKS.search(text):
                continue
            hits = [
                m
                for m in (self._SENSITIVE_FILE.search(text), self._ENV_SECRET.search(text))
                if m is not None
            ]
            if not hits:
                continue
            first = min(hits, key=lambda m: m.start())
            out.append(
                Finding(
                    self.rule_id,
                    Severity.CRITICAL,
                    "同一文件内同时出现『读取凭据(敏感文件路径 / 具名密钥环境变量)』与"
                    "『网络外联』两个能力 —— 这是数据外泄的最小充分条件",
                    file=fname,
                    line=text.count("\n", 0, first.start()) + 1,
                    evidence=_clip(text, first.start(), first.end()),
                )
            )
        return out


class TrojanSourceRule(AdmissionRule):
    """Trojan Source (CVE-2021-42574): 双向控制符能让源码在编辑器里显示成另一回事。

    对"技能是会被执行的指令"这个前提来说, 这是最直接的一类攻击:
    你在评审里看到的是注释, 执行的是另一段代码。Bandit 对应 B613。
    """

    rule_id = "B613"

    _BIDI = re.compile("[\u202a-\u202e\u2066-\u2069\u061c]")

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        for fname, text in ctx.iter_texts():
            for m in self._BIDI.finditer(text):
                cp = ord(m.group())
                out.append(
                    Finding(
                        self.rule_id,
                        Severity.CRITICAL,
                        f"含双向排版控制符 U+{cp:04X}(Trojan Source 类攻击), "
                        f"源码显示与实际执行可能不一致",
                        file=fname,
                        line=text.count("\n", 0, m.start()) + 1,
                        evidence=f"U+{cp:04X}",
                    )
                )
                break  # 一个文件报一条就够, 不刷屏
        return out


class InvisibleCharRule(AdmissionRule):
    """零宽字符/异常编码。多数是脏排版, 但可以用来藏标识符, 记低危。"""

    rule_id = "HS-014"

    _INVISIBLE = re.compile("[\u200b-\u200f\u2028\u2029\ufeff]")

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        for fname, text in ctx.iter_texts():
            body = text[1:] if text.startswith("\ufeff") else text  # 文件首 BOM 是编码问题
            m = self._INVISIBLE.search(body)
            if m is None:
                continue
            out.append(
                Finding(
                    self.rule_id,
                    Severity.LOW,
                    f"含不可见字符 U+{ord(m.group()):04X}(可能只是脏排版, 也可能用于隐藏标识符)",
                    file=fname,
                    line=body.count("\n", 0, m.start()) + 1,
                    evidence=f"U+{ord(m.group()):04X}",
                )
            )
        return out


class SelfExemptionRule(AdmissionRule):
    """⛔ 被审对象不得自我豁免 —— 这是本层与 Bandit 最重要的行为差异。

    Bandit 里 `# nosec` 是给**仓库作者**表达"我确认这条是误报"的。
    但在准入层的语境下, 技能作者 == 不可信方: 允许自我豁免等于允许
    "写一行注释就能把任意 CRITICAL 规则关掉"。所以这里反过来,
    把出现豁免标记本身记成 HIGH —— 你越想关掉检查, 我越要人工看一眼。
    """

    rule_id = "HS-011"

    _MARKERS = re.compile(
        r"(?i)(#\s*nosec|#\s*hiveswarm\s*:\s*allow|#\s*admission\s*:\s*(skip|ignore|allow)|"
        r"admission_skip|SKIP_ADMISSION)"
    )

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        for fname, text in ctx.iter_texts():
            for m in self._MARKERS.finditer(text):
                out.append(
                    Finding(
                        self.rule_id,
                        Severity.HIGH,
                        "含检查豁免标记。准入层不接受被审对象自我豁免"
                        "(即使内容本身无害, 也需人工确认后手工放行)",
                        file=fname,
                        line=text.count("\n", 0, m.start()) + 1,
                        evidence=_clip(text, m.start(), m.end()),
                    )
                )
        return out


class WriteOutsideSandboxRule(AdmissionRule):
    """写技能包目录之外的文件系统路径 —— 技能之间会互相污染, 且绕开借还边界。"""

    rule_id = "HS-012"

    _WRITE = re.compile(
        r"(?i)(open\s*\(\s*[\"'](/(?!tmp/)|[A-Za-z]:[\\/])[^\"']*[\"']\s*,\s*[\"'][wa])"
        r"|(\bshutil\.rmtree\s*\(\s*[\"'](/(?!tmp/)|[A-Za-z]:[\\/]))"
        r"|(\bos\.remove\s*\(\s*[\"'](/(?!tmp/)|[A-Za-z]:[\\/]))"
    )

    def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
        out: list[Finding] = []
        for fname, text in ctx.iter_texts(_CODE_EXTS):
            for m in self._WRITE.finditer(text):
                out.append(
                    Finding(
                        self.rule_id,
                        Severity.HIGH,
                        "写/删技能包目录之外的绝对路径, 会绕过借还边界污染其它任务",
                        file=fname,
                        line=text.count("\n", 0, m.start()) + 1,
                        evidence=_clip(text, m.start(), m.end()),
                    )
                )
        return out


def _clip(text: str, start: int, end: int, width: int = 120) -> str:
    """截一小段原文做证据, 单行化, 防把整份文件塞进报告。"""
    seg = text[start:end][:width].replace("\n", "\\n").replace("\r", "")
    return seg


def _all_builtin_rules() -> list[AdmissionRule]:
    return [
        ManifestIntegrityRule(),
        ApiCompatibilityRule(),
        DangerousCallRule(),
        TrojanSourceRule(),
        ExfiltrationRule(),
        SelfExemptionRule(),
        WriteOutsideSandboxRule(),
        InvisibleCharRule(),
    ]


# ── 可选后端: agentvet ────────────────────────────────────────────────────


class AgentVetBridge:
    """把已有的 agentvet 扫描器接进闸门(装了就用, 没装就如实记 skipped)。

    复用 > 重造: agentvet 已经是本仓库的技能包之一(skills/agentvet_pack),
    这里只做适配 —— 把它的 findings 翻译成本层的 Finding。
    """

    name = "agentvet"

    def __init__(self) -> None:
        self._engine_cls: object | None = None
        self._error: str = ""

    @property
    def available(self) -> bool:
        return self._engine_cls is not None

    def probe(self) -> bool:
        """探测 agentvet 是否可导入。失败不抛, 记下原因。"""
        try:
            from scanner.engine import ScanEngine  # type: ignore[import-not-found]

            self._engine_cls = ScanEngine
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            return False

    def scan(self, root: Path) -> list[Finding]:
        """跑 L1 扫描。调用方负责 try/except —— 这里不吞异常, 让 Gate 做 fail-closed。"""
        if self._engine_cls is None:
            raise RuntimeError(f"agentvet unavailable: {self._error}")
        engine = self._engine_cls(use_l2=False, use_l3=False, use_l4=False)  # type: ignore[operator]
        report = engine.scan(str(root))
        out: list[Finding] = []
        for f in getattr(report, "findings", []) or []:
            sev_raw = str(getattr(f, "severity", "")).lower()
            sev = {
                "critical": Severity.CRITICAL,
                "high": Severity.HIGH,
                "error": Severity.HIGH,
                "medium": Severity.MEDIUM,
                "warning": Severity.MEDIUM,
                "low": Severity.LOW,
                "info": Severity.LOW,
            }.get(sev_raw, Severity.MEDIUM)
            rid = str(getattr(f, "rule_id", "") or "AV-000")
            out.append(
                Finding(
                    rid,
                    sev,
                    f"[agentvet] {getattr(f, 'message', str(f))}",
                    file=str(getattr(f, "file", "") or ""),
                    line=int(getattr(f, "line", 0) or 0),
                )
            )
        return out


# ── 闸门 ─────────────────────────────────────────────────────────────────


class AdmissionGate:
    """准入闸门。技能进池的唯一入口是 register_if_admitted()。

    记账: 每次判决 append-only 落内存(可选同时落 JSONL), 判决可回放可审计。
    """

    def __init__(
        self,
        rules: list[AdmissionRule] | None = None,
        *,
        bus: EventBus | None = None,
        policy: dict[TrustLevel, dict[Severity, Verdict]] | None = None,
        ledger_path: Path | str | None = None,
        use_agentvet: bool = True,
    ) -> None:
        self._rules = list(rules) if rules is not None else _all_builtin_rules()
        self._bus = bus
        self._policy = policy or _DEFAULT_POLICY
        self._records: list[dict] = []
        self._ledger_path = Path(ledger_path) if ledger_path else None
        self._agentvet = AgentVetBridge()
        self._agentvet_probed = False
        self._use_agentvet = use_agentvet

    # ── 判决 ─────────────────────────────────────────────────────────────

    def evaluate(self, subject: AdmissionSubject) -> AdmissionReport:
        """纯判决: 跑规则 -> 聚合。不写账、不发事件, 便于单测。"""
        ctx = ScanContext.build(subject.source_root)
        findings: list[Finding] = []
        status: dict[str, str] = {"builtin": "ok"}

        for rule in self._rules:
            try:
                findings.extend(rule.evaluate(subject, ctx))
            except Exception as exc:  # noqa: BLE001
                # fail-closed: 规则自己崩了, 当作"没查成", 而不是"没问题"
                status[rule.rule_id] = f"error: {type(exc).__name__}: {exc}"
                findings.append(
                    Finding(
                        rule.rule_id,
                        Severity.HIGH,
                        f"准入规则执行失败({type(exc).__name__}), 结果不可信, 按 fail-closed 处理",
                    )
                )

        status.update(self._run_agentvet(subject, findings, ctx))

        verdict = self._decide(subject.trust, findings)
        report = AdmissionReport(
            subject_name=subject.name,
            verdict=verdict,
            trust=subject.trust,
            findings=tuple(findings),
            scanner_status=status,
            files_scanned=len(ctx.texts),
            skipped=tuple(ctx.skipped),
        )
        return report

    def _run_agentvet(
        self, subject: AdmissionSubject, findings: list[Finding], ctx: ScanContext
    ) -> dict[str, str]:
        if not self._use_agentvet or ctx.root is None:
            return {}
        if not self._agentvet_probed:
            self._agentvet.probe()
            self._agentvet_probed = True
        if not self._agentvet.available:
            return {"agentvet": "skipped: not installed"}
        try:
            findings.extend(self._agentvet.scan(ctx.root))
            return {"agentvet": "ok"}
        except Exception as exc:  # noqa: BLE001
            findings.append(
                Finding(
                    "HS-900",
                    Severity.HIGH,
                    f"agentvet 扫描异常({type(exc).__name__}: {exc}), 深层结果缺失, "
                    f"按 fail-closed 处理",
                )
            )
            return {"agentvet": f"error: {type(exc).__name__}"}

    def _decide(self, trust: TrustLevel, findings: list[Finding]) -> Verdict:
        """表驱动聚合。取**最严**的一条: 只要有 CRITICAL 就是 DENY, 不被 LOW 稀释。"""
        table = self._policy.get(trust, _DEFAULT_POLICY[TrustLevel.UNVERIFIED])
        worst: Verdict | None = None
        rank = {Verdict.ALLOW: 0, Verdict.QUARANTINE: 1, Verdict.DENY: 2}
        for f in findings:
            v = table.get(f.severity, Verdict.QUARANTINE)
            if worst is None or rank[v] > rank[worst]:
                worst = v
        if worst is None:
            return Verdict.ALLOW
        return worst

    # ── 记账 + 发事件 ────────────────────────────────────────────────────

    def admit(self, subject: AdmissionSubject) -> AdmissionReport:
        """判决 + 落账 + 发事件。对外主入口。"""
        report = self.evaluate(subject)
        record = {"type": "admission.verdict", **report.to_dict()}
        self._records.append(record)
        if self._ledger_path is not None:
            self._append_ledger(record)
        self._emit(report)
        if not report.allowed:
            _log.warning(
                "skill %s not admitted: %s (%d findings)",
                report.subject_name,
                report.verdict.value,
                len(report.findings),
            )
        return report

    def _append_ledger(self, record: dict) -> None:
        """append-only JSONL。写失败只告警 —— 审计失败不该让判决本身失效。"""
        assert self._ledger_path is not None
        try:
            import json

            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            _log.warning("admission ledger append failed", exc_info=True)

    def records(self) -> tuple[dict, ...]:
        """判决流水(只读快照), 给看板/审计用。"""
        return tuple(self._records)

    def _emit(self, report: AdmissionReport) -> None:
        if self._bus is None:
            return
        try:
            from core.events import Event, EventType

            self._bus.publish(
                Event(
                    type=EventType.SKILL_ADMISSION_VERDICT,
                    payload={
                        "name": report.subject_name,
                        "verdict": report.verdict.value,
                        "trust": report.trust.value,
                        "findings": len(report.findings),
                        "rules": sorted({f.rule_id for f in report.findings}),
                    },
                )
            )
        except Exception:  # noqa: BLE001
            _log.warning("emit admission event failed", exc_info=True)

    # ── 唯一注册入口 ────────────────────────────────────────────────────

    def register_if_admitted(
        self,
        pool: SkillPool,
        subject: AdmissionSubject,
        factory: Callable[[], Skill],
    ) -> Skill:
        """过闸才注册。不过闸抛 SkillNotAdmittedError, 不返回半成品。

        `factory` 而不是 skill 实例: 判决失败时连对象都不构造, 不给"构造过程
        已经产生副作用"的机会。
        """
        report = self.admit(subject)
        if not report.allowed:
            raise SkillNotAdmittedError(report)
        skill = factory()
        pool.register(skill)
        return skill
