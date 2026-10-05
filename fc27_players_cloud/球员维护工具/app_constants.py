"""全局常量：步骤、筛选、推荐与范围标签。"""

from __future__ import annotations

import sys
from pathlib import Path

# PyInstaller onefile 模式下 __file__ 位于临时解压目录，会让配置/运行历史
# 每次启动丢失；frozen 时改用 exe 所在目录作为应用目录。
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

STEP_LABELS = {
    "export": "导出新增球员",
    "transform": "Excel 格式处理",
    "import": "导入后台",
    "tags": "批量标签",
    "recommend": "推荐设置",
    "sync": "同步金币价",
}
FILTER_LABELS = {
    "q": "名称/关键词",
    "rating_min": "最低评分",
    "rating_max": "最高评分",
    "position": "位置",
    "league": "联赛",
    "club": "俱乐部",
    "nation": "国家",
    "days_new": "新增天数",
    "price_platform": "价格平台",
    "price_min": "最低价格",
    "price_max": "最高价格",
    "playstyle": "PlayStyle",
    "ps_type": "PS 类型",
}
RECOMMEND_MODE_LABELS = {"unchanged": "不变", "enable": "开启", "disable": "关闭"}
SCOPE_LABELS = {"manual_ids": "手动模型 ID", "current_batch": "本次导出批次"}
