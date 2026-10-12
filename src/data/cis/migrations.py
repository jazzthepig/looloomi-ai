"""代币迁移(旧币按固定比例换新币)在 CIS 统一标准里的处理(S-537)。

## 为什么

MKR → SKY(1 : 24,000)、MATIC → POL(1 : 1)。CoinGecko 把两段当成两个币:MKR 的市值 2025-06-05 起记为 0、
那一天 15.5 亿美元记到 SKY 名下;POL 在 2024-09-04 之前是一个日成交 60 万美元的薄币,真正在交易的是 MATIC。
直接用「今天的币」的历史 = MKR 16 个月市值 0(基本面支柱 0)、POL 前 11 个月用错了币。

## 别家怎么做(CoinDesk Indices 2026-02 政策文件 · CF Benchmarks 多资产规则)

多资产指数里新旧币**只放一个**;换不换、哪天换看三样:交易所公告、新旧币成交对比、新旧币流通量对比;
换的那天当作「移除旧币 + 加入新币」。我们只有能按时点复原的那一样 —— 成交 —— 所以规则是:

**生效日 = 不早于迁移开始日、且新币 30 日平均成交(≥ 20 天有数)第一次超过旧币的那天。** 只用当天及以前的数据,
一旦换过去就不换回来。

## 历史怎么接

生效日之前用旧币,价格按比例换成新币单位(旧币价 ÷ 比例);市值与成交是美元,不换算。
旧币市值记为 0 而新币有市值的日子(CoinGecko 把供应挪到新币名下),市值取新币的 —— 同一份经济暴露。
高 / 低价同价格一样换算;资金费率是比率,不换算。宇宙里只出现新币的代码。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd

#: new = 宇宙里的代码;old = 迁移前的代码;ratio = 1 个旧币换几个新币;start = 迁移开始日(此前不可能生效)。
MIGRATIONS: tuple[dict[str, Any], ...] = (
    {"new": "SKY", "new_coin": "sky", "old": "MKR", "old_coin": "maker", "ratio": 24000.0, "start": "2024-09-18"},
    {"new": "POL", "new_coin": "polygon-ecosystem-token", "old": "MATIC", "old_coin": "matic-network", "ratio": 1.0,
     "start": "2024-09-04"},
)
BY_NEW = {m["new"]: m for m in MIGRATIONS}
#: 已退役的旧代码 → 新代码(对外叠加时把旧代码从正式视图里拿掉)。
RETIRED = {m["old"]: m["new"] for m in MIGRATIONS}
WINDOW, MIN_DAYS = 30, 20


def effective_day(old_vol: pd.Series, new_vol: pd.Series, start: str) -> Optional[pd.Timestamp]:
    """纯函数。新币 30 日平均成交第一次超过旧币的那天(≥ start)。数据不够判 → None。"""
    idx = pd.date_range(min(_first(old_vol), _first(new_vol), pd.Timestamp(start)),
                        max(_last(old_vol), _last(new_vol), pd.Timestamp(start)), freq="D")
    o = old_vol.reindex(idx)
    n = new_vol.reindex(idx)
    om = o.rolling(WINDOW, min_periods=1).mean().fillna(0.0)
    nm = n.rolling(WINDOW, min_periods=MIN_DAYS).mean()
    ok = (nm > om) & nm.notna() & (idx >= pd.Timestamp(start))
    hit = ok[ok]
    return hit.index[0] if len(hit) else None


def chain(old: tuple[pd.Series, ...], new: tuple[pd.Series, ...], ratio: float,
          eff: Optional[pd.Timestamp]) -> tuple[pd.Series, ...]:
    """纯函数。(价, 市值, 成交, 高, 低) 两段 → 接起来的一段。eff 为 None:新币有数据之前用旧币、之后用新币。"""
    opx, omc, ovol, ohi, olo = old
    npx, nmc, nvol, nhi, nlo = new
    if eff is None:
        first_new = _first(npx) if len(npx.dropna()) else None
        eff = first_new if first_new is not None else pd.Timestamp.max

    def before(s: pd.Series) -> pd.Series:
        return s[s.index < eff] if len(s) else s

    def after(s: pd.Series) -> pd.Series:
        return s[s.index >= eff] if len(s) else s

    px = _cat(before(opx) / ratio, after(npx))
    vol = _cat(before(ovol), after(nvol))
    hi = _cat(before(ohi) / ratio, after(nhi))
    lo = _cat(before(olo) / ratio, after(nlo))
    om = before(omc)
    nm_b = nmc.reindex(om.index) if len(nmc) else pd.Series(index=om.index, dtype=float)
    om = om.where(om > 0, nm_b)                      # 旧币市值 0、新币有市值 → 用新币的(同一份供应)
    mc = _cat(om, after(nmc))
    return tuple(s[~s.index.duplicated(keep="last")] for s in (px, mc, vol, hi, lo))


def _cat(*parts: pd.Series) -> pd.Series:
    keep = [p.astype(float) for p in parts if len(p)]
    return pd.concat(keep).sort_index() if keep else pd.Series(dtype=float)


def token_on(sym: str, d: pd.Timestamp, eff: Mapping[str, Optional[pd.Timestamp]]) -> Optional[str]:
    """纯函数。sym 在 d 这一天实际是哪个币(给 inputs 记来源用)。不是迁移名字 → None。"""
    m = BY_NEW.get(sym)
    if m is None:
        return None
    e = eff.get(sym)
    if e is not None and d >= e:
        return m["new"]
    return f"{m['old']}÷{m['ratio']:g}" if m["ratio"] != 1 else m["old"]


def _first(s: pd.Series) -> pd.Timestamp:
    s = s.dropna() if len(s) else s
    return s.index.min() if len(s) else pd.Timestamp.max


def _last(s: pd.Series) -> pd.Timestamp:
    s = s.dropna() if len(s) else s
    return s.index.max() if len(s) else pd.Timestamp.min
