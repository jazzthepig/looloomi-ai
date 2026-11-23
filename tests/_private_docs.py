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
#: S-902:由私有文档**派生**的东西同样不入库 —— 台账 R 段的逐字快照、策略报告。T-056 于 11-18 把它们合进了公开仓库,
#: 当时的三道门都只认上面四个确切文件名(换个名字、换个目录就过了)。以 `/` 结尾 = 整个目录。
PRIVATE_DERIVED = ("docs/strategy_sources/REFUTATION_LEDGER.snapshot.md", "docs/strategy_sources/sidecars/")
#: 被跟踪的路径名里不许出现的名字(大小写不敏感)。
PRIVATE_NAME_PARTS = ("REFUTATION_LEDGER", "STRATEGY_PLAYBOOK")
#: 认内容,不认名字:台账的条目标题长这样(`## R76 …` / `## S-902 — …` / `## M-118 …`)。
#: 任何被跟踪的文本里这种标题达到 `LEDGER_HEADINGS_LIMIT` 个 = 一份台账的拷贝(11-23 实测:全仓库只有那份快照命中,92 个)。
LEDGER_HEADING = r"(?m)^## (?:R\d+|[SM]-\d+)\b"
LEDGER_HEADINGS_LIMIT = 10


def available(rel: str) -> bool:
    if (ROOT / rel).exists():
        return True
    if os.environ.get("CI") == "true":
        print(f"  ⚠ 跳过:{rel} 不入库(S-501),只在 Mac 侧 preflight 检查")
        return False
    raise FileNotFoundError(
        f"{rel} 不在 —— 它不入库(S-501),Mac 主目录那份是唯一一份;"
        "lane worktree 应有软链(bash scripts/setup_lane_worktrees.sh)")
