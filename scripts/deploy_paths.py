#!/usr/bin/env python3
"""哪些路径变了才需要重新部署(Jazz 2026-11-14;S-859)。

每次部署进程重启、进程内缓存清零,之后 5–8 分钟是冷的(量到一次请求 45 秒没回)。11-13 → 11-14 部署了二十多次,其中很多只改了
状态文件、任务卡、测试、研究文档 —— 运行着的服务根本不读它们。`railway.json` 的 `build.watchPatterns` 让 Railway 只在下面这些
路径变了才部署;**这份清单是唯一的源头**,`railway.json` 由它生成、测试核对两边相同。

清单按「运行时读不读」定,不按「重要不重要」定:
- `/src/**`、`/dashboard/**`(构建时要编前端)、`/strategies/**`(开源策略的代码接口直接读)、`/paper_trading/**`、`/data/**`
- `/scripts/*.py`、`/scripts/*.sql`(路由 import `scripts.compute_regime_fitness`;子目录里的机器人和 .sh 不是运行时)
- `/docs/research/scenarios/**`(部署后 `ingest_repo` 把情景命题入账 —— 漏了它,合并进来的命题不会入账)
- 构建与启动:`/requirements.txt`、`/Procfile`、`/nixpacks.toml`、`/railway.json`
不在清单里、而运行时确实读的只有一处:每日摘要数 `PROJECT_STATE.md` 里未关闭风险的条数 —— 它会是上一次部署时的数。
把它放进清单等于每次改状态文件都重启,得不偿失;这一处单独记着。

「线上是不是最新」的判据也跟着变:**线上那一版与 HEAD 之间没有任何运行时路径的差别 ⇒ 就是最新**,不再要求两个 sha 相等。

用法:
    python3 scripts/deploy_paths.py --is-current <线上 sha> [<目标 sha,缺省 HEAD>]     # 退出码 0 = 是最新
    python3 scripts/deploy_paths.py --write-railway-json
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = (
    "/src/**", "/dashboard/**", "/strategies/**", "/paper_trading/**", "/data/**",
    "/scripts/*.py", "/scripts/*.sql",
    "/docs/research/scenarios/**",
    "/requirements.txt", "/Procfile", "/nixpacks.toml", "/railway.json",
)


def matches(path: str, pattern: str) -> bool:
    """清单里只允许三种写法:`/目录/**`(目录下任何深度)、`/目录/*.后缀`(只这一层)、`/文件`(精确)。"""
    p, pat = path.lstrip("/"), pattern.lstrip("/")
    if pat.endswith("/**"):
        return p.startswith(pat[:-2])
    if "*" in pat:
        return p.count("/") == pat.count("/") and fnmatch.fnmatchcase(p, pat)
    return p == pat


def touches_runtime(paths: Iterable[str]) -> bool:
    return any(matches(p, pat) for p in paths for pat in PATTERNS)


def railway_config() -> dict:
    return {"$schema": "https://railway.com/railway.schema.json", "build": {"watchPatterns": list(PATTERNS)}}


def changed_between(a: str, b: str = "HEAD", root: Optional[Path] = None) -> Optional[list[str]]:
    """a..b 之间变过的文件;git 读不出(不认识的 sha 等)⇒ None(调用方当作「不是最新」)。"""
    r = subprocess.run(["git", "--no-optional-locks", "diff", "--name-only", f"{a}..{b}"], cwd=root or ROOT,
                       capture_output=True, text=True)
    return None if r.returncode != 0 else [x for x in r.stdout.splitlines() if x.strip()]


def is_current(live_sha: str, want: str = "HEAD", root: Optional[Path] = None) -> bool:
    """线上那一版对 `want` 来说是不是最新:两者之间没有运行时路径的差别。"""
    if not live_sha:
        return False
    files = changed_between(live_sha, want, root)
    return files is not None and not touches_runtime(files)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--is-current":
        return 0 if is_current(argv[1], argv[2] if len(argv) > 2 else "HEAD") else 1
    if argv == ["--write-railway-json"]:
        (ROOT / "railway.json").write_text(json.dumps(railway_config(), indent=2) + "\n", encoding="utf-8")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
