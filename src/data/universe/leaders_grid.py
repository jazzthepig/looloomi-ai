"""各行业 × 各地区的龙头 —— 研究宇宙(T-434 / 台账 S-912、S-913)。**不是 World50 成分,不进 CIS,不进任何账。**

Jazz 11-24「各行各业各地区的龙头」;11-25「公开免费的都可以获取到,不要求即时性」。

- 名单在同目录 `leaders_grid.json`,由 `docs/research/t434_leaders_grid/build_grid_v2.py` 从公开榜单编出来(30 个行业 × 10 个地区,
  格内市值第一且 ≥ 100 亿美元);**这里只放不在 World50 候选池、并且有免费价格线的名字** —— 已在候选池里的龙头沿用那边的代码与数据。
- 每个名字带价格线的层级(`tier`):`local` 本地交易所;`us_listed` 纽约 / 纳斯达克正式上市;`us_otc` 美国场外 ADR(东京 / 新加坡 404 时用,
  成交薄,收盘可能是陈的)。没有免费价格线的(印度本地、沙特、阿联酋……)不在这里,原因在 `grid_v2.json` 的 `price_why`。
- 用处:`tradfi_history.run_once` 每周把它们和候选池一起整段重取复权日线(同一个取数入口,S-913 规则 3);
  `world50_data.refresh_facts` 给其中在 SEC 申报的公司取原始财报事实(规则 4)。
- **代码撞名**:`MDT`(美敦力)在 `ohlcv_daily` 里另有币安的同名代币 —— 与已有的 `STX` / `T` 同样情况,读的时候按 `source = 'eodhd'` 过滤。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.data.universe.world50 import Candidate

PATH = Path(__file__).with_name("leaders_grid.json")
TIERS = ("local", "us_listed", "us_otc")


@lru_cache(maxsize=1)
def names() -> tuple[dict, ...]:
    return tuple(json.loads(PATH.read_text(encoding="utf-8"))["names"])


def candidates() -> tuple[Candidate, ...]:
    """研究宇宙 → `Candidate`(与轨道公司同法:只取复权价;`note` 记行业与价格线层级)。"""
    return tuple(Candidate(n["key"], n["name"], "equity", "eodhd", n["code"], n["region"], None,
                           f"龙头网格(研究宇宙,T-434):{n['industry']} · {n['tier']}")
                 for n in names())
