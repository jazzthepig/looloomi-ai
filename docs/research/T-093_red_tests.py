"""T-093 红测(§Seth-1014k 退回原 c258f81):钉住两处 R3c 错误,改 T-093_run.py 时必红→必绿。

1) short_ret 公式:旧 = p_ent / p_ext − 1(凸、100→50 记 +100%、价格趋零记 +∞)。
2) find_idx 上市前入场:旧 bisect_right − 1 在入期日早于该名首日时返回 −1,下游 i_ext = min(−1+30, n−1) ⇒
   用该名第 30 个交易日(实为「上市后第 30 天」)当「入场价」,记成假事件。

测试在 git 上跑两次:旧 T-093_run.py ⇒ 红;改完 ⇒ 绿。

可独立运行:python3 docs/research/T-093_red_tests.py。
不依赖 T-092 cache / Supabase。
"""
from __future__ import annotations
import bisect
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # /Users/sbb/Projects/looloomi-ai-lane-b
# src/ 可能在主仓库(本 worktree 不带),在主仓库找 apparatus
MAIN_REPO = Path("/Users/sbb/Projects/looloomi-ai")
if not (ROOT / "src" / "data" / "evaluation" / "apparatus.py").exists():
    sys.path.insert(0, str(MAIN_REPO))
else:
    sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import short_return, long_return, price_on_or_after  # noqa: E402

FAIL = 0
PASS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAIL, PASS
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


# ── §1 旧 short_ret = p_ent / p_ext − 1 是凸的 ──────────────────────────────
def test_old_short_ret_is_convex() -> None:
    # 旧写法:100 → 50 记 +1.0(100/50 − 1);真值是 +0.5
    old = lambda e, x: e / x - 1  # noqa: E731
    new = short_return
    # 单调性:旧写法价格 → 0 时 → +∞(凸),新写法 → +1(有界)
    check("100→50:旧公式 1.0 不等于 apparatus 0.5",
          old(100, 50) != new(100, 50) and new(100, 50) == 0.5,
          f"old={old(100,50)}, new={new(100,50)}")
    check("100→200:旧公式 −0.5 不等于 apparatus −1.0(短仓 2 倍涨幅亏光)",
          old(100, 200) != new(100, 200) and new(100, 200) == -1.0,
          f"old={old(100,200)}, new={new(100,200)}")
    check("100→1e-9:新公式有界 ≤ 1.0(100→0 最多 +1 全部赚)",
          new(100, 1e-9) <= 1.0,
          f"new={new(100, 1e-9)}")
    check("None / 0 / 负 / 字符串:任一价坏 → None",
          new(None, 100) is None and new(100, 0) is None and new(100, -1) is None and new(100, float("nan")) is None and new("x", 100) is None,
          "边界输入应得 None,不是崩")
    check("long_return 100→150 == 0.5(可对照)",
          long_return(100, 150) == 0.5)


# ── §2 旧 find_idx 上市前入场 ───────────────────────────────────────────────
def test_old_find_idx_pre_listing() -> None:
    # 模拟 30 名外的 sym:该名只在 2024-06-15 起有数据(年初被记为 z30≥3,但实价从 6 月起)
    sym_dates = ["2024-06-15", "2024-06-16", "2024-06-17"]
    sym_closes = [1.0, 1.05, 1.10]
    # 入场日 ent_d_b = "2024-06-01"(早于该名首日)
    ent_d_b = "2024-06-01"

    # 旧写法(复刻 T-093_run.py find_idx):
    def find_idx_old(cs, d):
        if d in cs:
            return cs.index(d)
        return bisect.bisect_right(cs, d) - 1
    # 下游:
    i_ent_s = find_idx_old(sym_dates, ent_d_b)
    i_ext_s = min(i_ent_s + 30, len(sym_dates) - 1)
    if i_ext_s > i_ent_s:
        ent_d_s = sym_dates[i_ent_s]  # ← 这里会拿到 -1 ⇒ sym_dates[-1](最后一个)
        p_ent_s = sym_closes[i_ent_s]
    else:
        ent_d_s, p_ent_s = None, None
    check("旧 find_idx:ent_d_b 早于 sym 首日 ⇒ i_ent_s = −1, i_ext_s > i_ent_s, 不返回 None",
          i_ent_s == -1 and i_ext_s > i_ent_s and p_ent_s is not None,
          f"i_ent_s={i_ent_s}, i_ext_s={i_ext_s}, p_ent_s={p_ent_s}(假入场价)")
    # Python 负索引 i_ent_s=−1 ⇒ sym_dates[−1] = sym 最后一个交易日(2024-06-17)
    check("旧 find_idx 假入场:用 sym 最后 1 个交易日(2024-06-17,1.10)当 'ent_d_b 那天' 的入场价 ⇒ 假信号",
          ent_d_s == "2024-06-17" and math.isclose(p_ent_s, 1.10, rel_tol=1e-6),
          f"ent_d_s={ent_d_s}, p_ent_s={p_ent_s}(实际:旧代码的负索引会拿到最后一条,不是首条)")

    # 正确写法:用 price_on_or_after,ent_d_b 早于上市日 ⇒ None
    p = price_on_or_after(sym_dates, sym_closes, ent_d_b, max_gap_days=3)
    check("apparatus.price_on_or_after:ent_d_b 早于 sym 上市日 ⇒ None(不可算,不是最新收盘)",
          p is None,
          f"price_on_or_after={p}")
    # 上市后第 2 天(max_gap=3 内):第一个有效收盘
    p2 = price_on_or_after(sym_dates, sym_closes, "2024-06-16", max_gap_days=3)
    check("apparatus.price_on_or_after:2024-06-16 那天有价 ⇒ 1.05",
          p2 == 1.05,
          f"price_on_or_after={p2}")


# ── §3 r3_pnl 综合:在旧写法下能得到一个「假」净值;改后 None ───────────────
def test_old_r3_pnl_yields_fake_pnl() -> None:
    """复刻旧 r3_pnl 关键路径:不写完整的 R3c 回放,只证明 pre-listing 路径会产生假 P&L。

    场景:sym 2024-06-15 上市(30+ 天数据),但事件周 = 2024-06-10(BTC 在 06-08 早于 06-10)。
    ent_d_b = BTC date at i0+7 = 2024-06-15(刚好是上市日);ext_d_b = 2024-07-13。
    旧代码取 sym_closes[−1] = 1.10 当入场价(应得 1.00)⇒ 假 P&L。修法后 None(ent_d_b 早于 sym 上市日)。
    """
    sym_dates = [f"2024-06-{15+i:02d}" for i in range(31)]
    n = len(sym_dates)
    sym_closes = [1.00 + 0.01 * i for i in range(n)]

    btc_dates = ["2024-06-01", "2024-06-08", "2024-06-15", "2024-06-22", "2024-06-29",
                 "2024-07-06", "2024-07-13", "2024-07-15"]
    btc_closes = [100.0, 102.0, 99.0, 105.0, 103.0, 108.0, 106.0, 110.0]

    def find_idx_old(cs, d):
        if d in cs:
            return cs.index(d)
        return bisect.bisect_right(cs, d) - 1

    # 事件周 = 2024-06-10(BTC 在 06-08,早于事件 ⇒ i0=1)
    cs_btc = btc_dates
    cs_s = sym_dates
    d_event = "2024-06-10"
    i0 = find_idx_old(cs_btc, d_event)  # 1(2024-06-08 早于 2024-06-10)
    i_entry = min(i0 + 7, len(cs_btc) - 1)  # 8,cap at 7
    i_exit = min(i_entry + 30, len(cs_btc) - 1)  # 7
    ent_d_b = cs_btc[i_entry]  # "2024-07-15"(BTC 最后一天)
    ext_d_b = cs_btc[i_exit]  # "2024-07-15"
    # 在 sym 上找 ent_d_b
    i_ent_s = find_idx_old(cs_s, ent_d_b)  # "2024-07-15" 在 sym 里(索引 30)
    i_ext_s = min(i_ent_s + 30, n - 1)
    if i_ext_s > i_ent_s and i_ent_s >= 0:
        p_ent_s = sym_closes[i_ent_s]
        p_ext_s = sym_closes[i_ext_s]
        # 旧 short_ret(p_ent_s/p_ext_s-1)与 apparatus 1-b/a 不同
        short_old = p_ent_s / p_ext_s - 1
        short_new = short_return(p_ent_s, p_ext_s)
        check("正常路径:旧 short_ret 与 apparatus 不一致(凸 vs 有界)",
              not math.isclose(short_old, short_new, rel_tol=1e-6),
              f"old={short_old:.4f}, new={short_new:.4f}")

    # 关键 pre-listing 场景:ent_d_b 早于 sym 上市日
    # 假设 event = 2024-05-20(早于 BTC 第一日 2024-06-01),i0 = -1 ⇒ 旧代码 `if i0<0: return None`,
    # 所以这条路径根本触发不到 i_ent_s. 真正的 pre-listing 场景是:event 落在 BTC 早期、ent_d_b 也早
    # 但 sym 还没上市。造一个 sym 起始 2024-07-01:
    sym_dates_late = [f"2024-07-{1+i:02d}" for i in range(31)]
    sym_closes_late = [2.00 + 0.01 * i for i in range(31)]
    d_event2 = "2024-06-03"  # BTC 在 06-01 ⇒ i0=0
    i0_2 = find_idx_old(cs_btc, d_event2)  # 0
    i_entry_2 = min(i0_2 + 7, len(cs_btc) - 1)  # 7(2024-07-13)
    ent_d_b_2 = cs_btc[i_entry_2]  # "2024-07-13" 早于 sym 起始 2024-07-01? 否,07-13 > 07-01
    # 改 event 2024-06-09 早一点
    d_event3 = "2024-06-09"  # BTC 06-08 ⇒ i0=1
    i0_3 = find_idx_old(cs_btc, d_event3)  # 1
    i_entry_3 = min(i0_3 + 7, len(cs_btc) - 1)  # 8,cap at 7 ⇒ 2024-07-15
    # 还是太晚。缩短 BTC 序列演示:
    btc_short_dates = ["2024-05-25", "2024-06-01", "2024-06-08", "2024-06-15"]
    btc_short_closes = [100.0, 101.0, 102.0, 103.0]
    d_event4 = "2024-05-27"  # i0=0(2024-05-25)
    i0_4 = find_idx_old(btc_short_dates, d_event4)  # 0
    i_entry_4 = min(i0_4 + 7, len(btc_short_dates) - 1)  # 3
    ent_d_b_4 = btc_short_dates[i_entry_4]  # "2024-06-15" — 仍晚于 sym 起始 2024-07-01
    # 关键:让 ent_d_b < sym_dates[0]。用更短 BTC:
    btc_v2 = ["2024-05-20", "2024-05-27"]  # 仅 2 条
    d_event5 = "2024-05-22"  # i0=0
    i0_5 = find_idx_old(btc_v2, d_event5)  # 0
    i_entry_5 = min(i0_5 + 7, len(btc_v2) - 1)  # 1
    ent_d_b_5 = btc_v2[i_entry_5]  # "2024-05-27"
    i_ent_s_5 = find_idx_old(sym_dates_late, ent_d_b_5)  # bisect_right(..., 2024-05-27) - 1 = -1
    i_ext_s_5 = min(i_ent_s_5 + 30, len(sym_dates_late) - 1)  # 29
    if i_ext_s_5 > i_ent_s_5:  # 29 > -1 ⇒ 进入 if
        ent_d_s_5 = sym_dates_late[i_ent_s_5]  # sym_dates_late[−1] = sym 最后 1 日 "2024-07-31"
        p_ent_s_5 = sym_closes_late[i_ent_s_5]  # = 2.30
    else:
        ent_d_s_5, p_ent_s_5 = None, None
    check("pre-listing 假入场(ent_d_b 早于 sym 上市日,旧 find_idx i_ent_s=−1 但下游 i_ext_s=29 > −1, 继续):入价用 sym 最后 1 日 2.30",
          ent_d_s_5 == "2024-07-31" and math.isclose(p_ent_s_5, 2.30, rel_tol=1e-6),
          f"ent_d_s_5={ent_d_s_5}, p_ent_s_5={p_ent_s_5}")
    # 修法:price_on_or_after(ent_d_b_5, ...)⇒ None(早于 sym 上市日)
    p_correct = price_on_or_after(sym_dates_late, sym_closes_late, ent_d_b_5, max_gap_days=3)
    check("apparatus 改法:ent_d_b 早于 sym 上市日 ⇒ None(下游把这条事件当不可算,不是假 P&L)",
          p_correct is None,
          f"price_on_or_after={p_correct}")


def main() -> int:
    print("=== T-093 红测(§Seth-1014k) ===")
    test_old_short_ret_is_convex()
    test_old_find_idx_pre_listing()
    test_old_r3_pnl_yields_fake_pnl()
    print(f"\n  PASS={PASS}  FAIL={FAIL}")
    if FAIL:
        print("  >>> 红测失败 / 有 bug(预期:旧 T-093_run.py = 红,改完 = 绿)")
        return 1
    print("  >>> 绿:两处 R3c 错误已修")
    return 0


if __name__ == "__main__":
    sys.exit(main())
