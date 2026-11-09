"""对手盘地图(11-08):一个币此刻正处在哪些「散户在疯 / 在逃」的事件窗口里,每类事件历史上之后 30 天的基率。只读、只描述。

## 为什么

对手盘族站住的几条(下架、监控标签、上币、上永续、Upbit KRW 上币、squeeze、社交量尖峰)各自有一张前向记录表,但**没有一个读者**:
探索仓提交一个名字、AI 判断臂看一个名字时,看不到「这个币 5 天前刚上 Upbit 韩元市场,这类事件之后 30 天中位 −20.7%」。
这里把六张表按 (代号, 最近 N 天) 并成一个视图,附上台账里的基率 —— 读者自己判断;**不进任何规则、不动敞口**。

## 基率(写死的是台账的数,不是重算;改了台账要改这里,`test_crowd_map` 核对每条都有台账出处)

见 `BASE_RATES`。超额的基准各不相同(PIT 等权篮 / BTC / 时点等权永续篮)—— 原样写出,不混成一个数。

判活:`curl -s -H "X-Internal-Token: …" "…/internal/crowd-map?days=30" | jq '.n, .by_kind'`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

DAYS_DEFAULT = 30

#: kind → 台账里的基率(之后 30 天超额的中位;vs = 基准;ledger = 出处;note = 必须跟着数一起出现的那句话)。
BASE_RATES: dict[str, dict[str, Any]] = {
    "delisting": {"median_30d": -0.377, "vs": "PIT 加密篮", "ledger": "S-751 / S-766", "n": 53,
                  "note": "真钱硬规则:公告即剔除(R-v2 不开新票)"},
    "listing": {"median_30d": -0.214, "vs": "PIT 加密篮", "ledger": "S-763", "n": 205,
                "note": "Binance 现货上币;公告前 30 天中位 +41%"},
    "perp_listing": {"median_30d": -0.219, "vs": "BTC", "ledger": "S-758 / S-764", "n": 142,
                     "note": "现货先有、后上 USDT 永续"},
    "upbit_krw_listing": {"median_30d": -0.207, "vs": "PIT 加密篮", "ledger": "S-770", "n": 106,
                          "note": "事件效应 9.5pp,不比 Binance 强;同币随机日本身 −11%"},
    "squeeze": {"median_30d": -0.164, "mean_30d": -0.010, "vs": "时点等权永续篮", "ledger": "S-781", "n": 341,
                "note": "典型一次跑输,右尾(+100% 以上)把均值拉回零附近 —— 排除的期望值不显著"},
    "flush": {"median_30d": -0.141, "vs": "时点等权永续篮", "ledger": "S-781(只报不判)", "n": 57,
              "note": "没有判定,只是描述"},
    "attention_spike": {"median_30d": -0.0875, "vs": "市值 ≥ 2,000 万等权篮", "ledger": "S-769 B", "n": 510,
                        "note": "同币随机日本身 −6.5%,尖峰的增量约 −2pp;Santiment 滞后 30 天"},
    "monitoring_tag": {"median_30d": -0.158, "vs": "BTC", "ledger": "S-753 / S-789", "n": 60,
                       "note": "逐句解析后的事件集(137 个代号,有价 60);58% 在 180 天内被宣布下架;打标签 → 下架公告中位 61 天、"
                               "那段 −41%。真钱硬规则(Jazz 11-08):挂着标签 ⇒ R-v2 不开新票"},
}

#: 表 → (事件日的列, 选的列, 怎么变成 kind)
SOURCES: dict[str, tuple[str, str]] = {
    "delisting_watch": ("d0", "symbol,d0,kind,title,excess_30d"),
    "binance_event_watch": ("d0", "symbol,d0,kind,title,cohort,excess_30d"),
    "crowding_watch": ("d", "symbol,d,kind,cohort,x7,x30"),
    "attention_watch": ("d", "symbol,d,z,cohort,excess_30d"),
}


def to_events(table: str, rows: list[dict], today: dt.date) -> list[dict]:
    """纯函数。一张表的行 → 统一的事件:{symbol, kind, d, age_days, so_far, base}。so_far = 已到期的 30 天超额(没到期为 None)。"""
    out = []
    dcol = SOURCES[table][0]
    for r in rows or []:
        d = str(r.get(dcol) or "")[:10]
        sym = str(r.get("symbol") or "").upper()
        if len(d) != 10 or not sym:
            continue
        if table == "delisting_watch":
            kind = "delisting"
        elif table == "attention_watch":
            kind = "attention_spike"
        else:
            kind = str(r.get("kind") or "")
        if kind not in BASE_RATES:
            continue
        so_far = r.get("x30") if table == "crowding_watch" else r.get("excess_30d")
        ev = {"symbol": sym, "kind": kind, "d": d, "age_days": (today - dt.date.fromisoformat(d)).days,
              "so_far_30d": so_far, "base": BASE_RATES[kind]}
        if r.get("title"):
            ev["title"] = str(r["title"])[:160]
        if r.get("z") is not None:
            ev["z"] = r["z"]
        out.append(ev)
    return out


def active_tags(rows: list[dict], today: dt.date) -> list[dict]:
    """纯函数。Binance 监控标签此刻挂着的币(与硬规则同一个状态机:`delisting_watch.active_tags`,按标题逐句走 —— T-308)。"""
    from src.data.signals.delisting_watch import active_tags as _on
    return [{"symbol": s, "kind": "monitoring_tag", "d": d, "age_days": (today - dt.date.fromisoformat(d)).days,
             "so_far_30d": None, "base": BASE_RATES["monitoring_tag"]} for s, d in sorted(_on(rows).items()) if len(d) == 10]


def summarize(events: list[dict]) -> dict[str, Any]:
    """纯函数。按币聚合:一个币身上同时有几类事件(「叠在一起」比单条更值得看)。"""
    by_sym: dict[str, list[dict]] = {}
    for e in events:
        by_sym.setdefault(e["symbol"], []).append(e)
    stacked = sorted(((s, sorted({e["kind"] for e in es})) for s, es in by_sym.items() if len({e["kind"] for e in es}) > 1),
                     key=lambda x: (-len(x[1]), x[0]))
    by_kind: dict[str, int] = {}
    for e in events:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    return {"n": len(events), "symbols": len(by_sym), "by_kind": by_kind,
            "stacked": [{"symbol": s, "kinds": k} for s, k in stacked[:20]]}


async def active(now: Optional[dt.datetime] = None, days: int = DAYS_DEFAULT, symbol: str = "", read=None) -> dict[str, Any]:
    """最近 days 天里发生的对手盘事件(可只看一个币)。一张表读不到 ⇒ 写进 missing,其余照出(不把「读不到」当成「没有事件」)。"""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if read is None:
        from src.data.style.header import _read_all as read
    days = max(1, min(int(days or DAYS_DEFAULT), 120))
    cut = (now.date() - dt.timedelta(days=days)).isoformat()
    sym = str(symbol or "").upper()
    events, missing = [], []
    for table, (dcol, cols) in SOURCES.items():
        params = {"select": cols, dcol: f"gte.{cut}", "order": f"{dcol}.desc"}
        if sym:
            params["symbol"] = f"eq.{sym}"
        try:
            rows = await read(table, params)
        except Exception as e:                       # noqa: BLE001 —— 一张表读不到不挡其余,但要说出来
            missing.append(f"{table}: {type(e).__name__}")
            continue
        events += to_events(table, rows or [], now.date())
    try:                                             # 11-08 S-753 ✅:监控标签不按「最近 N 天」,按「此刻还在标签上」
        tags = await read("events", {"select": "ts,title", "source": "eq.binance",
                                     "kind": "in.(monitoring_tag,monitoring_tag_removed)", "order": "ts.asc"})
        events += [e for e in active_tags(tags or [], now.date()) if not sym or e["symbol"] == sym]
    except Exception as e:                           # noqa: BLE001
        missing.append(f"events(monitoring_tag): {type(e).__name__}")
    events.sort(key=lambda e: (e["d"], e["symbol"]), reverse=True)
    return {"ok": not missing or bool(events), "as_of": now.isoformat(), "days": days, "symbol": sym or None,
            **summarize(events), "events": events[:500], "missing": missing,
            "caveat": "只描述:基率是台账里的历史中位,基准各不相同;不是信号,不进任何敞口"}
