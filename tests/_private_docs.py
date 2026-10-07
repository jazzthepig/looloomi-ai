"""S-501:仓库是 public,研究台账、策略手册、Jazz 的裁决不入库。读它们的测试先问这里。

三种机器,三种处理:
- Mac 主目录 / lane worktree(软链)/ seth_bot 合并用的临时 worktree(软链):文件在 → 照常检查
- CI(干净机器,GitHub 设 CI=true):文件不在 → 明说跳过,不冒充通过
- 其他任何地方文件不在 → 报错。主目录那份是唯一一份,缺了是丢数据,不是环境差异
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DOCS = ("REFUTATION_LEDGER.md", "STRATEGY_PLAYBOOK.md", "DECISIONS.md", "docs/DECISIONS.md")


def available(rel: str) -> bool:
    if (ROOT / rel).exists():
        return True
    if os.environ.get("CI") == "true":
        print(f"  ⚠ 跳过:{rel} 不入库(S-501),只在 Mac 侧 preflight 检查")
        return False
    raise FileNotFoundError(
        f"{rel} 不在 —— 它不入库(S-501),Mac 主目录那份是唯一一份;"
        "lane worktree 应有软链(bash scripts/setup_lane_worktrees.sh)")
