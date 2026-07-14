"""HiveSwarm skill pack: PPT 生成器.

四阶段流水线:
  - data_collect: 收集数据（stub 模板）
  - outline:     写大纲（stub JSON）
  - layout:      排版渲染（stub Markdown）
  - export:      导出文件（python-pptx 真实生成 .pptx）

用法:
    from ppt_pack import DataCollectSkill
    skill = DataCollectSkill()
    result = skill.run({"topic": "季度复盘"})
"""
from __future__ import annotations

from .skills import (
    DataCollectSkill,
    OutlineSkill,
    LayoutSkill,
    ExportSkill,
    register_all,
)

__version__ = "0.1.0"
__all__ = [
    "DataCollectSkill", "OutlineSkill", "LayoutSkill", "ExportSkill",
    "register_all",
]