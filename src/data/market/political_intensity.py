"""政治 / 地缘强度(Jazz 11-06「政治事件必须的,而且来源很多」)—— 三个免费、有长历史、按时点可得的来源,进状态面板。

- **GPR 日度地缘政治风险指数**(Caldara & Iacoviello,美联储;报纸文章计数,1985 →):一个 xls 文件一次下载。
  `GPRD` 总指数、`GPRD_ACT`(已发生的行动)、`GPRD_THREAT`(威胁)。按可得日入库:DAY + `GPR_LAG_DAYS`(更新有几天滞后)。
- **GDELT DOC 2.0 新闻量强度**(全球新闻里匹配某主题的文章占比,2017 →):每个主题一次请求,返回整段日序列。
  主题写死在 `TOPICS`;按可得日 = 日期 + 1 入库。GDELT 限速严(实测连续请求 429,Railway 共用出口 IP 更甚)⇒ 每轮只做 `GDELT_PER_ROUND` 个最旧的主题、之间停 `GDELT_PAUSE_S` 秒。
- **经济政策不确定性 EPU**(FRED USEPUINDXD)走 `cis_inputs.CREDIT_SERIES`;**Polymarket 政治 / 地缘市场**走 `prediction_markets.TAGS`。

只记、不进敞口;是否有信息量由 lane 用 `joint_model.py` 判。表:GPR 进 `macro_daily`(series gpr / gpr_act / gpr_threat),
GDELT 进 `political_intensity_daily`(d, topic)。判活:`select topic, max(d), count(*) from political_intensity_daily group by 1`。

**11-13 起同一条循环也记市场叙事(S-855,`NARRATIVE_TOPICS`):** 每条叙事两条序列 —— 量(topic = 名字)与调(topic = 名字 + `:tone`)。
表名里的 political 是历史遗留;`feature_matrix_daily` 把这张表的每个 topic 都并成 `pol:<topic>`,叙事也会出现在那里
(`fused_knn` / `joint_forecast` 用的是冻结的特征清单,不受影响)。读它的是 ③ 档案的背景栏(`dossier_context.narratives`)。
"""
from __future__ import annotations

import datetime as dt
import io
from typing import Any, Callable, Optional

TABLE = "political_intensity_daily"
MACRO_TABLE = "macro_daily"
WRITES_TABLES = (TABLE, MACRO_TABLE)
WRITES_COLUMNS = {TABLE: ("d", "topic", "value", "source"), MACRO_TABLE: ("series", "d", "value", "source")}
LOOP_NAME = "_political_intensity_loop"
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
GPR_LAG_DAYS = 5
GPR_COLS = {"GPRD": "gpr", "GPRD_ACT": "gpr_act", "GPRD_THREAT": "gpr_threat"}
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_START = "20170101000000"
GDELT_PAUSE_S = 30.0
TOPICS = {
    "conflict": "(war OR airstrike OR invasion OR missile)",
    "sanctions": "sanctions",
    "trade_war": "(tariff OR tariffs OR \"trade war\")",
    "election_unrest": "(election OR coup OR impeachment OR protest)",
    "crypto_policy": "(crypto OR bitcoin OR stablecoin) (SEC OR regulation OR ban OR bill)",
}


#: 11-13(S-855,Jazz:「英伟达的事让全球科技股埋单…在我看来只是加息周期的 scapegoat,但这些 narrative 都是重要跟踪,它代表了情绪的方向和矢量」):
#: 市场叙事。同一个来源、同一张表、同一条循环;每条叙事两条序列 —— **量**(timelinevol:全球新闻里匹配文章的占比 = 这个故事有多响)
#: 与 **调**(timelinetone:匹配文章的平均语气 = 方向),调的那条 topic 名加后缀 `:tone`。只记、不进敞口、不进规则。
#: 这份清单是写死的、看得见的:叙事的名字是人起的,系统只量它响不响、往哪边偏;要加一条就在这里加一行。
NARRATIVE_TOPICS = {
    "ai_chips": '(Nvidia OR "AI chips" OR "AI bubble" OR semiconductor OR semiconductors)',
    "tech_selloff": '("tech stocks" OR Nasdaq) (selloff OR plunge OR rout)',
    "fed_hike": '("rate hike" OR "rate hikes" OR hawkish OR "Federal Reserve" OR Powell)',
    "inflation": '(inflation OR CPI OR "price pressures")',
    "recession": '(recession OR layoffs OR "hard landing")',
    "boj_yen": '("Bank of Japan" OR yen) (hike OR "carry trade" OR intervention)',
    "crypto_crash": '(bitcoin OR crypto) (crash OR plunge OR liquidation OR liquidations OR selloff)',
    "crypto_etf": '(bitcoin OR ether) ETF (outflow OR outflows OR inflow OR inflows)',
}
TONE_SUFFIX = ":tone"


def all_series() -> dict[str, tuple[str, str]]:
    """纯函数。{库里的 topic 名: (查询, GDELT 模式)}:政治五条只有量;叙事八条各有量与调。"""
    out = {t: (q, "timelinevol") for t, q in TOPICS.items()}
    for t, q in NARRATIVE_TOPICS.items():
        out[t] = (q, "timelinevol")
        out[t + TONE_SUFFIX] = (q, "timelinetone")
    return out


def gpr_rows(df) -> list[dict]:
    """纯函数。GPR 日表 → macro_daily 行(可得日 = DAY + GPR_LAG_DAYS)。"""
    out = []
    for _, r in df.iterrows():
        try:
            day = dt.datetime.strptime(str(int(r["DAY"])), "%Y%m%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        avail = (day + dt.timedelta(days=GPR_LAG_DAYS)).isoformat()
        for col, name in GPR_COLS.items():
            v = r.get(col)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v == v:
                out.append({"series": name, "d": avail, "value": round(v, 4), "source": "gpr_caldara_iacoviello"})
    return out


GDELT_THROTTLE_WAITS = (30.0, 90.0, 180.0)
GDELT_PER_ROUND = 3            # 11-13:序列从 5 条变 21 条(叙事的量与调),3 小时一轮 × 3 = 一天 24 条,够轮一遍


def due_topics(last: dict[str, str], today: dt.date, topics: Optional[Any] = None, rot: int = 0) -> list[str]:
    """纯函数。没有行的主题排最前,其次最久没更新的;最新可得日(= 今天 + 1)已在库的跳过;最多 GDELT_PER_ROUND 个。
    `topics` 不给 = 政治五条(旧行为);`run_once` 传全部序列。
    `rot`:把排好的队列循环右移这么多位再取 —— 一条一直不通的序列(查询写坏了 / 被限速)永远排在最前,
    序列多了以后三条坏的就能把其余的全部饿死;`run_once` 每轮把 rot 推进 GDELT_PER_ROUND,坏的照样重试,但别的也轮得到。"""
    stale = [t for t in (TOPICS if topics is None else topics) if t not in last or dt.date.fromisoformat(last[t]) < today]
    stale.sort(key=lambda t: (t in last, last.get(t, "")))
    if stale and rot:
        k = rot % len(stale)
        stale = stale[k:] + stale[:k]
    return stale[:GDELT_PER_ROUND]


def throttled(body: Any) -> bool:
    """纯函数。GDELT 限速时回的不是 JSON 而是一段「Please limit requests to one every 5 seconds…」。"""
    head = (body[:200].decode("utf-8", "ignore") if isinstance(body, (bytes, bytearray)) else str(body or "")[:200]).lstrip()
    return head.startswith("Please limit") or "limit requests" in head


def gdelt_rows(payload: Any, topic: str, mode: str = "timelinevol") -> list[dict]:
    """纯函数。DOC timelinevol / timelinetone → 行(可得日 = 日期 + 1)。两种模式返回同一个形状。"""
    out = []
    try:
        data = payload["timeline"][0]["data"]
    except (KeyError, IndexError, TypeError):
        return out
    for x in data:
        try:
            day = dt.datetime.strptime(str(x["date"])[:8], "%Y%m%d").date()
            v = float(x["value"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"d": (day + dt.timedelta(days=1)).isoformat(), "topic": topic, "value": round(v, 5), "source": f"gdelt_doc_{mode}"})
    return out


def _get_bytes(url: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


async def run_once(now: Optional[dt.datetime] = None, get: Optional[Callable[[str], bytes]] = None,
                   pause_s: float = GDELT_PAUSE_S) -> dict[str, Any]:
    import asyncio
    import json
    import urllib.parse

    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import assert_bulk_source
    from src.data.style.header import _read_all
    series = all_series()
    get = get or _get_bytes
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    out: dict[str, Any] = {"gpr": 0, "gdelt": {}, "failed": {}}
    # GPR:一个文件
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(await asyncio.to_thread(get, GPR_URL)))
        rows = gpr_rows(df)
        for i in range(0, len(rows), 1000):
            if not await supabase_upsert_table(MACRO_TABLE, rows[i:i + 1000], on_conflict="series,d"):
                raise RuntimeError("写 macro_daily 失败")
        out["gpr"] = len(rows)
    except Exception as e:                                                # noqa: BLE001 —— 一个源不通不挡其余
        out["failed"]["gpr"] = f"{type(e).__name__}: {str(e)[:120]}"
    # GDELT:每个主题一次;库里有就只取最近 15 天。11-06:Railway 出口 IP 被 GDELT 按 429 限速,一轮 5 个主题总有 4 个拿不到
    # ⇒ 每轮只做最久没更新的 GDELT_PER_ROUND 个(没有行的排最前),已经到最新可得日的跳过;循环 3 小时一轮,轮转补齐。
    from src.data.vector.market_state_writer import _sb_get
    last: dict[str, str] = {}
    for topic in series:
        rd = await _sb_get(TABLE, {"select": "d", "topic": f"eq.{topic}", "order": "d.desc", "limit": "1"})
        if rd.ok and rd.rows:
            last[topic] = str(rd.rows[0]["d"])[:10]
    todo = due_topics(last, now.date(), series, rot=int(now.timestamp() // (3 * 3600)) * GDELT_PER_ROUND)
    # 源策略管的是「这一轮向免费源扇出多少次」:清单有 21 条,但每轮最多请求 GDELT_PER_ROUND 条(轮转,一天轮一遍)⇒ 按本轮实际请求数过闸
    assert_bulk_source(len(todo), "gdelt", job=f"political intensity + market narratives(每轮最多 {GDELT_PER_ROUND} 次请求,{len(series)} 条序列轮转)")
    for k, (topic, (q, mode)) in enumerate((t, series[t]) for t in todo):
        start = GDELT_START
        if topic in last:
            start = (dt.date.fromisoformat(last[topic]) - dt.timedelta(days=15)).strftime("%Y%m%d000000")
        url = GDELT_URL + "?" + urllib.parse.urlencode({"query": q, "mode": mode, "format": "json", "startdatetime": start,
                                                        "enddatetime": now.strftime("%Y%m%d000000")})
        try:
            body = await asyncio.to_thread(get, url)
            for wait in GDELT_THROTTLE_WAITS:                             # 11-06:Railway 出口 IP 共用,首轮 5 个主题 4 个拿到限速文本
                if not throttled(body):
                    break
                await asyncio.sleep(wait if pause_s else 0)
                body = await asyncio.to_thread(get, url)
            if throttled(body):
                raise RuntimeError("GDELT 限速(重试后仍是限速文本)")
            rows = gdelt_rows(json.loads(body), topic, mode)
            if not rows:                                                  # 形状不符 / 查询没有匹配:记成不通,不记成「0 行、正常」(5b:判活要能失败)
                raise RuntimeError("GDELT 返回里没有序列(形状不符或查询无匹配)")
            for i in range(0, len(rows), 1000):
                if not await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="d,topic"):
                    raise RuntimeError(f"写 {TABLE} 失败")
            out["gdelt"][topic] = len(rows)
        except Exception as e:                                            # noqa: BLE001
            out["failed"][topic] = f"{type(e).__name__}: {str(e)[:120]}"
        if k < len(todo) - 1:
            await asyncio.sleep(pause_s)
    ok = not out["failed"]
    return {"ok": ok, **out, "failed": out["failed"] or None,
            "why": f"GPR {out['gpr']} 行 · GDELT " + ", ".join(f"{t} {n}" for t, n in out["gdelt"].items())
                   + (f" · 不通:{', '.join(out['failed'])}" if out["failed"] else "")}
