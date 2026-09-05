"""摄入只有一条 lane —— 而且这件事必须可强制,不能靠记住 (S-289).

CLAUDE.md 规则 3b 写着「摄入按功能划一条 lane」。它是**散文**,而散文守不住:
M-118 就是在规则写下之后、完全待在 minimax 自己的路径里、又建了第三个 fetcher,
去抓我们**已经有的**数据(S-276:PENDLE 820 天被重抓)。

规则本身没有错,错在它只存在于一份要人去读的文件里。

## 为什么判据是「写」,不是「抓」

抓价格的地方很多,而且**大部分是对的**:`load_binance_panel` 直连 fapi 给研究侧
做面板,`get_cg_ohlc_range` 在请求路径上取一段行情。这些都不产生第二份记录。

真正的危险是**持久化**:

> **两个摄入器 = 两条看起来是同一个量、实际不是的序列。**

一天里 S-273/S-274/S-275 三条都出自这个形状。所以本文件只问一件事:
**谁在往 `ohlcv_daily` 写?** 允许的名单是白名单,加人要改代码 + 留台账,
不能是「顺手加个 upsert」。

## 为什么这个守卫拦不住 M-118 本身

M-118 的 fetcher 活在 `/Volumes/CometCloudAI/cometcloud-local/`,不在本仓库,
**这个测试看不见它**。诚实记下来而不是假装覆盖:本文件保证的是
「B(路由到 deep_walk)+ A(删除)做完之后,**第四个不会在本仓库里长出来**」。
Mac 侧的等价保证要么靠 A 的 preflight,要么靠把摄入彻底收回本仓库 —— 后者是
规则 3b 的字面意思,也是这条债最终该还的方式。

**一个作用域小于问题的守卫读起来就是覆盖**(本周第六次),所以这段话必须留在这里。
"""
from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"

#: 允许写 `ohlcv_daily` 的模块。每一条都要能说出「它是哪条 lane 的哪一步」。
#: 加人 = 改这个常量 + 台账条目,和 `_INCEPTION_ID` 同样的摩擦。
_ALLOWED_WRITERS = {
    # S-258/S-269:CoinGecko Pro 分块回填,受 deep_walk 的「走到起点」判据约束。
    "src/data/market/cg_pro_backfill.py",
    # 深度面板采集(262 标的),与上面共用同一个 upsert 与 on_conflict。
    "src/data/market/deep_panel_collector.py",
    # Hyperliquid 采集,S-197 之后作为价格锚而非执行场所。
    "src/data/market/hyperliquid_collector.py",
}

_WRITE_HELPERS = {"supabase_insert_table", "supabase_upsert_table",
                  "supabase_insert", "_sb_post"}

_OK, _FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (_OK if cond else _FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" :: {detail}" if not cond and detail else ""))


def _ohlcv_writers() -> dict[str, list[int]]:
    """模块相对路径 -> 写 ohlcv_daily 的行号。AST,不是 grep:
    注释里的表名是文档,不是写入,而本文件的全部意义就是不把
    「写下来的」和「跑起来的」混为一谈。"""
    found: dict[str, list[int]] = {}
    for p in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        rel = p.relative_to(_ROOT).as_posix()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if nm not in _WRITE_HELPERS or not n.args:
                continue
            a0 = n.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str) \
                    and a0.value.startswith("ohlcv"):
                found.setdefault(rel, []).append(n.lineno)
    return found


def test_only_the_allowlisted_modules_write_ohlcv() -> None:
    writers = _ohlcv_writers()
    extra = sorted(set(writers) - _ALLOWED_WRITERS)
    check("没有第二条摄入路径", not extra,
          f"这些模块也在写 ohlcv_daily:{extra} —— 规则 3b 只允许一条。"
          f"两个摄入器会产生两条看起来是同一个量的序列(S-273/274/275 同日三发)。"
          f"要么路由到 deep_walk,要么把它加进 _ALLOWED_WRITERS 并在台账写明理由")


def test_the_allowlist_is_not_stale() -> None:
    """名单里列了、实际不再写的,要摘掉。

    一份有鬼影的白名单会让下一个人以为覆盖比实际更宽 —— 和 manifest 里的
    ghost table 同一个毛病,而那条已经在 `test_every_written_table_exists`
    里学过一次了。"""
    writers = _ohlcv_writers()
    ghosts = sorted(_ALLOWED_WRITERS - set(writers))
    check("白名单没有鬼影", not ghosts,
          f"{ghosts} 已不再写 ohlcv_daily,请从 _ALLOWED_WRITERS 移除")


def test_the_guard_states_what_it_cannot_see() -> None:
    """守卫必须自己说出作用域边界。

    M-118 的 fetcher 在 Mac 侧,本仓库的测试看不见。**沉默的作用域是这周
    重复了六次的缺陷**(inception 只护 Postgres · mark_coverage 只在 ① ·
    列检查只查 api_keys · schema-drift 只查表 · 容差只被自己的测试读 ·
    forward-fill 不可见)。所以这条断言的是文档本身。"""
    doc = pathlib.Path(__file__).read_text(encoding="utf-8")
    check("守卫写明了它看不见 Mac 侧",
          "cometcloud-local" in doc and "看不见" in doc,
          "本文件必须显式说明它不覆盖 Mac 侧摄入路径,否则它读起来像全覆盖")


if __name__ == "__main__":
    print("── 摄入只有一条 lane (S-289 / 规则 3b) ──")
    test_only_the_allowlisted_modules_write_ohlcv()
    test_the_allowlist_is_not_stale()
    test_the_guard_states_what_it_cannot_see()
    print()
    if _FAIL:
        print(f"🔴 {len(_FAIL)} FAILED: {_FAIL}")
        raise SystemExit(1)
    print(f"✅ {len(_OK)}/{len(_OK)} 摄入 lane 检查通过 · Mac 侧不在本守卫范围内")
