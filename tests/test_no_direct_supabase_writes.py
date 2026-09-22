"""S-404 — `scripts/` 里不许直连 Supabase 写入。棘轮:冻结现状,禁止增长。

## 这条守的不是「数据被写乱了」,是反过来的

2026-09-22 实测,而实测推翻了提出这条时的框架:

    .env 里的钥匙        SUPABASE_KEY(anon) + SUPABASE_URL —— **没有 service_role**
    anon 可 INSERT 的表  **0**      UPDATE **0**      DELETE **0**
    service_role 可 INSERT  96
    引用 SUPABASE_SERVICE_KEY 的文件 90 个 —— **而它不在 .env 里,全部解析成空**

**所以直连写入在这台机器上一个字节都写不进去。** 它们不是在制造混乱的数据,
**是在往虚空里写,然后把 401/403 吞掉** —— 和「表存在、永远空、看起来这项有人管」
(S-201)是同一件事的上游。

`research_intake.py` 的 docstring 早就记过同一件事:
「Minimax-C 被要求把 172 个挖掘产物落进一条**已经关闭**的路径,
靠碰撞才发现,**因为没有任何东西说它关了**。」
**正确的路(`/internal/research-intake`)已经建好并 ship 了 —— 缺的是强制。**

## 合法的写入路只有两条

    ① Railway `/internal/*`   —— 它持有 service_role(S-169 的整个设计)
    ② Supabase MCP            —— 带凭证的受控通道(迁移、一次性修数)

**不合法的第三条**:脚本里 `POST/PATCH/DELETE` 到 `$SUPABASE_URL/rest/v1/…`。

⚠️ **读不在这条守卫范围内。** anon 读 80 张表是 by design(S-169),
一个直连的**只读**脚本不会造成任何写入问题。**把读也一起禁,是把作用域扩大到
不需要的地方,而作用域太大的规则会被绕过**(和作用域太小一样坏)。

## 为什么是棘轮而不是大迁移

当前 9 个违规脚本全部列在 `FROZEN` 里,**带各自的理由和解除条件**。
守卫今天是绿的,**它拦的是第 10 个**。
一次性重写 21 个脚本、每个都要回归测试,风险远大于收益 ——
**而不拦住增长,重写完第二天就会有新的。**

`FROZEN` 的设计沿用 `test_every_test_is_registered.EXEMPT`:
**豁免不是赦免,每一条写明为什么 + 什么时候删掉。**
一条 `FROZEN` 被迁走之后必须从名单里删除,否则名单会变成永久特赦。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

#: 当前已存在的直连写入脚本。**每一条写明为什么还在、什么时候能删。**
#: 迁走一个就从这里删一个 —— 名单只许缩短。
FROZEN: dict[str, str] = {
    "cis_historical_ingest.py":
        "一次性历史灌入(cis_scores)。日更路径走 Mac→Railway /internal/cis-scores,"
        "与它无关。**今天跑会静默失败**(anon 写 0 张表)。"
        "解除:要么改走 /internal/research-intake,要么标成 MCP-only 运维脚本。",
    "reconstruct_cis_history.py":
        "同上,cis_scores 的历史重建。解除条件同上。",
    "backfill_embedding_history.py":
        "一次性回填 asset_embeddings_history。解除:改走 /internal/asset-vectors-history。",
    "load_meditations.py":
        "把 83 篇冥想贴到 regime_daily(S-349)。**那次我是用 MCP 写的,脚本这条路没验过。**"
        "解除:确认它要么走 MCP、要么走 Railway,二选一并在文件头写明。",
    "sync_ohlcv_local_to_supabase.py":
        "本地 OHLCV 同步。⚠️ **规则 3b:ingestion 是 Seth 的 lane 且只走受守的路** —— "
        "这个脚本的存在本身要重新审。解除:并入 /internal/ohlcv-collect 或删除。",
    "compute_regime_fitness.py":
        "写 cis_regime_fitness。解除:改走 /internal/regime-fitness(端点已存在)。",
    "refresh_column_snapshot.py":
        "调 RPC 刷新列快照。⚠️ S-361 踩过:它进 `&&` 链后在没 source .env 的 shell 上拿不到凭证,"
        "**卡住了所有 push**。解除:改走 MCP 或 Railway。",
    "run_freqtrade_backtest.py":
        "回测产物落库。解除:改走 /internal/research-intake(那个端点就是为这个建的)。",
    "ops_console.py":
        "只读台子,但调了写 RPC。⚠️ S-375 已记它的身份问题;"
        "A 正在按 §S-399 的裁决把它整体改成调 /internal/schema-drift。"
        "解除:那次改造完成后从本名单删除。",
}

#: 写请求的形状。读(GET)不在范围内 —— 见模块 docstring 的作用域说明。
_WRITE = re.compile(
    r"""(?x)
    (?: method \s* = \s* ["'](?:POST|PATCH|DELETE|PUT)["'] )   # urllib Request(method=…)
  | (?: \. (?:post|patch|delete|put) \s* \( )                  # httpx / requests
    """
)
# ⚠️ 末尾**不带斜杠**。第一版写成 `rest/v1/`,于是漏掉
# `run_freqtrade_backtest.py:79` 的 `SUPABASE_URL` 默认值(以 `rest/v1` 结尾,
# 拼接时才补斜杠)—— 一个字符的过严,少报一个真实的违规者。
# **是下面那条反向检查抓到的**:单向守卫(只查「有没有新增」)会静默少报,
# 双向(再查「名单里的是不是还成立」)才会响。SPINE 那条的同款。
_REST = re.compile(r"""rest/v1""")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _direct_writers() -> set[str]:
    out: set[str] = set()
    for p in sorted(SCRIPTS.glob("*.py")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if _WRITE.search(txt) and _REST.search(txt):
            out.add(p.name)
    return out


def test_no_new_direct_supabase_writer() -> None:
    """新增的直连写入脚本 ⇒ RED。名单只许缩短。"""
    found = _direct_writers()
    new = sorted(found - set(FROZEN))
    if new:
        _fail(
            f"{len(new)} 个新的直连 Supabase 写入脚本:{new}\n"
            "    写入只有两条合法路:① Railway `/internal/*`(它持有 service_role)"
            " ② Supabase MCP。\n"
            "    ⚠️ **直连写在这台机器上根本写不进去** —— anon 对 0 张表有 INSERT 权限,"
            "结果是 401/403 被吞,\n"
            "    表永远空而看起来有人管(S-201)。**不是数据被写乱,是写进了虚空。**\n"
            "    若确有理由,加进本文件 FROZEN 并写明**为什么**和**什么时候删掉**。"
        )
    _ok(f"无新增直连写入脚本(冻结 {len(FROZEN)} 个,实测 {len(found)} 个)")


def test_frozen_list_has_no_stale_entries() -> None:
    """已经迁走的不许留在名单里 —— 否则 FROZEN 会变成永久特赦。

    这是 `EXEMPT` 那条设计的同款:**豁免不是赦免,被解决之后那一行必须删掉。**
    """
    found = _direct_writers()
    stale = sorted(set(FROZEN) - found)
    if stale:
        _fail(
            f"{len(stale)} 条 FROZEN 已经不再直连写入,请从名单删除:{stale}\n"
            "    留着它们会让名单变成永久特赦,而下一个人读到的是一份虚假的债务清单。"
        )
    _ok(f"FROZEN 名单无过期条目({len(FROZEN)} 条全部仍然成立)")


def test_every_frozen_entry_states_its_exit_condition() -> None:
    """每条理由必须写明解除条件 —— 没有出口的豁免就是永久的。"""
    bad = [k for k, v in FROZEN.items() if "解除" not in v]
    if bad:
        _fail(f"这些 FROZEN 条目没写解除条件:{bad}")
    _ok("每条 FROZEN 都写明了解除条件")


if __name__ == "__main__":
    print("── S-404 scripts/ 直连 Supabase 写入棘轮 ──")
    test_no_new_direct_supabase_writer()
    test_frozen_list_has_no_stale_entries()
    test_every_frozen_entry_states_its_exit_condition()
    print("\n✅ 3/3 passed")
