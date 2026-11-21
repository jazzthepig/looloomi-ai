"""CG-less 兜底 —— **默认关**(Jazz 2026-11-21,卡 T-422)。

## 为什么有这个模块

Jazz 2026-11-21 停了 CoinGecko 订阅(省 10 天的钱)。实测代价(2026-11-21 04:50Z):
**CG Pro key 401、public 端点拒绝 Pro key ⇒ `get_cg_markets` 返回 0 行**。

代价不是「10 天没分数」,而是**官方日收盘从此卡住**:
`asset_mcap_daily`(source=`coingecko_pro_market_chart`)拿不到 ⇒ 11-20 起 0 行
⇒ 25 个加密名一个都没有收盘价 ⇒ 硬闸(`MIN_CRYPTO_PRICED=0.90`)过不去 ⇒
`cis_official_daily` 的 max(d) 停在 11-19 ⇒ 第二天也没有前一天的正式档做滞回 ⇒ **每天继续缺**。

本模块用**库里已有的原料**(不新开外呼)把「缺的那一维」补上或**如实标缺**:

| 维度 | 兜底来源 | 与 CG 的口径关系 |
|---|---|---|
| 收盘价 | `ohlcv_daily`(source=`binance_hist`).close | **不同源**:Binance 现货 USDT 日线收盘 ≠ CG 全交易所收盘 |
| 市值 | `coin_supply_daily.circulating_supply` × 当日收盘价 | **同一个式子**(CG 自己的定义就是 circ×price),但价格源不同 |
| 成交量 | `ohlcv_daily`(binance_hist).volume(币) × 当日收盘价 | **口径差大**:CG market_chart 是全交易所 24h 滚动量,Binance 只是现货单场所日量 |
| 总量 | `coin_supply_daily.total_supply` | **同一个源**(CG 的数),只是走日表而不是 live 端点 ⇒ 快照早 ≤ 1 天 |
| 上限 | **无库内来源** | **如实缺**(CG coin detail 才有)⇒ F 支柱的 emission_bonus(≤ 5 分)丢掉 |
| 全市场市值 | **无库内来源** | **如实缺**(`macro_daily.total_mcap` 也是 CG 来的)⇒ `bdom=None` ⇒ regime 判定少一个输入 |

实测覆盖(2026-11-20):25 个加密名里 **23 个有 Binance 收盘价**(缺 HYPE、SKY)⇒
兜底后 `加密名字有价的 23/25 = 0.92 ≥ MIN_CRYPTO_PRICED 0.90` ⇒ **硬闸能过**。
`coin_supply_daily` 最后一批是 2026-11-20(300 行,全部带 circ/total)⇒ CG 死后再无新批次
⇒ 11-21 起流通量**冻结在 11-20 的快照**(漂移要记)。

## 边界(卡上写死的几条)

* **开关默认关**:`os.environ["CIS_CG_LESS_FALLBACK"] == "1"` 才启用。关的时候本模块**什么都不做**
  ⇒ 输出与今天**逐字节相同**。
* **只在「CG 那条路取不到」时接管**,不是替换:能拿 CG 的日子**仍然走 CG**(口径优先)。
* **不把缺的东西补成 0 或默认值**(仓库规则:宁缺勿造)。缺就是缺,让闸门去拒。
* **不改评分公式、不改闸门、不改公开面** —— 本模块只负责「把缺的那一维补上或如实标缺」。

## 用法

    from src.data.cis.cg_less_fallback import apply_if_enabled
    data, report = await apply_if_enabled(assets, data, end)

`report` 里有:接管了哪些名字、接管的是哪一维、哪些仍然缺、供给量快照是哪一天。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Optional

import pandas as pd

logger = logging.getLogger(__name__)

#: 开关。默认关。
ENABLE_ENV = "CIS_CG_LESS_FALLBACK"
#: 兜底的价 / 量源:Binance 现货 USDT 日线(日线采集与 CG 无关,CG 停订阅期间照常在落)。
PRICE_SOURCE = "binance_hist"
#: 流通量 / 总量:CG 的数,但走日表而不是 live 端点 ⇒ 同一个口径,只是快照早 ≤ 1 天。
SUPPLY_TABLE = "coin_supply_daily"
#: 价 / 量的历史起点 —— 与 rebuild 读 ohlcv 的起点一致(ATH 口径可比)。
HIST_START = "2022-11-01"


def enabled() -> bool:
    """开关:只有 `CIS_CG_LESS_FALLBACK=1` 才启用。默认关。"""
    return os.environ.get(ENABLE_ENV) == "1"


def sym2cg_map() -> dict[str, str]:
    """符号 → CoinGecko id。迁移前的旧币也带上(旧币的历史要接成一段)。"""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.cis.migrations import MIGRATIONS
    out = {k: v.get("coingecko") for k, v in CRYPTO_ASSETS.items() if v.get("coingecko")}
    for m in MIGRATIONS:
        if m.get("old_coin"):
            out.setdefault(m["old"], m["old_coin"])
    return out


def _f(v: Any) -> Optional[float]:
    """numpy / pandas 标量 → Python float;缺失或非有限 → None(**不补 0**)。"""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


async def load_raw(sym2cg: Mapping[str, str]) -> dict[str, Any]:
    """读兜底原料(库里已有的,不外呼)。

    返回 `{"px": {sym: Series(date→close)}, "vol": {sym: Series(date→币量)},
             "supply": {cg_id: {date: (circulating, total)}}}`
    """
    from src.data.style.header import _read_all
    raw: dict[str, Any] = {"px": {}, "vol": {}, "supply": {}}
    syms = [s for s in sym2cg if sym2cg.get(s)]
    if not syms:
        return raw
    ohl = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close,volume",
                                          "source": f"eq.{PRICE_SOURCE}",
                                          "symbol": f"in.({','.join(syms)})",
                                          "trade_date": f"gte.{HIST_START}"})
    px: dict[str, dict] = {}
    vol: dict[str, dict] = {}
    for r in ohl or []:
        c = _f(r.get("close"))
        if c is None or c <= 0:
            continue
        d = pd.Timestamp(str(r.get("trade_date"))[:10])
        px.setdefault(r["symbol"], {})[d] = c
        v = _f(r.get("volume"))
        if v is not None:
            vol.setdefault(r["symbol"], {})[d] = v
    raw["px"] = {k: pd.Series(v, dtype=float).sort_index() for k, v in px.items()}
    raw["vol"] = {k: pd.Series(v, dtype=float).sort_index() for k, v in vol.items()}
    sup = await _read_all(SUPPLY_TABLE, {"select": "coin_id,d,circulating_supply,total_supply",
                                          "order": "coin_id.asc,d.asc"})
    supply: dict[str, dict] = {}
    for r in sup or []:
        cid = r.get("coin_id")
        circ = _f(r.get("circulating_supply"))
        if not cid or circ is None:
            continue
        tot = _f(r.get("total_supply"))
        supply.setdefault(cid, {})[pd.Timestamp(str(r.get("d"))[:10])] = (circ, tot)
    raw["supply"] = supply
    return raw


def _pit_circ(supply_days: Mapping[pd.Timestamp, tuple], index: pd.Index) -> pd.Series:
    """流通量的 PIT 序列:每个日期取**它之前(含当天)最后一次快照**。没有快照 → NaN(**不补 0**)。"""
    if not supply_days:
        return pd.Series(index=index, dtype=float)
    s = pd.Series({d: v[0] for d, v in sorted(supply_days.items())}, dtype=float)
    return s.reindex(index).ffill()


def _pit_total(supply_days: Mapping[pd.Timestamp, tuple], end: Optional[pd.Timestamp]
               ) -> tuple[Optional[float], Optional[pd.Timestamp]]:
    """总量:取**打分日当天或之前**最后一次快照(PIT:不用未来的供给量)。返回 (值, 快照日)。"""
    if not supply_days:
        return None, None
    cand = {d: v[1] for d, v in supply_days.items() if v[1] is not None}
    if not cand:
        return None, None
    if end is not None:
        e = pd.Timestamp(end).normalize()
        before = {d: v for d, v in cand.items() if d <= e}
        if not before:                      # 打分日之前一次快照都没有 ⇒ 缺(不用未来的)
            return None, None
        cand = before
    dmax = max(cand)
    return float(cand[dmax]), dmax


def _merge_series(cg: pd.Series, fb: pd.Series, force: bool) -> tuple[pd.Series, pd.Series]:
    """合并 CG 与兜底两路。返回 (合并后的值, 这段日期是兜底供的)。

    `force=True`(研究用:模拟「CG 那条路整个取不到」)⇒ 只用兜底。
    否则**逐日 CG 优先**:CG 那一天有值就用 CG,没有才用兜底。
    """
    cg = cg if isinstance(cg, pd.Series) else pd.Series(dtype=float)
    fb = fb if isinstance(fb, pd.Series) else pd.Series(dtype=float)
    if force:
        idx = fb.index
        val = fb.reindex(idx)
        return val, val.notna()
    idx = cg.index.union(fb.index)
    cg_re = cg.reindex(idx)
    fb_re = fb.reindex(idx)
    val = fb_re.where(cg_re.isna(), cg_re)
    from_fb = val.notna() & cg_re.isna()
    return val, from_fb


def _empty() -> pd.Series:
    return pd.Series(dtype=float)


def apply(data: Mapping[str, Any], assets: Mapping[str, Mapping[str, Any]],
          raw: Mapping[str, Any], sym2cg: Mapping[str, str],
          end: Optional[pd.Timestamp] = None, force: bool = False) -> dict[str, Any]:
    """在 `data` 上接管。只在 CG 取不到的那一维接管。返回接管报告。

    改的是 `data["crypto"][sym]` 的 (价, 市值, 成交) 三条 Series 与 `data["static"][sym]` 的
    total_supply —— **不改评分公式、不改闸门、不改公开面**。

    `force=True`(研究用:模拟「CG 那条路整个取不到」)⇒ 连 CG 的 static 也当没有,
    兜底没有的名字**就是没有**(不保留 CG 的值,否则就不是模拟)。
    """
    from src.data.cis.rebuild import TRADFI
    crypto = data.setdefault("crypto", {})
    static = data.setdefault("static", {})
    supply = raw.get("supply") or {}
    report: dict[str, Any] = {
        "enabled": True, "force": bool(force),
        "took_over": [], "still_missing": [], "no_fallback_price": [],
        "sources": {}, "supply_asof": {}, "supply_stale_days": {},
        "missing_dimensions": {},
        "volume_caveat": "ohlcv_daily(binance_hist) 是 Binance 现货单所日量 × 收盘价;"
                         "CG market_chart 是全交易所 24h 滚动量 —— 口径不同",
        "max_supply_caveat": "max_supply 无库内来源 ⇒ F 支柱 capped-emission bonus(0–5 分)拿不到",
    }
    for sym in list(crypto):
        if (assets.get(sym) or {}).get("class") in TRADFI:
            continue
        cg_px, cg_mc, cg_vol = crypto[sym][0], crypto[sym][1], crypto[sym][2]
        hi, lo = crypto[sym][3], crypto[sym][4]
        fb_px = (raw.get("px") or {}).get(sym)
        has_fb = fb_px is not None and len(fb_px) > 0
        if not has_fb:
            # 兜底也拿不到这个名字的收盘价 ⇒ 这一维就是缺
            report["no_fallback_price"].append(sym)
            if force:
                crypto[sym] = (_empty(), _empty(), _empty(), hi, lo)   # 模拟 CG 路取不到 ⇒ 不留 CG 的值
            continue
        idx = fb_px.index if force else cg_px.index.union(fb_px.index)
        px, from_fb = _merge_series(cg_px, fb_px, force)
        px = px.reindex(idx).dropna()
        if not len(px):
            report["no_fallback_price"].append(sym)
            if force:
                crypto[sym] = (_empty(), _empty(), _empty(), hi, lo)
            continue
        # 供给量 PIT(最后一个 ≤ 该日的快照)
        sup_days = supply.get(sym2cg.get(sym) or "") or {}
        circ_at = _pit_circ(sup_days, px.index)
        # 市值 = 流通量 × 价(CG 自己的定义)
        fb_mc = circ_at * px
        fb_vol_coins = (raw.get("vol") or {}).get(sym)
        fb_vol_usd = ((fb_vol_coins.reindex(px.index) * px) if fb_vol_coins is not None
                      else pd.Series(index=px.index, dtype=float))
        mc, mc_from_fb = _merge_series(cg_mc, fb_mc, force)
        vol, vol_from_fb = _merge_series(cg_vol, fb_vol_usd, force)
        crypto[sym] = (px, mc.reindex(px.index), vol.reindex(px.index), hi, lo)
        days_fb = [d for d, f in zip(px.index, from_fb) if bool(f)]
        if days_fb:
            report["took_over"].append(sym)
            report["sources"][sym] = {
                "price": PRICE_SOURCE, "mcap": "circulating_supply_x_close",
                "volume": "volume_x_close", "from": str(min(days_fb).date()),
                "to": str(max(days_fb).date()), "n_days": len(days_fb),
                "n_days_mcap_fb": int(mc_from_fb.sum()), "n_days_vol_fb": int(vol_from_fb.sum()),
            }
        else:
            report["still_missing"].append(sym)
        # total_supply:CG live 缺 ⇒ 用日表里最后一条 PIT(不是 0!F 支柱要它:缺了 fdv=0、supply_ratio=0)
        st = static.setdefault(sym, {})
        if force:
            st["total_supply"] = None            # 模拟 CG live 也取不到
            st["max_supply"] = None
        if not st.get("total_supply"):
            tot, asof = _pit_total(sup_days, end)
            if tot is not None:
                st["total_supply"] = tot
                report["sources"].setdefault(sym, {})["total_supply"] = f"{SUPPLY_TABLE}@{asof.date()}"
        # max_supply:无库内来源 ⇒ 保持 None(如实缺,不许补)
        st.setdefault("max_supply", None)
        # 供给量快照的漂移:快照日 vs 打分日
        circ_snap = _pit_circ(sup_days, pd.Index([pd.Timestamp(end).normalize()] if end is not None
                                                  else list(px.index[-1:]))).iloc[0]
        if end is not None and circ_snap == circ_snap:      # NaN 自查
            snap_dates = sorted(d for d in sup_days if d <= pd.Timestamp(end).normalize())
            if snap_dates:
                report["supply_asof"][sym] = str(snap_dates[-1].date())
                report["supply_stale_days"][sym] = int((pd.Timestamp(end).normalize() - snap_dates[-1]).days)
        miss = ["max_supply"]
        if not st.get("total_supply"):
            miss.append("total_supply")
        if not (circ_at.reindex(px.index).notna().all()):
            miss.append("circulating_supply")
        report["missing_dimensions"][sym] = miss
    # 批次级硬输入:全市场市值是 CG 来的,没有库内来源 ⇒ 缺就是缺(不许用 0 假装有)。
    # 缺了它 ⇒ BTC 占比算不出 ⇒ regime 判定少一个输入(还有 btc30 / fng / vix)。
    batch_missing: list[str] = []
    _mac = (data.get("macro") or {}).get("total_mcap") or {}
    _k = pd.Timestamp(end).normalize() if end is not None else None
    if _k is not None and not _mac.get(_k):
        batch_missing.append("macro.total_mcap")
    report["batch_missing"] = batch_missing
    report["no_max_supply"] = sorted(s for s in crypto
                                      if not (static.get(s) or {}).get("max_supply")
                                      and (assets.get(s) or {}).get("class") not in TRADFI)
    report["still_missing_total_supply"] = sorted(s for s in crypto
                                                   if not (static.get(s) or {}).get("total_supply")
                                                   and (assets.get(s) or {}).get("class") not in TRADFI)
    if report["took_over"]:
        logger.warning("CG-less 兜底接管 %d 个名字:%s", len(report["took_over"]),
                       ",".join(sorted(report["took_over"])))
    if report["no_fallback_price"]:
        logger.warning("CG-less 兜底拿不到收盘价 %d 个名字:%s", len(report["no_fallback_price"]),
                       ",".join(sorted(report["no_fallback_price"])))
    return report


async def apply_if_enabled(assets: Mapping[str, Mapping[str, Any]], data: dict[str, Any],
                            end: Optional[pd.Timestamp] = None, force: bool = False
                            ) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """开关关 ⇒ 原样返回(data 一个字节都不动)。开关开 ⇒ 兜底接管并返回报告。"""
    if not enabled():
        return data, None
    sym2cg = sym2cg_map()
    raw = await load_raw(sym2cg)
    report = apply(data, assets, raw, sym2cg, end=end, force=force)
    data["cg_less_fallback"] = report
    return data, report


def annotate_rows(rows: list[dict], report: Optional[Mapping[str, Any]]) -> list[dict]:
    """如实标缺:兜底接管时,把「确实缺的那几维」写进每行的 `missing`。

    * `max_supply` —— 无库内来源 ⇒ emission_bonus(≤ 5 分)拿不到。
    * `total_supply` / `circulating_supply` —— 兜底也没补上时才算缺(补上了就不标)。
    * 全市场市值(`macro_daily.total_mcap`)是**批次级**的,由 `official.completeness` 写
      「全市场市值缺(BTC 占比算不出)」,这里只标行级的。
    """
    if not report:
        return rows
    dims = report.get("missing_dimensions") or {}
    for r in rows:
        miss = set(r.get("missing") or [])
        miss.update(dims.get(r.get("symbol")) or [])
        r["missing"] = sorted(miss)
    return rows
