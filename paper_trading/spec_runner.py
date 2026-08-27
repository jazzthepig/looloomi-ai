"""Paper-trade 执行器:按 spec JSON 跑,拒绝比成交更有信息 (S-254).

## 这是谁的活,以及它欠了多久

`Shadow/cometcloud-local/paper_trading_specs/m86_r22_k1_hold14_ret3d_README.md`:

    - **minimax-c (engine):** SHIP - 2026-08-26 (「直接走」)
    - **Seth/Austin (execution):** PENDING - wire up execution per pseudo-code above
    - **Jazz (strategic):** SHIP - 2026-08-26

**三个 spec 已经 ship 到 Mac 侧,而 `paper_trading/` 目录不存在。**
M-86(④ 卫星)· M-87(② beta+,OOS +19.94% / SR +2.270)·
M-88(③ beta multiplier,OOS +29.90% / SR +1.912)——
全部 OOS 验证过、全部等着一条执行路径。

## 为什么是 spec-driven 而不是给 M-86 写一个

三个 spec 现在,还会有更多(M-93 ① 也要接)。给每个 spec 写一个 runner,
就是给每个 spec 一份会各自漂移的成交逻辑 —— 今天已经因为
「两个展平器 / 四个 regime 规范化实现」被抓过两次(S-249)。
一份 runner,spec 是数据。

## 但实测发现:三个 spec 是三种 schema,不是一种

接线时才发现的,值得记下来:

    M-86  cross_sectional_momentum_ls    K · rank_by · n_lookback · hold · cadence
    M-87  cluster_tilt_cross_sectional_ls K_long/K_short · score_formula · rebalance:"daily"
    M-88  regime_switch_beta_multiplier   regime_proxy · if_btc_21d_gt_0 / _le_0

**M-88 根本不是横截面排名** —— 它是一个 regime 开关,按 BTC 21d 收益的符号
在两个完全不同的子策略之间切。用一份"通用" runner 硬吃三种,只会在
M-88 上产生一个**语义上错误但语法上成功**的成交。

所以按 `spec_family` 分派,而**没有接线的 family 明确拒绝**:
`Spec.load` 缺字段抛异常(S-122:不填默认值),`FAMILIES` 表说清楚谁通了。
把"这个 family 还没接"变成一个可读的失败,而不是一次静默的错误成交。

**当前状态:1/3 接通。** 这不是好消息,但它是真的,而且现在可查。

## 它必须拒绝的场景,而不是硬着头皮成交

**这条是本模块的核心,不是防御性编程。**

实测 2026-08-27(S-251):M-86 的 `data_source.primary = "binance_hist"`,
而 binance_hist **最近 3 天 0/212 个标的**,自 08-09 起每天只写 BCH 一个。
一个照着 spec 跑的 runner 会:拿到历史面板 → 排序 → **开一笔仓**,
而那笔仓是按 7 天前的价格排的。**它会产生一条看起来正常的 paper 记录。**

纸面账的价值全部来自它是不是一份诚实的前向记录。一笔在死数据上开的仓
污染的不是这一笔,是整条曲线 —— 而且**不可分辨**,因为记录里不会写
"这天的价格是 7 天前的"。所以:panel 不新鲜 → `BLOCKED`,不开仓,写下原因。

三值,不是两值:

    ENTERED   开了仓,附标的与 regime
    SKIPPED   规则说不开(排不出两条腿 / regime 被跳过 / 已达 max_open)
    BLOCKED   我们【算不了】(价源死了 / 覆盖不足 / 跨源)

`SKIPPED` 是策略在工作,`BLOCKED` 是我们瞎了。把它们压成"今天没开仓"
正是 S-207 那一课(规则拒绝 vs 规则跑不起来 → 一个"没开仓")。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

log = logging.getLogger("spec_runner")

#: panel 最后一根 bar 距今超过这个天数 → BLOCKED。
#: 加密 24/7,所以 2 天已经很宽松;这不是"容错",是"再宽就等于用旧价开仓"。
MAX_PANEL_AGE_DAYS = 2

#: 排序至少需要几个标的。K=1 的多空需要 2 条腿,但只有 2 个标的时
#: "最高"和"最低"是同一次比较,没有横截面信息可言。
MIN_UNIVERSE_FOR_RANK = 3


#: 哪些 spec_family 真的有 decide() 实现。**True 才会被执行。**
#:
#: 把它写成一张表而不是一句 if,是因为"哪些通了"必须是**可查的事实**,
#: 不是读代码读出来的推断。今天 S-244 那一课:写了 ≠ 被执行;
#: 这里是它的反面 —— **没写的必须说出来自己没写。**
FAMILIES: dict[str, bool] = {
    "cross_sectional_momentum_ls": True,        # M-86:本模块实现
    "cluster_tilt_cross_sectional_ls": False,   # M-87:K_long/K_short + score_formula,待接
    "regime_switch_beta_multiplier": False,     # M-88:regime 开关切两个子策略,机制不同
}


class UnwiredFamily(NotImplementedError):
    """这个 spec 的机制还没有实现 —— 明确拒绝,不要用别的 family 的逻辑凑合。"""


class Verdict:
    ENTERED = "ENTERED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Leg:
    symbol: str
    side: str            # "long" | "short"
    weight: float
    price: float


@dataclass(frozen=True)
class Decision:
    """一天的判定 = 结论 + 为什么。没有 reason 的 SKIPPED/BLOCKED 不接受。"""

    d: str
    spec_name: str
    verdict: str
    reason: str = ""
    legs: tuple[Leg, ...] = ()
    regime: Optional[str] = None
    panel_source: Optional[str] = None
    panel_last_bar: Optional[str] = None

    def __post_init__(self) -> None:
        if self.verdict in (Verdict.SKIPPED, Verdict.BLOCKED) and not self.reason:
            raise ValueError(
                f"{self.verdict} 必须带原因 —— 一个说不出'为什么没开仓'的判定,"
                f"和一次静默失败在下游长得一样 (S-207)")
        if self.verdict == Verdict.ENTERED and not self.legs:
            raise ValueError("ENTERED 却没有腿 —— 那不是开仓")

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "date": self.d, "spec": self.spec_name, "verdict": self.verdict,
            "regime": self.regime,
            "panel": {"source": self.panel_source, "last_bar": self.panel_last_bar},
        }
        if self.legs:
            out["legs"] = [{"symbol": l.symbol, "side": l.side,
                            "weight": l.weight, "price": l.price} for l in self.legs]
        if self.verdict != Verdict.ENTERED:
            out["reason"] = self.reason
        return out


@dataclass
class Spec:
    """spec JSON 的最小契约。多的字段忽略,少的字段必须报错而不是默认。"""

    name: str
    universe: tuple[str, ...]
    rank_by: str
    n_lookback: int
    hold: int
    cadence: int
    k: int
    weight_per_leg: float
    cost_bps_rt: float
    dd_stop_pct: float
    max_open_trades: int
    skip_regimes: frozenset[str]
    source: str
    dry_run: bool
    raw: Mapping[str, Any] = field(default_factory=dict)

    family: str = "cross_sectional_momentum_ls"

    @classmethod
    def load(cls, path: str | Path) -> "Spec":
        """从 JSON 读。**缺字段抛异常,不填默认值。**

        一个默认的 `cost_bps_rt = 0` 会让每条曲线都好看一点,而且不会有人发现 ——
        MEMORY.md:「默认值越接近多数类越查不出,危害与可发现性成反比」(S-122)。
        """
        raw = json.loads(Path(path).read_text())
        fam = str(raw.get("spec_family") or "")
        if fam not in FAMILIES:
            raise UnwiredFamily(
                f"spec_family '{fam}' 还没有接线(spec={raw.get('spec_name')})。"
                f"已接:{sorted(k for k, v in FAMILIES.items() if v)};"
                f"已知未接:{sorted(k for k, v in FAMILIES.items() if not v)}。"
                f"用通用 runner 硬吃一个不同机制的 family,会产生语法成功、"
                f"语义错误的成交 —— 那比不跑更糟。")
        if not FAMILIES[fam]:
            raise UnwiredFamily(
                f"spec_family '{fam}' 已知但【尚未接线】(spec={raw.get('spec_name')})。"
                f"它的机制与 cross_sectional_momentum_ls 不同,需要自己的 decide()。")
        p = raw.get("parameters") or {}
        ds = raw.get("data_source") or {}
        ex = raw.get("execution") or {}

        def need(container: Mapping[str, Any], key: str, where: str):
            if key not in container or container[key] is None:
                raise ValueError(f"spec 缺 {where}.{key} —— 不填默认值 (S-122)")
            return container[key]

        return cls(
            name=need(raw, "spec_name", "spec"),
            universe=tuple(need(raw, "universe", "spec")),
            rank_by=need(p, "rank_by", "parameters"),
            n_lookback=int(need(p, "n_lookback", "parameters")),
            hold=int(need(p, "hold", "parameters")),
            cadence=int(need(p, "cadence", "parameters")),
            k=int(need(p, "K", "parameters")),
            weight_per_leg=float(need(p, "weight_per_leg", "parameters")),
            cost_bps_rt=float(need(p, "cost_bps_rt", "parameters")),
            dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
            max_open_trades=int(need(p, "max_open_trades", "parameters")),
            skip_regimes=frozenset(str(r).upper() for r in (p.get("skip_regimes") or [])),
            source=str(need(ds, "primary", "data_source")),
            family=fam,
            dry_run=bool(ex.get("dry_run", True)),   # 缺省必须是 dry_run,不是实盘
            raw=raw,
        )


# ── 面板 ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Panel:
    """`{symbol: {day: close}}` + 它的源与末端。值 + 可信域,和今天其余模块同一个模式。"""

    closes: Mapping[str, Mapping[str, float]]
    source: str
    last_bar: Optional[str]
    n_symbols: int

    def age_days(self, as_of: date) -> Optional[int]:
        if not self.last_bar:
            return None
        return (as_of - date.fromisoformat(self.last_bar)).days


def build_panel(rows: Sequence[Mapping[str, Any]], *, source: str) -> Panel:
    """从行构面板,并**断言单源** (S-230)。

    `assert_single_source` 会在混源时抛 `CrossSourceError` —— 不在这里 catch。
    一个在跨源面板上排出来的名次,是在拼接跳变上排的:三个源对同一个 BTC
    同一窗口给 +1.6% / +21.3% / +19.1%,谁排第一取决于哪个源赢了那一天。
    """
    from src.data.market.single_source import assert_single_source

    src = assert_single_source(rows, job=f"paper panel {source}", source_key="source")
    closes: dict[str, dict[str, float]] = {}
    for r in rows:
        c = r.get("close")
        d = str(r.get("trade_date") or "")[:10]
        if c is None or not d:
            continue
        closes.setdefault(str(r["symbol"]), {})[d] = float(c)
    last = max((d for s in closes.values() for d in s), default=None)
    return Panel(closes, src.source, last, len(closes))


def _return_over(closes: Mapping[str, float], upto: str, n: int) -> Optional[float]:
    """`upto` 当天回看 n 天的收益。**PIT:只用 <= upto 的 bar。**"""
    ds = sorted(d for d in closes if d <= upto)
    if len(ds) < n + 1:
        return None
    a, b = closes[ds[-(n + 1)]], closes[ds[-1]]
    return (b / a - 1.0) if a else None


# ── 决策 ──────────────────────────────────────────────────────────────────────

def decide(spec: Spec, panel: Panel, *, as_of: date,
           regime: Optional[str], n_open: int) -> Decision:
    """一天的判定。**不写任何东西** —— 纯函数,便于重放与测试。

    顺序有意为之:**先判我们能不能算(BLOCKED),再判规则说什么(SKIPPED)。**
    反过来的话,一个价源死掉的日子会被记成"regime 跳过",
    而那会让停摆看起来像纪律。
    """
    d = as_of.isoformat()
    base = dict(d=d, spec_name=spec.name, panel_source=panel.source,
                panel_last_bar=panel.last_bar)

    # ① 面板本身能不能用 ─────────────────────────────────────────────────────
    if panel.n_symbols == 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板 0 个标的 —— 源 {spec.source} 没有返回任何行。"
                               f"这不等于'今天没有机会' (S-180)")
    age = panel.age_days(as_of)
    if age is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="面板没有可读的最后一根 bar")
    if age > MAX_PANEL_AGE_DAYS:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板最后一根 bar 是 {panel.last_bar},已 {age} 天 "
                               f"> {MAX_PANEL_AGE_DAYS} 天。用旧价开的仓会产生一条"
                               f"看起来正常、而不可分辨的污染记录 (S-251:"
                               f"binance_hist 自 08-09 起每天只写 1 个标的)")
    missing = [s for s in spec.universe if s not in panel.closes]
    if missing:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"universe 里 {len(missing)}/{len(spec.universe)} 个标的"
                               f"不在面板里:{missing} —— 在残缺宇宙上排名不是这个 spec")

    # ② 规则说什么 ───────────────────────────────────────────────────────────
    canon = None
    if regime is not None:
        from src.data.cis.cis_provider import canonical_regime_strict
        canon = canonical_regime_strict(regime)
    base["regime"] = canon
    if canon and canon in spec.skip_regimes:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"regime {canon} 在 skip_regimes 里 —— 规则在工作")
    if n_open >= spec.max_open_trades:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"已有 {n_open} 笔未平仓 >= max_open_trades "
                               f"{spec.max_open_trades}")

    rets = {s: _return_over(panel.closes[s], d, spec.n_lookback) for s in spec.universe}
    usable = {s: v for s, v in rets.items() if v is not None}
    if len(usable) < MIN_UNIVERSE_FOR_RANK:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"只有 {len(usable)}/{len(spec.universe)} 个标的算得出 "
                               f"{spec.n_lookback}d 收益(需要 >= {MIN_UNIVERSE_FOR_RANK})"
                               f" —— 算不出名次不等于名次是平的")

    ranked = sorted(usable, key=lambda s: usable[s], reverse=True)
    longs, shorts = ranked[: spec.k], ranked[-spec.k:]
    if set(longs) & set(shorts):
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"K={spec.k} 在 {len(ranked)} 个标的上让多空腿重叠")

    def px(s: str) -> float:
        return panel.closes[s][max(x for x in panel.closes[s] if x <= d)]

    legs = tuple(
        [Leg(s, "long", spec.weight_per_leg, px(s)) for s in longs]
        + [Leg(s, "short", spec.weight_per_leg, px(s)) for s in shorts])
    return Decision(**base, verdict=Verdict.ENTERED, legs=legs)


def should_run_today(spec: Spec, *, as_of: date, last_entry: Optional[date]) -> bool:
    """cadence 到了没有。第一次运行(无 last_entry)总是跑。"""
    if last_entry is None:
        return True
    return (as_of - last_entry).days >= spec.cadence


def exit_due(spec: Spec, *, entry_date: date, as_of: date,
             pnl_pct: float) -> Optional[str]:
    """该不该平仓 —— 返回原因,None 表示继续持有。

    两个出口都要报出来是哪一个:持满 vs 触止损,在下游是两件不同的事,
    而"平了"把它们压成一件。
    """
    if pnl_pct <= spec.dd_stop_pct:
        return f"dd_stop {pnl_pct:.2f}% <= {spec.dd_stop_pct}%"
    if (as_of - entry_date).days >= spec.hold:
        return f"hold {spec.hold}d reached"
    return None


__all__ = ["Spec", "Panel", "Decision", "Leg", "Verdict",
           "build_panel", "decide", "should_run_today", "exit_due",
           "MAX_PANEL_AGE_DAYS", "MIN_UNIVERSE_FOR_RANK"]
