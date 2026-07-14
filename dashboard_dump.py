"""Dump 9 个 Tab 的实际渲染结果（不打 Gradio，直接调 _render_xxx）"""
import os
os.environ['NO_PROXY'] = '*'
import sys
sys.path.insert(0, '.')

from stub.dashboard_gradio import GradioDashboard
from stub.bus_local import LocalEventBus
from layers.work.pool import SkillPool
from core.events import Event, EventType
from core.skill import Skill, SkillManifest, SkillHealth
from stub.store_sqlite import SQLiteStore
from layers.memory.store import MemoryStore, MemoryTier
import time


class DemoSkill(Skill):
    def __init__(self, name, fail=False, slow=False):
        super().__init__(SkillManifest(name=name, api_version='1.0', description=f'demo {name}'))
        self._fail = fail
        self._slow = slow
        self.run_count = 0
    def run(self, input_data):
        self.run_count += 1
        if self._fail:
            raise ValueError(f'{self.manifest.name} simulated failure')
        return {'ok': True, 'name': self.manifest.name, 'echo': input_data}
    async def health_check(self):
        return SkillHealth(name=self.manifest.name, success_count=self.run_count)


bus = LocalEventBus()
pool = SkillPool(bus=bus)
pool.register(DemoSkill('agentvet_l1'))
pool.register(DemoSkill('agentvet_l2'))
pool.register(DemoSkill('ppt_export'))
pool.register(DemoSkill('crawler_fetch', fail=True))

db_path = os.path.expanduser('~/.hiveswarm/dashboard_demo.db')
os.makedirs(os.path.dirname(db_path), exist_ok=True)
if os.path.exists(db_path):
    os.remove(db_path)
mem = MemoryStore(SQLiteStore(db_path))

# 多塞数据让每个 Tab 都丰满
events = [
    Event(type=EventType.TASK_STARTED, payload={'task_id': 't-1001', 'rationale': 'agentvet 扫描 github.com/anthropics', 'subtasks': [1,2,3,4]}),
    Event(type=EventType.TASK_STARTED, payload={'task_id': 't-1002', 'rationale': '制作 2026Q3 战略 PPT', 'subtasks': [1,2,3,4,5]}),
    Event(type=EventType.TASK_STARTED, payload={'task_id': 't-1003', 'rationale': '竞品分析：6 家公司', 'subtasks': [1,2,3]}),
    Event(type=EventType.SKILL_CHECKED_OUT, payload={'names': ['agentvet_l1']}),
    Event(type=EventType.AGENT_ASSEMBLED, payload={'agent_id': 'agent-aaa111'}),
    Event(type=EventType.TASK_COMPLETED, payload={'task_id': 't-1001'}),
    Event(type=EventType.TASK_COMPLETED, payload={'task_id': 't-1002'}),
    Event(type=EventType.SKILL_RETURNED, payload={'names': ['agentvet_l1']}),
    Event(type=EventType.AGENT_DESTROYED, payload={'agent_id': 'agent-aaa111'}),
    Event(type=EventType.SKILL_CHECKED_OUT, payload={'names': ['ppt_export']}),
    Event(type=EventType.TASK_FAILED, payload={'task_id': 't-1003', 'subtask_id': 's-3-crawler', 'error': 'ppt_export timeout after 30s'}),
    Event(type=EventType.REPAIR_TRIGGERED, payload={'task_id': 't-1003', 'subtask_id': 's-3-crawler', 'action': 'switch_skill'}),
    Event(type=EventType.TASK_FAILED, payload={'task_id': 't-1004', 'subtask_id': 's-2-fetch', 'error': 'crawler_fetch connection refused (port 443)'}),
    Event(type=EventType.REPAIR_TRIGGERED, payload={'task_id': 't-1004', 'subtask_id': 's-2-fetch', 'action': 're_assemble'}),
    Event(type=EventType.TASK_COMPLETED, payload={'task_id': 't-1005'}),
    Event(type=EventType.PAUSE_POINT, payload={'reason': '需要人工确认扫描目标白名单'}),
]
for e in events:
    bus.publish(e)
    time.sleep(0.01)

# Memory 多塞
mem.put(MemoryTier.LONG, 'task:t-1001', {'ok': True, 'result': 'all passed'})
mem.put(MemoryTier.LONG, 'task:t-1002', {'ok': True, 'result': 'all passed'})
mem.put(MemoryTier.LONG, 'task:t-1003', {'ok': False, 'error': 'ppt_export timeout'})
mem.put(MemoryTier.SHORT, 'session:current', {'user': 'demo'})
mem.put(MemoryTier.SHORT, 'recent:1', {'plan_id': '001'})
mem.put(MemoryTier.WORKING, 'plan:001', {'subtasks': 4})
mem.put(MemoryTier.WORKING, 'plan:002', {'subtasks': 5})

dash = GradioDashboard(pool=pool, bus=bus, brain=None, memory=mem)

# Dump 所有 render
print("=" * 80)
print("[Health]")
print(dash._render_health())
print()
print("=" * 80)
print("[Brain]")
for r in dash._render_brain():
    print(' ', r)
print()
print("=" * 80)
print("[Tasks]")
for r in dash._render_tasks():
    print(' ', r)
print()
print("=" * 80)
print("[Events]")
print(dash._render_events()[:1500])
print()
print("=" * 80)
print("[Skills]")
for r in dash._render_skills():
    print(' ', r)
print()
print("=" * 80)
print("[Repair]")
print(dash._render_repair())
print()
print("=" * 80)
print("[Memory]")
print(dash._render_memory())
print()
print("=" * 80)
print("[Inspect]")
for r in dash._render_inspect():
    print(' ', r)