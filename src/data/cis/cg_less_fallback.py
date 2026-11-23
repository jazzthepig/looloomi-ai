"""CG-less 兜底(Jazz 2026-11-21,卡 T-422;S-900 起在登记的停供窗内默认开)。

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

* **开关**(S-900,Jazz 11-23「make it update in daily basis first until we have cg … back」):
  `CIS_CG_LESS_FALLBACK=1` 开、`=0` 关;**没设时,在登记的停供窗 `OUTAGE`(外加回填宽限)内默认开,窗外默认关**。
  关的时候本模块**什么都不做** ⇒ 输出逐字节相同。原来是「默认关、要有人去配变量」⇒ 装上两天没人开,正式档停了四天。
* **只接停供起的日子**(`since`):默认开的那条路只让兜底供 ≥ `OUTAGE[0]` 的日子。不加这一条,
  「CG 没有、Binance 有」的任何历史日都会被接 ⇒ 开关一开就改写 `cis_rebuild_daily` 的历史行。
* **成交量按币校准**(S-900):兜底量 × 该币「CG 量 ÷ Binance 量」在 CG 最后 30 个共有日的中位数。
  不校准时两边差 6.4–24 倍 ⇒ M 支柱低 14–37 分;校准后(09-01 → 11-19,1,760 币日,比值滞后 12 天)
  吃成交量的两项与真值差 中位 1.07 分、p90 5.0。比值写进 `inputs.vol_ratio`,下游可以除回去。
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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import pandas as pd

logger = logging.getLogger(__name__)

#: 开关:"1" 开、"0" 关;没设 ⇒ 登记的停供窗内开、窗外关(`enabled`)。
ENABLE_ENV = "CIS_CG_LESS_FALLBACK"
#: 登记的 CoinGecko 停供窗:(第一个没有 CG 收盘的日子, 订阅恢复日)。与 `state_book.SOURCE_OUTAGES` 是同一件事
#: (那边记的是「最后一个有数的日子」11-19,测试钉住两边的恢复日相同)。再停一次 ⇒ 改这里,先记台账。
OUTAGE = ("2026-11-20", "2026-12-01")
#: 恢复后给回填留的天数 —— 这几天里 CG 逐日优先,还没回填到的日子仍由兜底供。
OUTAGE_GRACE_DAYS = 7
#: 成交量校准:最后多少个共有日、至少多少个才校准。
VOL_CAL_WINDOW = 30
VOL_CAL_MIN = 20
VOL_SOURCE_RAW = "volume_x_close"
VOL_SOURCE_CAL = "binance_hist_x_cg_ratio"
#: 兜底的价 / 量源:Binance 现货 USDT 日线(日线采集与 CG 无关,CG 停订阅期间照常在落)。
PRICE_SOURCE = "binance_hist"
#: 流通量 / 总量:CG 的数,但走日表而不是 live 端点 ⇒ 同一个口径,只是快照早 ≤ 1 天。
SUPPLY_TABLE = "coin_supply_daily"
#: 价 / 量的历史起点 —— 与 rebuild 读 ohlcv 的起点一致(ATH 口径可比)。
HIST_START = "2022-11-01"


def enabled(today: Optional[date] = None) -> bool:
    """开关。显式设了就听它的("1" 开 / "0" 关);没设 ⇒ 今天(UTC)落在登记的停供窗 + 回填宽限内才开。"""
    v = (os.environ.get(ENABLE_ENV) or "").strip().lower()
    if v in ("1", "on", "true", "yes"):
        return True
    if v in ("0", "off", "false", "no"):
        return False
    d = today or datetime.now(timezone.utc).date()
    return date.fromisoformat(OUTAGE[0]) <= d <= date.fromisoformat(OUTAGE[1]) + timedelta(days=OUTAGE_GRACE_DAYS)


def vol_ratio(cg_vol: Optional[pd.Series], fb_vol_usd: Optional[pd.Series],
              before: Optional[pd.Timestamp] = None) -> tuple[Optional[float], int, Optional[pd.Timestamp]]:
    """纯函数。「CG 量 ÷ 兜底量」在最后 `VOL_CAL_WINDOW` 个共有日(两边都 > 0、且早于 `before`)的中位数。

    返回 (比值, 用了几天, 最后一个共有日)。共有日不足 `VOL_CAL_MIN` ⇒ (None, n, …):**不校准**,不拿三五天的比值硬乘。
    `before` = 兜底开始供量的那一天 ⇒ 比值只用那之前的日子(CG 恢复后新落的日子不回头改停供期间用过的比值)。
    """
    if cg_vol is None or fb_vol_usd is None or not len(cg_vol) or not len(fb_vol_usd):
        return None, 0, None
    both = pd.concat([cg_vol.rename("cg"), fb_vol_usd.rename("fb")], axis=1).dropna()
    both = both[(both["cg"] > 0) & (both["fb"] > 0)]
    if before is not None:
        both = both[both.index < pd.Timestamp(before)]
    both = both.sort_index().tail(VOL_CAL_WINDOW)
    if len(both) < VOL_CAL_MIN:
        return None, int(len(both)), (both.index.max() if len(both) else None)
    return float((both["cg"] / both["fb"]).median()), int(len(both)), both.index.max()


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
    import asyncio

    from src.data.style.header import _read_all
    syms = [s for s in sym2cg if sym2cg.get(s)]
    if not syms:
        return {"px": {}, "vol": {}, "supply": {}}
    ohl = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close,volume",
                                          "source": f"eq.{PRICE_SOURCE}",
                                          "symbol": f"in.({','.join(syms)})",
                                          "trade_date": f"gte.{HIST_START}"})
    sup = await _read_all(SUPPLY_TABLE, {"select": "coin_id,d,circulating_supply,total_supply",
                                          "coin_id": f"in.({','.join(sorted({sym2cg[s] for s in syms}))})",
                                          "order": "coin_id.asc,d.asc"})
    # 三万多行逐行转日期 ⇒ 进线程(S-862 / 11-15 看门线程同一类:不在事件循环里做)
    return await asyncio.to_thread(_shape_raw, ohl, sup)


def _shape_raw(ohl: list[dict], sup: list[dict]) -> dict[str, Any]:
    """同步:读到的行 → {"px", "vol", "supply"}。"""
    raw: dict[str, Any] = {"px": {}, "vol": {}, "supply": {}}
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


def _iso_days(index, flags) -> list[str]:
    """逐日挑出「这一维是兜底供的」那些日期(ISO 字符串)。"""
    out: list[str] = []
    for d, f in zip(index, flags):
        if bool(f):
            out.append(str(pd.Timestamp(d).date()))
    return out


def _fb_day_map(px: pd.Series, from_fb, mc_from_fb, vol_from_fb) -> dict[str, list[str]]:
    """「哪一天、哪一维是兜底供的」—— 逐维逐日。

    为什么要有它:`sources` 只说「这个符号的价是兜底来的」,可读不出**口径断在哪一天**。
    而口径断点就是这套东西存在的全部理由(见 `annotate_rows` 的注释)。
    """
    out: dict[str, list[str]] = {}
    for key, flags in (("price", from_fb), ("mcap", mc_from_fb), ("volume", vol_from_fb)):
        if flags is None:
            continue
        f = flags.reindex(px.index, fill_value=False).astype(bool)
        days = _iso_days(px.index, f)
        if days:
            out[key] = days
    return out


def _empty() -> pd.Series:
    return pd.Series(dtype=float)


def _fill_static(sym: str, static: dict, sup_days: Mapping[pd.Timestamp, tuple],
                 end: Optional[pd.Timestamp], report: dict) -> None:
    """一个名字的静态供给量:CG live 没给总量 ⇒ 用日表里 ≤ 打分日的最后一条;上限没有库内来源 ⇒ 保持 None。
    只把**确实缺的**记进 `missing_dimensions`(CG 回来、live 有上限的那几天,不再把每一行都标成缺上限)。"""
    st = static.setdefault(sym, {})
    if not st.get("total_supply"):
        tot, asof = _pit_total(sup_days, end)
        if tot is not None:
            st["total_supply"] = tot
            report["sources"].setdefault(sym, {})["total_supply"] = f"{SUPPLY_TABLE}@{asof.date()}"
    st.setdefault("max_supply", None)                       # 无库内来源 ⇒ 如实缺,不许补
    miss = []
    if not st.get("max_supply"):
        miss.append("max_supply")
    if not st.get("total_supply"):
        miss.append("total_supply")
    report["missing_dimensions"][sym] = miss


def apply(data: Mapping[str, Any], assets: Mapping[str, Mapping[str, Any]],
          raw: Mapping[str, Any], sym2cg: Mapping[str, str],
          end: Optional[pd.Timestamp] = None, force: bool = False,
          since: Optional[pd.Timestamp] = None, calibrate: bool = True) -> dict[str, Any]:
    """在 `data` 上接管。只在 CG 取不到的那一维接管。返回接管报告。

    改的是 `data["crypto"][sym]` 的 (价, 市值, 成交) 三条 Series 与 `data["static"][sym]` 的
    total_supply —— **不改评分公式、不改闸门、不改公开面**。

    `force=True`(研究用:模拟「CG 那条路整个取不到」)⇒ 连 CG 的 static 也当没有,
    兜底没有的名字**就是没有**(不保留 CG 的值,否则就不是模拟)。`since` / 校准在这条路上都不生效(T-422 的量表保持可复算)。

    `since`(S-900):兜底只供 ≥ 这一天的日子 —— 更早的日子 CG 没有就是没有,不拿 Binance 去补历史。
    `calibrate`(S-900):兜底的成交量 × `vol_ratio`(共有日不够 ⇒ 不校准,点名在 `vol_uncalibrated`)。
    """
    from src.data.cis.rebuild import TRADFI
    since = None if force or since is None else pd.Timestamp(since).normalize()
    crypto = data.setdefault("crypto", {})
    static = data.setdefault("static", {})
    supply = raw.get("supply") or {}
    report: dict[str, Any] = {
        "enabled": True, "force": bool(force),
        "took_over": [], "still_missing": [], "no_fallback_price": [],
        "sources": {}, "supply_asof": {}, "supply_stale_days": {},
        "missing_dimensions": {},
        # 逐日:兜底在哪一天供的哪一维。`sources` 说「这个符号的价是兜底来的」,
        # `fb_days` 说「哪一天」—— 口径断在 11-20 还是 11-21,只有这个能回答。
        "fb_days": {},
        "since": str(since.date()) if since is not None else None,
        # 成交量校准(S-900):{sym: {ratio, n, to}};共有日不够的名字在 vol_uncalibrated(那些行的量仍是 Binance 单所)。
        "vol_cal": {}, "vol_uncalibrated": [],
        "volume_caveat": "ohlcv_daily(binance_hist) 是 Binance 现货单所日量 × 收盘价;"
                         "CG market_chart 是全交易所 24h 滚动量 —— 口径不同;vol_cal 里有的名字已按该币近 30 个共有日的"
                         "「CG ÷ Binance」中位数换算(估计值,不是 CG 的数)",
        "max_supply_caveat": "max_supply 无库内来源 ⇒ F 支柱 capped-emission bonus(0–5 分)拿不到",
    }
    for sym in list(crypto):
        if (assets.get(sym) or {}).get("class") in TRADFI:
            continue
        cg_px, cg_mc, cg_vol = crypto[sym][0], crypto[sym][1], crypto[sym][2]
        hi, lo = crypto[sym][3], crypto[sym][4]
        fb_px_all = (raw.get("px") or {}).get(sym)
        fb_px = fb_px_all
        if since is not None and fb_px is not None:
            fb_px = fb_px[fb_px.index >= since]
        has_fb = fb_px is not None and len(fb_px) > 0
        if not has_fb:
            # 兜底也拿不到这个名字的收盘价 ⇒ 这一维就是缺
            report["no_fallback_price"].append(sym)
            if force:
                crypto[sym] = (_empty(), _empty(), _empty(), hi, lo)   # 模拟 CG 路取不到 ⇒ 不留 CG 的值
            else:
                # S-900:价没有兜底,**总量仍然要补** —— CG live 一空,这个名字历史上每一天的 F 支柱都少 ~30 分
                # (HYPE / SKY:11-23 实测重建档整段被写低)。总量来自日表,与有没有兜底价无关。
                _fill_static(sym, static, supply.get(sym2cg.get(sym) or "") or {}, end, report)
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
        if since is not None:                              # 兜底的市值 / 量也只供 since 起的日子(价已经裁过)
            fb_mc = fb_mc[fb_mc.index >= since]
            fb_vol_usd = fb_vol_usd[fb_vol_usd.index >= since]
        mc, mc_from_fb = _merge_series(cg_mc, fb_mc, force)
        vol, vol_from_fb = _merge_series(cg_vol, fb_vol_usd, force)
        if calibrate and not force and fb_vol_coins is not None and bool(vol_from_fb.any()):
            # 比值用**没裁过**的兜底量(共有日都在 since 之前),只取兜底开始供量那天之前的共有日
            first_fb = min(d for d, f in zip(vol_from_fb.index, vol_from_fb) if bool(f))
            fb_all_usd = (fb_vol_coins * fb_px_all.reindex(fb_vol_coins.index)).dropna()
            ratio, n_cal, cal_to = vol_ratio(cg_vol, fb_all_usd, before=first_fb)
            if ratio is None:
                report["vol_uncalibrated"].append(sym)
            else:
                vol = vol.where(~vol_from_fb, vol * ratio)
                report["vol_cal"][sym] = {"ratio": round(ratio, 6), "n": n_cal,
                                          "to": str(pd.Timestamp(cal_to).date())}
        crypto[sym] = (px, mc.reindex(px.index), vol.reindex(px.index), hi, lo)
        days_fb = [d for d, f in zip(px.index, from_fb) if bool(f)]
        if days_fb:
            report["took_over"].append(sym)
            report["sources"][sym] = {
                "price": PRICE_SOURCE, "mcap": "circulating_supply_x_close",
                "volume": VOL_SOURCE_CAL if sym in report["vol_cal"] else VOL_SOURCE_RAW,
                "from": str(min(days_fb).date()),
                "to": str(max(days_fb).date()), "n_days": len(days_fb),
                "n_days_mcap_fb": int(mc_from_fb.sum()), "n_days_vol_fb": int(vol_from_fb.sum()),
            }
            # **逐日**记下「哪一天、哪一维是兜底供的」—— 报表上要看得见口径断在哪。
            report["fb_days"][sym] = _fb_day_map(px, from_fb, mc_from_fb, vol_from_fb)
        else:
            report["still_missing"].append(sym)
        # total_supply:CG live 缺 ⇒ 用日表里最后一条 PIT(不是 0!F 支柱要它:缺了 fdv=0、supply_ratio=0)
        st = static.setdefault(sym, {})
        if force:
            st["total_supply"] = None            # 模拟 CG live 也取不到
            st["max_supply"] = None
        _fill_static(sym, static, sup_days, end, report)
        # 供给量快照的漂移:快照日 vs 打分日
        circ_snap = _pit_circ(sup_days, pd.Index([pd.Timestamp(end).normalize()] if end is not None
                                                  else list(px.index[-1:]))).iloc[0]
        if end is not None and circ_snap == circ_snap:      # NaN 自查
            snap_dates = sorted(d for d in sup_days if d <= pd.Timestamp(end).normalize())
            if snap_dates:
                report["supply_asof"][sym] = str(snap_dates[-1].date())
                report["supply_stale_days"][sym] = int((pd.Timestamp(end).normalize() - snap_dates[-1]).days)
        miss = list(report["missing_dimensions"].get(sym) or [])      # _fill_static 已写 max_supply / total_supply
        # 流通量只在**兜底供价的那些天**才用得上(那几天的市值 = 流通量 × 价)。原来看的是整段历史:供给量日表 11-10 才开始 ⇒ 之前的日子全是 NaN ⇒
        # 每个名字、每一天的行都被标成「缺流通量」,包括 CG 自己供市值的那三年(S-900 上线前查出)。
        if days_fb and circ_at.reindex(days_fb).isna().any():       # days_fb = 兜底供价的日子(那几天的市值要靠流通量 × 价)
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
    """开关关 ⇒ 原样返回(data 一个字节都不动)。开关开 ⇒ 兜底接管并返回报告。兜底只供停供起的日子(`OUTAGE[0]`)。"""
    if not enabled():
        return data, None
    import asyncio
    sym2cg = sym2cg_map()
    raw = await load_raw(sym2cg)
    report = await asyncio.to_thread(apply, data, assets, raw, sym2cg, end, force, pd.Timestamp(OUTAGE[0]))
    data["cg_less_fallback"] = report
    return data, report


#: 兜底接管时写进 `inputs` 的来源标记 —— 键是 `inputs` 里的字段名,值是那一维的来源。
PROVENANCE_KEYS = {
    "price": ("px_source", PRICE_SOURCE),
    "mcap": ("mcap_source", "circulating_supply_x_close"),
    "volume": ("vol_source", VOL_SOURCE_RAW),
}


def _mark_provenance(r: dict, days_by_dim: Mapping[str, list[str]],
                     vol_cal: Optional[Mapping[str, Any]] = None) -> None:
    """把「这一行的价/市值/成交是兜底供的」写进 `inputs`。

    为什么必须有(这是这套东西的全部理由):**`cis_official_daily` 只追加 + 不可改**
    —— 触发器 `cis_official_daily_no_change` 拒绝 UPDATE/DELETE,发出去的档事后补不了标记。
    ⇒ 标记必须在**发布之前**就在行里;先发后补 = 补不回来。
    ⇒ 而口径差是真的(M 支柱低 ~24 分、成交额差 6.5–34 倍,见 T-422 卡的量表)——
    混在同一条正式序列里不标出来,下游会把口径断读成真实变动。

    没有兜底接管的行**一个键都不加** ⇒ 与今天逐字节相同。
    """
    if not days_by_dim:
        return
    d = r.get("d")
    if d is None:
        return
    inp = r.get("inputs")
    if not isinstance(inp, dict):
        return
    d = str(d)[:10]
    for dim, (key, value) in PROVENANCE_KEYS.items():
        if d in days_by_dim.get(dim, ()):
            inp[key] = value
            if dim == "volume" and vol_cal and vol_cal.get("ratio"):
                # S-900:这一行的量是「Binance 量 × 比值」的估计 —— 来源和比值都写进行里(只追加的表事后补不了)
                inp[key] = VOL_SOURCE_CAL
                inp["vol_ratio"] = vol_cal["ratio"]


def annotate_rows(rows: list[dict], report: Optional[Mapping[str, Any]]) -> list[dict]:
    """如实标缺 + 如实标来源:兜底接管时,把「确实缺的那几维」写进每行的 `missing`,
    把「哪一维是兜底供的、哪一天」写进每行的 `inputs`。

    * `max_supply` —— 无库内来源 ⇒ emission_bonus(≤ 5 分)拿不到。
    * `total_supply` / `circulating_supply` —— 兜底也没补上时才算缺(补上了就不标)。
    * 全市场市值(`macro_daily.total_mcap`)是**批次级**的,由 `official.completeness` 写
      「全市场市值缺(BTC 占比算不出)」,这里只标行级的。
    * 来源标记(`px_source` / `mcap_source` / `vol_source`)—— 见 `_mark_provenance` 的理由。
    """
    if not report:
        return rows
    dims = report.get("missing_dimensions") or {}
    fb_days = report.get("fb_days") or {}
    vol_cal = report.get("vol_cal") or {}
    for r in rows:
        miss = set(r.get("missing") or [])
        miss.update(dims.get(r.get("symbol")) or [])
        r["missing"] = sorted(miss)
        _mark_provenance(r, fb_days.get(r.get("symbol")) or {}, vol_cal.get(r.get("symbol")))
    return rows
