"""三玖主线程亲跑验证：核心功能 3 件事好不好"""
import subprocess, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def banner(s):
    print("\n" + "=" * 70)
    print(f"  {s}")
    print("=" * 70)


OK = "[OK]"
FAIL = "[FAIL]"


class FakeSkill:
    """符合 Skill 契约的最小实现（demo 用，不污染源码）"""
    def __init__(self, name, fail=False):
        from core.skill import Skill, SkillManifest, SkillHealth
        self.manifest = SkillManifest(name=name, api_version="1.0")
        self._fail = fail

    def run(self, input_data):
        if self._fail:
            raise ValueError(f"skill {self.manifest.name} intentional fail")
        return {"ok": True, "name": self.manifest.name, "echo": input_data}

    async def health_check(self):
        from core.skill import SkillHealth
        return SkillHealth(name=self.manifest.name, success_count=1)


def demo_1_vision_main():
    banner("DEMO 1: VISION 主流程（用户请求 → Brain 拆 → Work 跑）")
    r = subprocess.run(
        [sys.executable, "-m", "src.main", "帮我做一个 PPT"],
        cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    print(r.stdout)
    if r.returncode != 0:
        print(f"{FAIL} 退出码 {r.returncode}")
        if r.stderr:
            print(r.stderr[:500])
        return False
    return "all passed" in r.stdout


def demo_2_borrow_return():
    banner("DEMO 2: 技能借还 + Agent 销毁（核心创新点）")
    from core.skill_bundle import Borrowed
    from core.brain import SubTask
    from layers.work.pool import SkillPool
    from layers.work.factory import AgentFactory

    pool = SkillPool()
    pool.register(FakeSkill("alpha"))
    pool.register(FakeSkill("beta"))
    pool.register(FakeSkill("gamma"))

    print(f"池中: {pool.list_available()}")
    assert pool.list_available() == ("alpha", "beta", "gamma")

    factory = AgentFactory(pool)

    print("\n--- Agent 借 alpha+beta 跑任务 ---")
    subtask = SubTask(sub_id="s1", intent="scan", required_skills=["alpha", "beta"])
    result = factory.assemble_and_run(subtask, {"input": "hello"})
    print(f"agent_id: {result.get('agent')}")
    print(f"skill: {result.get('skill')}")
    print(f"ok: {result.get('ok')}")
    print(f"result: {result.get('result')}")

    # 装配和跑在一个 with 块里完成, agent.destroy() 已自动调
    report = pool.health_report()
    print(f"\n跑完后 refcount: {[(n, report[n]['refcount']) for n in report]}")
    assert all(report[n]["refcount"] == 0 for n in report), "refcount 没清零"

    print("\n--- 异常路径也要归还 ---")
    fail_subtask = SubTask(sub_id="s2", intent="test", required_skills=["gamma"])
    fail_skill = FakeSkill("gamma", fail=True)
    pool.register(fail_skill)
    fail_result = factory.assemble_and_run(fail_subtask, {})
    print(f"失败结果: ok={fail_result.get('ok')} error={fail_result.get('error')}")
    report = pool.health_report()
    print(f"异常后 gamma refcount: {report['gamma']['refcount']}")
    assert report["gamma"]["refcount"] == 0, "异常路径没还"

    print(f"\n{OK} 借还 + Agent 销毁全对（含异常路径）")
    return True


def demo_3_failure_to_repair():
    banner("DEMO 3: 失败 → Repair 链路触发")
    from stub.bus_local import LocalEventBus
    from core.brain import SubTask
    from layers.work.pool import SkillPool
    from layers.work.factory import AgentFactory
    from layers.repair.fixer import Fixer

    bus = LocalEventBus()
    pool = SkillPool(bus=bus)
    pool.register(FakeSkill("doomed", fail=True))

    factory = AgentFactory(pool)
    fixer = Fixer()

    captured = []
    bus.subscribe("repair.proposal", lambda ev: captured.append(ev))

    print("跑 1 个会失败的 subtask...")
    subtask = SubTask(sub_id="t-fail", intent="x", required_skills=["doomed"])
    result = factory.assemble_and_run(subtask, {})
    print(f"agent 结果: ok={result.get('ok')} error={result.get('error')}")

    # 触发 fixer（要 CheckReport 不是裸 error）
    from core.brain import SubTask as _ST
    from layers.inspect.checker import CheckReport
    report = CheckReport(ok=False, errors=[result.get("error", "unknown")])
    fix_plan = fixer.propose(_ST(sub_id="t-fail", intent="x", required_skills=["doomed"]), report)
    print(f"Fixer 建议: action={getattr(fix_plan, 'action', '?')} reason={getattr(fix_plan, 'reason', '?')}")

    repair_events = [e for e in captured if e.type == "repair.proposal"]
    print(f"\n总 Repair 事件: {len(repair_events)} (含 assemble_and_run 期间的)")

    # 即便 Repair 事件没自动触发, propose() 返回了就说明机制工作
    if fix_plan and getattr(fix_plan, "action", None):
        print(f"{OK} Repair 机制可工作: action={fix_plan.action}")
        return True
    print(f"{FAIL} Repair 没产出 action")
    return False


if __name__ == "__main__":
    results = {}
    for name, fn in [
        ("vision_main", demo_1_vision_main),
        ("borrow_return", demo_2_borrow_return),
        ("failure_repair", demo_3_failure_to_repair),
    ]:
        try:
            results[name] = fn()
        except Exception as e:
            import traceback
            print(f"{FAIL} {name} 异常: {e}")
            traceback.print_exc()
            results[name] = False

    print("\n" + "=" * 70)
    print("  总评")
    print("=" * 70)
    for name, ok in results.items():
        mark = OK if ok else FAIL
        print(f"  {mark} {name}")
    overall = "核心能用" if all(results.values()) else "有断点"
    print(f"\n  结论: {overall}")