"""每个价源单独判活,按【覆盖标的数】而不是【最新日期】(S-251).

## 探针为什么看不见管道死亡

`supabase_ohlcv_daily_freshness()` 的全部查询是:

```python
params = {"select": "trade_date", "order": "trade_date.desc", "limit": "1"}
```

**一行。全表最新的那个 `trade_date`,没有 source 过滤,没有 symbol 过滤。**

它的 docstring 写着自己是为「silent pipeline death」建的,并列了三次前科
(T2 pillars 全 NULL 数月 · signal_outcomes 死 80 天 · ohlcv_daily 停 4 天靠偶然发现)。
**而它抓不到第四次,因为它取的是一个混合总体上的 max。**

实测 2026-08-27:

```
coingecko     last=2026-08-27   0d   最近3天 25/25 个标的   flowing
eodhd         last=2026-08-26   1d              33/33      flowing
hyperliquid   last=2026-08-23   4d               0/177     DEAD
binance_hist  last=2026-08-20   7d               0/212     DEAD
yfinance      last=2026-06-18  70d               0/—       DEAD
```

`/internal/data-freshness` 报 **`verdict: "fresh", age_days: 0.5`** ——
因为 coingecko 还在写,而它是全表 max。

### 而 binance_hist 是两段式死的,中间那段更隐蔽

```
2026-07-27   261 个标的
2026-07-28   221            ← 掉了 40
2026-08-08   221
2026-08-09     1            ← 掉了 220,只剩 BCH
2026-08-20     1            ← 至今
```

**08-09 之后整整 19 天,binance_hist 每天只写一个标的(BCH)。**
一个还活着的写入者掩护了 260 个死掉的 —— 而 `max(trade_date)` 对此一无所知,
因为 BCH 每天都在把那个 max 往前推。

> **「某个东西是新的」和「这个管道是活的」被压成了同一个数。**

这和今天其余全部缺陷是同一个形状,只是这次被压掉的那一维是**总体**:
一个 max 不携带它是在多少个成员上取到的。

### 后果不是抽象的

- **加密侧当前没有任何可信价源在更新。** binance_hist 与 hyperliquid 都死了,
  唯一在流的是 coingecko —— 而 S-195 把它排除在收益序列之外。
- S-245 的 `market_state_writer` 默认用 `binance_hist`。历史数据还在,所以
  地板会过、写者会成功 —— **但它产出的是一个 7 天前的基底**,而
  `vdb_health` 的 budget 是 2 天。**上游死着,写者修不好下游。**
- S-248 里 41 个 crypto 行只有 20 个能重算 30 天出口价,直接因为这次停摆。

## 判据:覆盖率衰减,不是日期

一个源"活着"的定义不是"它最近写过",是**"它还在写它历来在写的那么多标的"**。
所以对每个源比较两个数:最近 N 天写了几个标的 vs 一个月前它的常态。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

#: 最近多少天算"当前" —— **按资产域给,因为交易日历不同。**
#:
#: ⚠️ `main.py` 的 `/internal/data-freshness` 里有一段写给未来的人的警告,
#: 而它正对着我这个模块:
#:
#: > 「周末合法地掉到只剩加密(~25 个标的),因为 EODHD 是 TradFi 而市场关门 ——
#: >  一个忽略这件事的标的数检查会**每个周六都狼来了**,而一个狼来了的检查
#: >  会被静音,那正是这一整层存在要避免的失败。」
#:
#: 我第一版是全局 `RECENT_DAYS = 3`。周四实测没事,但**周二早上**(上周五收盘 +
#: 周六 + 周日 + 周一假期)窗口里一根 eodhd bar 都没有 → 会把 eodhd 报成 DEAD。
#: 那就是那段警告描述的失败,一字不差。
#:
#: 加密 24/7,3 天里零覆盖是无歧义的;TradFi 需要容下长周末 + 一次调度抖动。
RECENT_DAYS_BY_DOMAIN = {"crypto": 3, "tradfi": 6}
RECENT_DAYS = 3  # 加密口径;保留供不带域的调用点使用

#: 每个源覆盖哪个资产域。**总判决必须按域给,不能给一个全局的。**
#:
#: ⚠️ 这一层是我自己在写这个模块时犯的第二遍同样的错。第一版 `overall()`
#: 只数"有没有【能用于收益】的源在流",于是实测数据跑出来是 **`verdict: "ok"`** ——
#: 因为 eodhd 活着。**而 eodhd 只有 TradFi,加密侧三个源全死了。**
#:
#: 我在修「一个 max 掩盖了一个总体」的时候,自己又做了一次同样的投影:
#: 把"某个域有可用源"压成了"系统有可用源"。**一个全局的 ok,和每个域都 ok,
#: 不是同一件事** —— 而前者读起来像后者。
DOMAIN_OF_SOURCE = {
    "binance_hist": "crypto",
    "hyperliquid": "crypto",
    "coingecko": "crypto",
    "eodhd": "tradfi",
    "yfinance": "tradfi",
}

#: 常态基线取哪一段。避开最近 15 天,否则正在发生的衰减会把基线一起拉低 ——
#: 那样一个缓慢死亡的源永远达不到告警线,因为它自己就是标尺。
BASELINE_LO_DAYS, BASELINE_HI_DAYS = 45, 15

#: 覆盖率低于常态的这个比例 → COLLAPSED;低于 0.9 → degraded。
COLLAPSE_RATIO = 0.50
DEGRADE_RATIO = 0.90


@dataclass(frozen=True)
class SourceHealth:
    """一个价源的判活结果 —— 五值,不是布尔。"""

    source: str
    verdict: str          # flowing | degraded | COLLAPSED | DEAD | no_baseline
    last_bar: Optional[str]
    age_days: Optional[int]
    symbols_recent: int
    symbols_typical: Optional[int]
    detail: str = ""

    @property
    def usable_for_returns(self) -> bool:
        """能不能用于收益序列 —— 活着还不够,还要没被 S-195/S-230 禁用。"""
        from src.data.market.single_source import TRUSTED_RETURN_SOURCES
        return self.verdict in ("flowing", "degraded") and self.source in TRUSTED_RETURN_SOURCES

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "verdict": self.verdict,
            "last_bar": self.last_bar,
            "age_days": self.age_days,
            "symbols_recent": self.symbols_recent,
            "symbols_typical": self.symbols_typical,
            "usable_for_returns": self.usable_for_returns,
            "detail": self.detail,
        }


def recent_days_for(source: str) -> int:
    """这个源该用几天的窗口 —— 加密 3 天,TradFi 6 天(容长周末)。"""
    return RECENT_DAYS_BY_DOMAIN.get(DOMAIN_OF_SOURCE.get(source, ""), RECENT_DAYS)


def classify(source: str, *, last_bar: Optional[str], age_days: Optional[int],
             symbols_recent: int, symbols_typical: Optional[int]) -> SourceHealth:
    """把覆盖数变成判决。纯函数 —— SQL 留在调用点。

    ⚠️ 判据的顺序有讲究:**先判 DEAD,再判基线缺失。** 反过来的话,一个从未
    有过基线的源(新接入,或历史太短)在完全停写时会被报成 `no_baseline`,
    而那读起来像"还不知道",不像"死了"。0 个标的就是 0 个标的,不需要基线。
    """
    if symbols_recent == 0:
        return SourceHealth(
            source, "DEAD", last_bar, age_days, 0, symbols_typical,
            f"最近 {recent_days_for(source)} 天一个标的都没写"
            + (f";此前常态 {symbols_typical} 个" if symbols_typical else ""))

    if symbols_typical is None or symbols_typical <= 0:
        return SourceHealth(
            source, "no_baseline", last_bar, age_days, symbols_recent, symbols_typical,
            "没有历史常态可比 —— 这【不是】通过,是没法判断")

    ratio = symbols_recent / symbols_typical
    if ratio < COLLAPSE_RATIO:
        return SourceHealth(
            source, "COLLAPSED", last_bar, age_days, symbols_recent, symbols_typical,
            f"覆盖塌到 {symbols_recent}/{symbols_typical}({ratio:.0%}) —— "
            f"少数还活着的写入者会把 max(trade_date) 一直往前推,"
            f"于是全表 max 看起来是新鲜的")
    if ratio < DEGRADE_RATIO:
        return SourceHealth(
            source, "degraded", last_bar, age_days, symbols_recent, symbols_typical,
            f"覆盖 {symbols_recent}/{symbols_typical}({ratio:.0%})")
    return SourceHealth(source, "flowing", last_bar, age_days,
                        symbols_recent, symbols_typical)




def overall(healths: Iterable[SourceHealth]) -> dict[str, Any]:
    """**按资产域**给判决。一个全局的 ok 会掩盖一整个域的全灭。

    重点不是"有没有源在写",是"**每个域有没有【能用于收益】的源在写**"。
    实测 2026-08-27:coingecko 在流但被 S-195 排除;binance_hist 与 hyperliquid
    都 DEAD ⇒ **crypto 域无可用价源**;tradfi 域有 eodhd ⇒ ok。
    """
    hs = list(healths)
    domains: dict[str, dict[str, Any]] = {}
    for h in hs:
        d = DOMAIN_OF_SOURCE.get(h.source, "unknown")
        slot = domains.setdefault(d, {"usable": [], "dead": [], "flowing_but_barred": []})
        if h.usable_for_returns:
            slot["usable"].append(h.source)
        elif h.verdict in ("DEAD", "COLLAPSED"):
            slot["dead"].append(h.source)
        elif h.verdict == "flowing":
            # 在写,但不能用于收益 —— 这是第三种状态,不是"活着"也不是"死了"
            slot["flowing_but_barred"].append(h.source)

    per_domain = {}
    for d, s in domains.items():
        per_domain[d] = {
            **s,
            "verdict": "ok" if s["usable"] else (
                "no_usable_source" if s["flowing_but_barred"] else "all_dead"),
        }

    broken = [d for d, v in per_domain.items() if v["verdict"] != "ok"]
    return {
        "sources": [h.as_dict() for h in hs],
        "by_domain": per_domain,
        "domains_without_usable_source": broken,
        # 任何一个域没有可用源 → 整体不是 ok。
        "verdict": "ok" if not broken else "domain_without_usable_source",
        "note": ("以下资产域没有【能用于收益】的价源:" + ", ".join(broken)
                 + "。有源在写 ≠ 有能用于收益的源在写 (S-195/S-230)。"
                 if broken else ""),
    }


def from_rows(rows: Iterable[Mapping[str, Any]]) -> list[SourceHealth]:
    """把一批 `{source, last_bar, age_days, symbols_recent, symbols_typical}` 变成判决。"""
    def _recent(r):
        """按这个源所属的域挑窗口。SQL 一次给出两个窗口的计数,这里选对的那个 ——
        用错窗口就是 `main.py` 警告的"每个周六狼来了"。"""
        src = str(r.get("source"))
        if "symbols_recent" in r:                       # 直接给了就用(测试/旧调用点)
            return int(r.get("symbols_recent") or 0)
        key = ("symbols_recent_tradfi_win"
               if DOMAIN_OF_SOURCE.get(src) == "tradfi" else "symbols_recent_crypto_win")
        return int(r.get(key) or 0)

    return [classify(str(r.get("source")),
                     last_bar=r.get("last_bar"),
                     age_days=r.get("age_days"),
                     symbols_recent=_recent(r),
                     symbols_typical=(int(r["symbols_typical"])
                                      if r.get("symbols_typical") not in (None, "") else None))
            for r in rows]


#: 供调用点使用的 SQL —— 写在这里,是为了让判据与取数在同一个文件里可读。
#: 一个"最近 3 天覆盖数 vs 一个月前常态"的比较,分散在两处就会各自漂移。
COVERAGE_SQL = """
with recent as (
  select source,
         count(distinct symbol) filter (where trade_date >= current_date - %(recent_crypto)s) as n_crypto_win,
         count(distinct symbol) filter (where trade_date >= current_date - %(recent_tradfi)s) as n_tradfi_win
  from ohlcv_daily where trade_date >= current_date - %(recent_tradfi)s group by 1),
baseline as (
  select source, round(avg(n)::numeric, 0) n_typical from (
    select source, trade_date, count(distinct symbol) n
    from ohlcv_daily
    where trade_date between current_date - %(base_lo)s and current_date - %(base_hi)s
    group by 1, 2) x group by 1),
last_seen as (select source, max(trade_date) last_bar from ohlcv_daily group by 1)
select l.source,
       l.last_bar::text            as last_bar,
       (current_date - l.last_bar) as age_days,
       coalesce(r.n_crypto_win, 0) as symbols_recent_crypto_win,
       coalesce(r.n_tradfi_win, 0) as symbols_recent_tradfi_win,
       b.n_typical                 as symbols_typical
from last_seen l
left join recent r   on r.source = l.source
left join baseline b on b.source = l.source
order by age_days
"""

#: SQL 参数。窗口取值集中在这里,不散落在调用点。
COVERAGE_PARAMS = {
    "recent_crypto": RECENT_DAYS_BY_DOMAIN["crypto"],
    "recent_tradfi": RECENT_DAYS_BY_DOMAIN["tradfi"],
    "base_lo": BASELINE_LO_DAYS,
    "base_hi": BASELINE_HI_DAYS,
}
