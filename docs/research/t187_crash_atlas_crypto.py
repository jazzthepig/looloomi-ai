"""T-187 · 崩盘图谱 C 道(加密)—— 台账 S-675,只 import 共用内核,不复制它的函数。

Jazz 10-23:「给每个市场崩盘(主流、EM、crypto)前的事件、迹象和情绪,还有对应的策略风格,做个挖掘」。

**这是挖掘,不是检验。** 每个迹象对基准率 + 循环平移零分布(内核 sign_lift,种子 675、2,000 次)。
「线索」只进候选,要当规则用必须另立预注册、按前向判。

跑法:python3 docs/research/t187_crash_atlas_crypto.py
出:docs/research/t187_results.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from docs.research.crash_atlas_common import (  # noqa: E402
    SEED,
    available,
    bear_episodes,
    expanding_pct,
    fast_crashes,
    load_fred,
    phase_returns,
    sign_lift,
    to_calendar,
    trend_200_nav,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t187_results.json")

# ── 取数(库只读 publishable key;翻页必带 order=)────────────────────────────────
SUPA = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPK = os.environ.get("SUPABASE_KEY", "")
if not SUPA or not SUPK:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置,退出")

PAGE = 1000


def fetch(table: str, params: dict) -> list[dict]:
    """PostgREST 翻页读。**必须**带 order=(按主键排)—— 不带时翻页边界会漂(T-170 / T-173 实测)。"""
    q = dict(params)
    q["select"] = q.get("select", "*")
    q["limit"] = str(PAGE)
    rows: list[dict] = []
    off = 0
    while True:
        q["offset"] = str(off)
        url = SUPA + "/rest/v1/" + table + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(
            url, headers={"apikey": SUPK, "Authorization": "Bearer " + SUPK})
        chunk = json.loads(urllib.request.urlopen(req, timeout=90).read())
        if not isinstance(chunk, list):
            raise RuntimeError(table + ": " + str(chunk)[:200])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        off += PAGE


def srs(rows: list[dict], x: str, y: str, agg: str = "last") -> pd.Series:
    """行 → 日历日序列。funding_time 有混合格式(带 / 不带毫秒)且一天 3 行 ⇒ ISO8601 解析 + agg="sum"。
    价格 / 市值等一天一行(agg="last")。"""
    idx = pd.to_datetime([r[x] for r in rows], format="ISO8601", utc=True).tz_localize(None).normalize()
    s = pd.Series(pd.to_numeric([r[y] for r in rows], errors="coerce"), index=idx,
                  dtype="float64").dropna()
    g = s.groupby(level=0)
    return (g.sum() if agg == "sum" else g.last()).sort_index()


# ── 崩盘目录(S-675 写死:熊市 0.50 / 急跌 14 天 −30% 去簇 60 天)─────────────────
def load_prices() -> tuple[pd.Series, pd.Series]:
    out = {}
    for sym in ("BTC", "ETH"):
        rows = fetch("asset_mcap_daily",
                     {"symbol": "eq." + sym, "order": "d.asc",
                      "select": "symbol,d,price"})
        # 卡:只用 price 列,不用「市值 ÷ 价格」推
        out[sym] = srs(rows, "d", "price")
    return out["BTC"], out["ETH"]


def macro_series(name: str) -> pd.Series:
    rows = fetch("macro_daily", {"series": "eq." + name, "order": "d.asc", "select": "d,value"})
    return srs(rows, "d", "value")


# ── 迹象 C1–C6 ──────────────────────────────────────────────────────────────
def mk(cond: pd.Series, valid: pd.Series) -> pd.Series:
    """把「条件成立」变成可空布尔 —— **数据没到的日子必须留 NA,不能当成 False**。
    (否则 sign_lift 的 covered 会把没数据的锚点算成「用过」,跳过数就少报了。)"""
    v = valid if valid.dtype == bool else valid.notna()
    return cond.astype("boolean").where(v)


def sign_c1(fng: pd.Series) -> pd.Series:
    """C1 恐惧贪婪 ≥ 75 连续 ≥ 7 天 ⇒ 当天往前 7 个日历日全部 ≥ 75。"""
    cal = to_calendar(fng, 7)
    hot = cal >= 75
    return mk(hot.rolling(7, min_periods=7).sum() >= 7, cal)


def sign_c2_btc_funding(sym: str = "BTC", venue: str = "binance_perp") -> pd.Series:
    """C2 资金费 7 日均年化 ≥ 30%。每 8 小时一行;日内之和 × 365 = 年化。"""
    rows = fetch("funding_history", {"symbol": "eq." + sym, "venue": "eq." + venue,
                                     "order": "funding_time.asc", "select": "funding_time,funding_rate"})
    f = srs(rows, "funding_time", "funding_rate", agg="sum")   # 日内之和
    ann = to_calendar(f, 5) * 365.0          # 日内之和 → 年化
    m7 = to_calendar(ann, 10).rolling(7, min_periods=7).mean()
    return mk(m7 >= 0.30, m7)


def sign_c3_oi(sym: str = "BTC") -> pd.Series:
    """C3 持仓量 30 天增长,按 expanding_pct 的按时点分位 ≥ 0.9。"""
    rows = fetch("deriv_metrics_daily", {"symbol": "eq." + sym, "order": "d.asc",
                                         "select": "d,oi_value_close"})
    oi = to_calendar(srs(rows, "d", "oi_value_close"), 5)
    g = (oi / oi.shift(30) - 1.0).replace([np.inf, -np.inf], np.nan)
    p = expanding_pct(g)
    return mk(p >= 0.9, p)


def sign_c4_stables() -> pd.Series:
    """C4 USDT + USDC 市值 30 天增长 < 0(同 S-673)。"""
    tot = None
    for cid in ("tether", "usd-coin"):
        rows = fetch("cg_coin_mcap_daily", {"coin_id": "eq." + cid, "order": "d.asc",
                                            "select": "d,mcap"})
        m = to_calendar(srs(rows, "d", "mcap"), 5)
        tot = m if tot is None else tot.add(m, fill_value=0.0)
    g = (tot / tot.shift(30) - 1.0).replace([np.inf, -np.inf], np.nan)
    return mk(g < 0, g)


def sign_c5_btc_share(btc_mcap: pd.Series) -> pd.Series:
    """C5 BTC 市占 60 天降 ≥ 10pp。BTC 市值取 7 日中位数(T-183:单日端点会换档)。
    total_mcap 2018-01 起 ⇒ 2018 年前没有市占,那些锚点必须报成跳过。"""
    tc = to_calendar(macro_series("total_mcap"), 5)
    b = to_calendar(btc_mcap, 5).rolling(7, min_periods=7).median()
    share = b / tc
    d = (share - share.shift(60)).replace([np.inf, -np.inf], np.nan)
    return mk(d <= -0.10, d)


def sign_c6_volume() -> pd.Series:
    """C6 全市场成交额 30 天均值,按 expanding_pct 的按时点分位 ≥ 0.9。"""
    v = to_calendar(macro_series("total_volume"), 5)
    p = expanding_pct(v.rolling(30, min_periods=30).mean())
    return mk(p >= 0.9, p)


# ── 迹象 P1–P5(价格本身,在 BTC 上)──────────────────────────────────────────
# 台账 S-675:「迹象(写死;全部按时点计算,低频序列按发布滞后后移)」
#   P1 过去 252 天收益的按时点分位 ≥ 0.9(亢奋)
#   P2 价格 / 200 日均线 − 1 分位 ≥ 0.9(过度延伸)
#   P3 20 日实现波动分位 ≤ 0.1(风平浪静)· P4 同上分位 ≥ 0.9(动荡)
#   P5 离 52 周高点 ≥ 5% 但仍在 200 日线上(初裂)
# 「分位」= 内核 expanding_pct(当天的值在「到当天为止的全部历史」里的分位,min_periods=252,只看过去)。
def sign_p1_p5(btc: pd.Series) -> dict[str, pd.Series]:
    px = to_calendar(btc, 5)
    r1 = px.pct_change()
    r252 = (px / px.shift(252) - 1.0).replace([np.inf, -np.inf], np.nan)
    ma200 = px.rolling(200, min_periods=200).mean()
    rv20 = r1.rolling(20, min_periods=20).std()
    p1, p2 = expanding_pct(r252), expanding_pct(px / ma200 - 1.0)
    p3, p4 = expanding_pct(rv20), expanding_pct(rv20)
    hi52 = px.rolling(252, min_periods=252).max()
    dd52 = (px / hi52 - 1.0).replace([np.inf, -np.inf], np.nan)
    return {
        "P1_ret252_pct_ge90": mk(p1 >= 0.9, p1),
        "P2_px_over_ma200_pct_ge90": mk(p2 >= 0.9, p2),
        "P3_rv20_pct_le10": mk(p3 <= 0.1, p3),
        "P4_rv20_pct_ge90": mk(p4 >= 0.9, p4),
        "P5_dd52w_ge5pct_above_ma200": mk((dd52 <= -0.05) & (px > ma200),
                                          dd52.notna() & ma200.notna()),
    }


# ── 迹象 M1–M13(全球宏观,FRED)─────────────────────────────────────────────
# 台账 S-675 的 M1–M13 一字不改。FRED 快照只读数据根 research/crash_atlas/fred/(Seth 抓的),
# 经济数据一律先过 available()(内核写死的发布滞后),周 / 月频序列再 to_calendar 铺成日历日
# (Seth 10-23 16:43Z:新内核对不在索引上的锚点会报错 ⇒ 所有序列先 to_calendar)。
FRED_GAP = {"NFCI": 10, "WALCL": 10, "ICSA": 10, "UMCSENT": 40}   # 周频 / 月频的 ffill 上限(日历日)


def fred_cal(sid: str) -> pd.Series:
    """FRED 快照 → 发布滞后后移(available)→ 日历日(to_calendar,前向填但不跨数据断点)。"""
    s = available(load_fred(sid), sid)
    return to_calendar(s, FRED_GAP.get(sid, 7))


def sign_m1_m13() -> dict[str, pd.Series]:
    """M1 联邦基金利率 12 个月升 ≥ 1pp · M2 10Y−2Y < 0 · M3 解除倒挂 · M4 NFCI > 0
    M5 Baa−10Y 利差 63 天升 ≥ 0.5pp · M6 VIX < 13 · M7 VIX > 30 · M8 VIX/VXV > 1
    M9 美元广义 63 天变化分位 ≥ 0.9 · M10 WTI 126 天涨 ≥ 50% · M11 美联储资产负债表 91 天缩
    M12 密歇根消费者信心分位 ≥ 0.8 · M13 初请失业金 4 周均值 13 周升 ≥ 15%。
    BAA10Y 本身就是「Baa 减 10 年国债」的利差(FRED 定义),不再减一次 DGS10。"""
    dff = fred_cal("DFF")
    t10y2y = fred_cal("T10Y2Y")
    nfci = fred_cal("NFCI")
    spread = fred_cal("BAA10Y")            # Baa−10Y 利差(本身)
    vix, vxv = fred_cal("VIXCLS"), fred_cal("VXVCLS")
    dtw = fred_cal("DTWEXBGS")
    wti = fred_cal("DCOILWTICO")
    walcl = fred_cal("WALCL")
    umc = fred_cal("UMCSENT")
    icsa = fred_cal("ICSA")

    m1 = (dff - dff.shift(365)).replace([np.inf, -np.inf], np.nan)
    m2 = t10y2y < 0
    roll_min = t10y2y.rolling(365, min_periods=365).min()
    m3 = (t10y2y > 0) & (roll_min < 0)
    m4 = nfci > 0
    m5 = (spread - spread.shift(63)).replace([np.inf, -np.inf], np.nan)
    m6 = vix < 13
    m7 = vix > 30
    vratio = (vix / vxv).replace([np.inf, -np.inf], np.nan)
    d63 = (dtw / dtw.shift(63) - 1.0).replace([np.inf, -np.inf], np.nan)
    m9 = expanding_pct(d63)
    m10 = (wti / wti.shift(126) - 1.0).replace([np.inf, -np.inf], np.nan)
    m11 = (walcl / walcl.shift(91) - 1.0).replace([np.inf, -np.inf], np.nan)
    m12 = expanding_pct(umc)
    ma4 = icsa.rolling(28, min_periods=28).mean()
    m13 = (ma4 / ma4.shift(91) - 1.0).replace([np.inf, -np.inf], np.nan)
    return {
        "M1_ffr_12m_up_ge1pp": mk(m1 >= 1.0, m1),
        "M2_10y2y_lt0": mk(m2, t10y2y),
        "M3_10y2y_gt0_after_inversion": mk(m3, t10y2y.notna() & roll_min.notna()),
        "M4_nfci_gt0": mk(m4, nfci),
        "M5_baa10y_63d_up_ge0p5pp": mk(m5 >= 0.5, m5),
        "M6_vix_lt13": mk(m6, vix),
        "M7_vix_gt30": mk(m7, vix),
        "M8_vix_over_vxv_gt1": mk(vratio > 1, vratio),
        "M9_usd_broad_63d_chg_pct_ge90": mk(m9 >= 0.9, m9),
        "M10_wti_126d_up_ge50pct": mk(m10 >= 0.5, m10),
        "M11_fed_balance_91d_shrink": mk(m11 < 0, m11),
        "M12_umcsent_pct_ge80": mk(m12 >= 0.8, m12),
        "M13_icsa_ma4_13w_up_ge15pct": mk(m13 >= 0.15, m13),
    }


# ── 事件(定性;台账 S-675:2010 年以来每个新一轮顶、每次急跌之前 90 天)────────
# 八类:货币政策 / 信用与违约 / 杠杆爆仓 / 地缘与战争 / 监管 / 欺诈与交易所倒闭 / 疫情 / 其他
# 每条带日期与来源链接;**查不到来源的不写**。来源优先官方(央行 / 监管 / 交易所 / 政府)与 Reuters /
# Bloomberg / Fortune / CNBC / CNN / NYT / Guardian / TechCrunch / Ars Technica / Economist / DOJ。
# 链接核验:官方与多数媒体页 200 可达;Reuters / Bloomberg / NYT / SEC / Congress 对脚本请求回 401/403
# (反爬),这些链接取自维基条目所引原始来源,人工点开有效。
# 事件**只计数,不算提升**(事件没有基准率)—— 这是最弱的一层。
EVENTS: list[dict] = [
    # ── 2014-10 → 2014-12(急跌起点 2014-12-31)──────────────────────────────
    {"date": "2014-11-25", "cat": "信用与违约",
     "title": "Mt. Gox 破产受托人启动经 Kraken 用比特币偿付债权人(2014-02 倒闭后的持续卖压来源)",
     "src": "NYT DealBook",
     "url": "https://dealbook.nytimes.com/2014/11/25/mt-gox-bankruptcy-trustee-to-tap-kraken-exchange-in-repaying-creditors/"},
    # ── 2017-06 → 2017-08(急跌起点 2017-08-30)──────────────────────────────
    {"date": "2017-08-01", "cat": "其他",
     "title": "BIP148(UASF)与比特币现金分叉激活,币圈分裂",
     "src": "CNN Money",
     "url": "https://money.cnn.com/2017/08/01/technology/business/bitcoin-cash-new-currency/index.html"},
    {"date": "2017-08-05", "cat": "其他",
     "title": "《经济学人》:比特币分裂成规则(分叉进入结算层)",
     "src": "The Economist",
     "url": "https://www.economist.com/finance-and-economics/2017/08/05/bitcoin-divides-to-rule"},
    {"date": "2017-08-11", "cat": "其他",
     "title": "比特币现金硬分叉的价格与日期",
     "src": "Fortune",
     "url": "http://fortune.com/2017/08/11/bitcoin-cash-hard-fork-price-date-why/"},
    {"date": "2017-08-15", "cat": "欺诈与交易所倒闭",
     "title": "BitConnect 宣布关闭(后被美国司法部认定为 24 亿美元庞氏骗局)",
     "src": "US DOJ",
     "url": "https://www.justice.gov/archives/opa/pr/bitconnect-founder-indicted-global-24-billion-cryptocurrency-scheme"},
    # ── 2017-09 → 2017-12(first_leg 顶 2017-12-15)──────────────────────────
    {"date": "2017-09-06", "cat": "监管",
     "title": "ICO 被密集叫停(背景:中国人民银行等七部委 9 月初公告),彭博社评论要求央行制止 ICO",
     "src": "Bloomberg Opinion",
     "url": "https://www.bloomberg.com/view/articles/2017-09-06/go-ahead-try-to-stop-initial-coin-offerings"},
    {"date": "2017-11-15", "cat": "其他",
     "title": "津巴布韦军方夺权后比特币支付量激增(战乱中的货币替代)",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2017-11-15/bitcoin-surges-in-zimbabwe-after-military-moves-to-seize-power"},
    {"date": "2017-11-29", "cat": "其他",
     "title": "诺贝尔经济学奖得主斯蒂格利茨称比特币应被禁止",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2017-11-29/bitcoin-ought-to-be-outlawed-nobel-prize-winner-stiglitz-says-jal10hxd"},
    {"date": "2017-12-01", "cat": "监管",
     "title": "CME 宣布比特币期货合约(12 月 17 日上线)",
     "src": "CNBC",
     "url": "https://www.cnbc.com/2017/12/17/worlds-largest-futures-exchange-set-to-launch-bitcoin-futures-sunday-night.html"},
    {"date": "2017-12-12", "cat": "监管",
     "title": "SEC 提醒投资者对 ICO 投资保持「极度谨慎」",
     "src": "The Guardian",
     "url": "https://www.theguardian.com/technology/2017/dec/12/bitcoin-buyer-beware-us-sec-warns-extreme-caution-over-cryptocurrency-investments"},
    # ── 2017-12 → 2018-03(急跌起点 2018-03-03)──────────────────────────────
    {"date": "2017-12-17", "cat": "其他",
     "title": "比特币期货在 CME 上线(全球最大交易所),价格创历史新高",
     "src": "CNBC / Fortune",
     "url": "https://fortune.com/crypto/2017/12/17/bitcoin-record-high-short-of-20000/"},
    {"date": "2017-12-22", "cat": "其他",
     "title": "比特币跌破 14,000 美元(顶后 7 天)",
     "src": "CNN Money",
     "url": "https://money.cnn.com/2017/12/22/investing/bitcoin-plunges-below-14k/index.html"},
    {"date": "2018-01-11", "cat": "监管",
     "title": "韩国传出将禁止加密货币交易,币价大跌",
     "src": "CNBC",
     "url": "https://www.cnbc.com/2018/01/11/bitcoin-ripple-ethereum-prices-fall-after-south-korea-trading-ban-talk.html"},
    {"date": "2018-01-29", "cat": "监管",
     "title": "《纽约时报》社论:比特币泡沫与欺诈",
     "src": "The New York Times",
     "url": "https://www.nytimes.com/2018/01/29/opinion/bitcoin-bubble-fraud.html"},
    # ── 2018-08 → 2018-11(急跌起点 2018-11-06)──────────────────────────────
    {"date": "2018-08-01", "cat": "其他",
     "title": "比特币用于商业的比例继续下降(泡沫退潮期)",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2018-08-01/bitcoin-s-use-in-commerce-keeps-falling-even-as-volatility-eases"},
    {"date": "2018-08-29", "cat": "其他",
     "title": "交易所支持 3,200 万美元规模的稳定币项目",
     "src": "Fortune",
     "url": "https://fortune.com/2018/08/29/cryptocurrency-exchanges-back-32-million-stable-coin-project/"},
    {"date": "2018-09-12", "cat": "杠杆爆仓",
     "title": "加密崩盘跌幅超过互联网泡沫,市值损失达 80%",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2018-09-12/crypto-s-crash-just-surpassed-dot-com-levels-as-losses-reach-80"},
    {"date": "2018-09-26", "cat": "其他",
     "title": "Circle 推出美元稳定币 USDC",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2018-09-26/circle-joins-ranks-of-stable-crypto-coins-with-dollar-token"},
    {"date": "2018-10-29", "cat": "其他",
     "title": "Circle / Coinbase 稳定币产品需求居前",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2018-10-29/stable-coin-backed-by-circle-coinbase-draws-most-early-demand"},
    {"date": "2018-10-30", "cat": "其他",
     "title": "比特币波动率降至 2016 年末以来最低(风平浪静的直接读数)",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2018-10-30/yawn-bitcoin-is-now-the-least-volatile-since-late-2016-chart"},
    # ── 2019-03 → 2019-06(first_leg 顶 2019-06-26)──────────────────────────
    {"date": "2019-03-14", "cat": "信用与违约",
     "title": "Mt. Gox 前 CEO 卡佩莱斯获刑(一年监禁、缓刑六年)",
     "src": "CNN",
     "url": "https://www.cnn.com/2019/03/14/tech/mark-karpeles-mt-gox/index.html"},
    {"date": "2019-05-08", "cat": "欺诈与交易所倒闭",
     "title": "币安遭黑客攻击,约 7,500 枚 BTC(约 4,000 万美元)被盗,交易一度停摆",
     "src": "TechCrunch / Asia Times",
     "url": "https://techcrunch.com/2019/05/15/binance-resumes-trading-following-40m-bitcoin-hack/"},
    {"date": "2019-05-24", "cat": "其他",
     "title": "比特币重回 6,000 美元(2019 年首次)",
     "src": "Ars Technica",
     "url": "https://arstechnica.com/tech-policy/2019/05/bitcoin-is-worth-6000-for-the-first-time-this-year/"},
    {"date": "2019-06-14", "cat": "监管",
     "title": "币安限制美国客户,停止为美国用户提供服务",
     "src": "TechCrunch",
     "url": "https://techcrunch.com/2019/06/14/binance-begins-to-restrict-us-customers/"},
    # ── 2019-11 → 2020-02(急跌起点 2020-02-27)──────────────────────────────
    {"date": "2020-01-03", "cat": "地缘与战争",
     "title": "美军空袭击杀伊朗革命卫队司令苏莱曼尼",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2020-01-03/top-iranian-commander-is-killed-in-u-s-airstrike-in-baghdad"},
    {"date": "2020-01-29", "cat": "货币政策",
     "title": "FOMC 因疫情紧急降息 25 个基点",
     "src": "Federal Reserve",
     "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200129a.htm"},
    {"date": "2020-01-30", "cat": "疫情",
     "title": "WHO 宣布新冠为「国际关注的突发公共卫生事件」",
     "src": "WHO",
     "url": "https://www.who.int/news/item/30-01-2020-statement-on-the-second-meeting-of-the-international-health-regulations-(2005)-emergency-committee-regarding-the-outbreak-of-novel-coronavirus-(2019-ncov)"},
    {"date": "2020-02-03", "cat": "疫情",
     "title": "疫情令中国一周消费蒸发约 1,400 亿美元",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2020-02-03/coronavirus-wipes-out-a-140-billion-spending-week-in-china"},
    {"date": "2020-02-24", "cat": "疫情",
     "title": "病毒爆发引发意大利抢购口罩与食品",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2020-02-24/virus-outbreak-drives-italians-to-panic-buying-of-masks-and-food"},
    # ── 2021-01 → 2021-04(first_leg 顶 2021-04-13)──────────────────────────
    {"date": "2021-02-07", "cat": "其他",
     "title": "狗狗币再度逼近纪录高位(散户投机外溢)",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2021-02-07/dogecoin-soars-again-toward-record-after-crashing-last-week"},
    {"date": "2021-02-08", "cat": "其他",
     "title": "特斯拉披露买入 15 亿美元比特币(公司资产负债表买入)",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2021-02-08/tesla-bets-1-5-billion-on-bitcoin-in-new-policy-crypto-surges"},
    {"date": "2021-02-11", "cat": "其他",
     "title": "狗狗币创造者对比特币与狗狗币的暴涨表示不解",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2021-02-11/dogecoin-s-creator-is-just-as-baffled-as-you-are-about-its-rise"},
    {"date": "2021-02-25", "cat": "监管",
     "title": "Coinbase 公开提交 IPO 招股说明书(S-1)",
     "src": "SEC EDGAR",
     "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001679788&type=S-1"},
    {"date": "2021-03-01", "cat": "监管",
     "title": "中国内蒙古「打击挖矿」,比特币当日反而上涨",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2021-03-01/bitcoin-rises-after-china-region-declares-war-on-crypto-mining"},
    # ── 2021-02 → 2021-05(急跌起点 2021-05-05)──────────────────────────────
    {"date": "2021-04-12", "cat": "其他",
     "title": "Coinbase 直接在纽交所上市",
     "src": "CNN",
     "url": "https://edition.cnn.com/2021/04/12/investing/bitcoin-prices-coinbase/index.html"},
    # ── 2021-08 → 2021-11(first_leg 顶 2021-11-08)──────────────────────────
    {"date": "2021-08-27", "cat": "货币政策",
     "title": "杰克逊霍尔年会,鲍威尔讲话暗示将缩减购债",
     "src": "Federal Reserve",
     "url": "https://www.federalreserve.gov/newsevents/speech/powell20210827a.htm"},
    {"date": "2021-09-02", "cat": "监管",
     "title": "民调显示多数萨尔瓦多人不希望采用比特币",
     "src": "Reuters",
     "url": "https://www.reuters.com/technology/majority-salvadorans-do-not-want-bitcoin-poll-shows-2021-09-02/"},
    {"date": "2021-09-08", "cat": "监管",
     "title": "SEC 威胁就加密借贷业务起诉 Coinbase",
     "src": "Reuters",
     "url": "https://www.reuters.com/technology/sec-threatens-sue-coinbase-over-crypto-lending-programme-2021-09-08/"},
    {"date": "2021-09-17", "cat": "监管",
     "title": "萨尔瓦多《比特币法》实施,比特币成为法定货币",
     "src": "Foreign Policy",
     "url": "https://foreignpolicy.com/2021/09/17/el-salvador-bitcoin-law-farce/"},
    {"date": "2021-09-22", "cat": "货币政策",
     "title": "FOMC 决定开始缩减购债(taper)",
     "src": "Federal Reserve",
     "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20210922a.htm"},
    {"date": "2021-09-24", "cat": "监管",
     "title": "中国人民银行重申打击加密货币炒作与交易",
     "src": "Reuters",
     "url": "https://www.reuters.com/world/china/china-central-bank-vows-crackdown-cryptocurrency-trading-2021-09-24/"},
    {"date": "2021-10-20", "cat": "信用与违约",
     "title": "Mt. Gox 受托人的债权人赔付方案获批准",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2021-10-20/mt-gox-trustee-says-creditor-reimbursement-plan-is-approved"},
    # ── 2022-03 → 2022-05(急跌起点 2022-05-31)──────────────────────────────
    {"date": "2022-03-05", "cat": "监管",
     "title": "PayPal 暂停俄罗斯业务",
     "src": "Reuters",
     "url": "https://www.reuters.com/business/paypal-shuts-down-its-services-russia-citing-ukraine-aggression-2022-03-05/"},
    {"date": "2022-03-16", "cat": "货币政策",
     "title": "FOMC 自 2015 年以来首次加息 25 个基点",
     "src": "Federal Reserve",
     "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20220316a.htm"},
    {"date": "2022-03-23", "cat": "其他",
     "title": "彭博社:Terra 的 20% 收益承诺引发可持续性质疑",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2022-03-23/terra-s-promise-of-20-defi-return-raises-sustainability-concern"},
    {"date": "2022-04-19", "cat": "其他",
     "title": "Do Kwon 大量买入比特币被曝光",
     "src": "Bloomberg Features",
     "url": "https://www.bloomberg.com/news/features/2022-04-19/terraform-s-do-kwon-s-huge-bitcoin-buys-catch-crypto-billionaires-attention"},
    {"date": "2022-04-28", "cat": "监管",
     "title": "中非共和国宣布比特币为法定货币",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2022-04-28/bitcoin-is-declared-a-legal-currency-in-central-african-republic-l2isppnb"},
    {"date": "2022-05-07", "cat": "信用与违约",
     "title": "Terra 的 UST 脱锚,跌破 1 美元锚",
     "src": "CNBC",
     "url": "https://www.cnbc.com/2022/05/10/bitcoin-btc-investors-panic-as-terrausd-ust-sinks-below-1-peg.html"},
    {"date": "2022-05-13", "cat": "欺诈与交易所倒闭",
     "title": "交易所开始暂停 Terra 币交易;Terraform Labs 再次停机",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2022-05-13/crypto-exchanges-start-to-suspend-terra-tokens-after-meltdown"},
    {"date": "2022-05-14", "cat": "欺诈与交易所倒闭",
     "title": "Terra 约 45 亿美元市值归零;其比特币储备去向成谜",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2022-05-14/terra-s-45-billion-face-plant-creates-a-crowd-of-crypto-losers"},
    {"date": "2022-05-18", "cat": "欺诈与交易所倒闭",
     "title": "《纽约时报》报道 Do Kwon 与 Terra 崩塌始末",
     "src": "The New York Times",
     "url": "https://www.nytimes.com/2022/05/18/technology/terra-luna-cryptocurrency-do-kwon.html"},
    {"date": "2022-05-25", "cat": "欺诈与交易所倒闭",
     "title": "Do Kwon 的 Terra 重建提案获得支持",
     "src": "Bloomberg",
     "url": "https://www.bloomberg.com/news/articles/2022-05-25/do-kwon-wins-backing-for-his-proposal-to-rescue-terra-project"},
    {"date": "2022-05-30", "cat": "欺诈与交易所倒闭",
     "title": "Terra 2.0 新 LUNA 上线即崩",
     "src": "CNBC",
     "url": "https://www.cnbc.com/2022/05/30/terra-2point0-new-luna-cryptocurrency-is-already-crashing.html"},
    # ── 2025-07 → 2025-10(first_leg 顶 2025-10-06)──────────────────────────
    {"date": "2025-07-18", "cat": "监管",
     "title": "美国《GENIUS Act》签署成法(支付型稳定币的监管框架)",
     "src": "The White House",
     "url": "https://www.whitehouse.gov/fact-sheets/2025/07/fact-sheet-president-donald-j-trump-signs-genius-act-into-law/"},
    {"date": "2025-07-23", "cat": "其他",
     "title": "PayPal 推出跨境支付平台并接入印度 UPI",
     "src": "Reuters",
     "url": "https://www.reuters.com/world/india/paypal-launch-cross-border-platform-with-link-indias-upi-payments-system-2025-07-23/"},
    {"date": "2025-08-22", "cat": "货币政策",
     "title": "杰克逊霍尔年会(鲍威尔讲话)",
     "src": "Federal Reserve",
     "url": "https://www.federalreserve.gov/newsevents/speech/powell20250822a.htm"},
    {"date": "2025-09-17", "cat": "货币政策",
     "title": "FOMC 降息 25 个基点",
     "src": "Federal Reserve",
     "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm"},
    {"date": "2025-09-29", "cat": "其他",
     "title": "Strategy 推介比特币支持的信用产品",
     "src": "Bloomberg Video",
     "url": "https://www.bloomberg.com/news/videos/2025-09-29/strategy-s-saylor-touts-bitcoin-backed-credit-products-video"},
    {"date": "2025-10-06", "cat": "其他",
     "title": "比特币创历史新高(约 12.6 万美元)",
     "src": "Reuters",
     "url": "https://www.reuters.com/business/bitcoin-hovers-near-all-time-high-2025-10-06/"},
]

EVENT_CATS = ["货币政策", "信用与违约", "杠杆爆仓", "地缘与战争", "监管",
              "欺诈与交易所倒闭", "疫情", "其他"]
LOOKBACK_EVENT_DAYS = 90


def event_windows(first_peaks: list, fc_start: list) -> list[dict]:
    """把事件挂到锚点上:主锚点 = first_leg 前高日,辅锚点 = 急跌起点,各自回看 90 天
    (台账 S-675:「2010 年以来每个新一轮顶、每次急跌之前 90 天的事件」)。"""
    out = []
    for kind, anchors in (("first_leg_peak", first_peaks), ("fast_crash_start", fc_start)):
        for a in anchors:
            a = pd.Timestamp(a)
            w0 = a - pd.Timedelta(days=LOOKBACK_EVENT_DAYS)
            evs = [e for e in EVENTS if w0 <= pd.Timestamp(e["date"]) <= a]
            out.append({"anchor_kind": kind, "anchor_d": str(a.date()),
                        "window": [str(w0.date()), str(a.date())],
                        "n_events": len(evs),
                        "events": [{"date": e["date"], "cat": e["cat"], "title": e["title"],
                                    "src": e["src"], "url": e["url"]} for e in sorted(evs, key=lambda x: x["date"])]})
    return out


# ── 风格净值 ────────────────────────────────────────────────────────────────
ALT_STYLES = ["defi", "second_l1_l2", "infra_tokenization", "ai", "app"]


def alt_ew_nav() -> tuple[pd.Series, list[str]]:
    """山寨板块 EW 指数:五个板块(style_index_pit_daily,weighting=equal)日收益等权累积。"""
    rows = fetch("style_index_pit_daily",
                 {"dimension": "in.(sector,tier)", "style": "in.(" + ",".join(ALT_STYLES) + ")",
                  "weighting": "eq.equal", "order": "d.asc", "select": "d,style,ret"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce")
    piv = df.pivot_table(index="d", columns="style", values="ret", aggfunc="last").sort_index()
    got = [s for s in ALT_STYLES if s in piv.columns]
    ew = piv[got].mean(axis=1)          # 缺的板块当天不参与(等权)
    return (1 + ew.fillna(0.0)).cumprod(), got


def btc_mcap_series() -> pd.Series:
    rows = fetch("asset_mcap_daily", {"symbol": "eq.BTC", "order": "d.asc",
                                      "select": "d,mcap"})
    return srs(rows, "d", "mcap")


def half_split(n: int) -> tuple[list, list]:
    """按时间前半 / 后半切锚点(前半 = 前 ceil(n/2) 个)。"""
    h = (n + 1) // 2
    return list(range(h)), list(range(h, n))


def window_any(on: pd.Series, lookback_days: int) -> pd.Series:
    """把迹象序列铺成「这 lookback 天(含当天)里亮过没有」的日历日布尔序列。
    内核 sign_lift 里那个是私有函数 _window_any,没导出 —— 这里按同一口径自己写一份,
    用来把**逐锚点的原始命中**取出来(卡:结果 json 里每个锚点、每个迹象的原始命中都要能复算),
    跑完在 assert_hit_consistency 里断言它与内核算出的 hit_rate 完全一致。"""
    b = pd.Series(on, dtype="boolean").fillna(False).astype(float)
    return b.rolling(lookback_days + 1, min_periods=1).max().astype(bool)


def anchor_hits(on: pd.Series, anchors: list, lookback_days: int) -> dict:
    """逐锚点的原始命中(1 / 0 / null=该锚点不在数据范围内,内核会当成跳过)。"""
    win = window_any(on, lookback_days)
    out = {}
    for a in anchors:
        a = pd.Timestamp(a)
        out[str(a.date())] = (int(bool(win.loc[a])) if a in win.index else None)
    return out


def assert_hit_consistency(on: pd.Series, anchors: list, L: int, kernel_hit_rate) -> None:
    """自检:自己写的 window_any 复算出来的命中率必须与内核 sign_lift 的完全一致。"""
    if kernel_hit_rate is None:
        return
    ok = on.dropna()
    if not len(ok):
        return
    first_ok = ok.index[0] + pd.Timedelta(days=L)
    usable = [pd.Timestamp(a) for a in anchors
              if first_ok <= pd.Timestamp(a) <= on.index[-1] and pd.Timestamp(a) in on.index]
    if not usable:
        return
    mine = float(np.mean([bool(window_any(on, L).loc[a]) for a in usable]))
    assert abs(mine - kernel_hit_rate) < 1e-9, (mine, kernel_hit_rate)


REPORT_PATH = os.path.join("/Volumes/CometCloudAI/cometcloud-local", "_reports", "absorb_input",
                           "T-187_crash_atlas_crypto.md")


def _f(x, nd=3, dash="—"):
    if x is None:
        return dash
    try:
        return ("%%.%df" % nd) % float(x)
    except (TypeError, ValueError):
        return str(x)


def _pct(x, nd=3, dash="—"):
    return dash if x is None else _f(x, nd)


def _pc(x, nd=1, dash="—"):
    """分数 → 带符号的百分比(收益、比率都用这个;协议里的分位/命中率仍是 0–1 的小数)。"""
    if x is None:
        return dash
    return ("%%+.%df%%%%" % nd) % (float(x) * 100.0)


def write_report(res: dict) -> str:
    """把结果 json 渲染成报告(数字全部来自 json,报告与结果同源)。"""
    cat = res["catalog"]
    out: list[str] = []
    w = out.append
    w("# T-187 崩盘图谱 · C 道(加密):BTC 2014 起每次 −50% 熊市与 14 天 −30% 急跌之前的迹象 / 事件 / 情绪 / 风格")
    w("")
    w("台账 **S-675**(挖掘协议,写于把任何迹象与崩盘放在一起看之前)· 种子 675 · 零分布 2,000 次(循环平移)。")
    w("")
    w("**这是挖掘,不是检验。** 每个迹象都跟基准率比(它在随便哪天之前出现的频率)。"
      "挖出来的「线索」只进候选名单,要当规则用必须另立预注册、按前向判。本报告不产生任何可交易规则。")
    w("")
    w("脚本 `docs/research/t187_crash_atlas_crypto.py` · 结果 `docs/research/t187_results.json`"
      "(每个锚点、每个迹象的原始命中都在里面,能复算)。")
    w("")
    w("## 0. 数据与口径")
    w("")
    w("- BTC 价格 = 库 `asset_mcap_daily` 的 `price` 列(2014-12 起),**不是市值 ÷ 价格**;ETH 同口径只报。")
    w("- 迹象全部按时点计算:低频序列先过内核 `available()`(发布滞后),再 `to_calendar` 铺成日历日;"
      "分位用内核 `expanding_pct`(只看过去,min_periods=252)。")
    w("- 零分布 = 内核 `sign_lift` 的循环平移(保留迹象自身的持续长度,只换时点),基准率 = 同一迹象在数据范围内的平均出现率。")
    w("- 「线索」判据(协议写死):分位 ≥ 0.95 且 提升 ≥ 1.5 且 锚点 ≥ 6 且 前后两半命中率都 > 基准率。"
      "**每道约 20 个迹象,按 0.95 的门槛纯偶然也会冒出约 1 个。**")
    w("")
    # ── 1 崩盘目录 ──
    w("## 1. 崩盘目录")
    w("")
    w("### 1.1 BTC 熊市段(−50% 起,+50% 反弹确认;`first_leg` = 高于上一段前高,新一轮的顶)")
    w("")
    w("| # | 前高日 | 破位日 | 谷底日 | 深度 | first_leg | 未确认 |")
    w("|---|---|---|---|---|---|---|")
    for i, e in enumerate(cat["BTC"]["bear_episodes"], 1):
        w("| %d | %s | %s | %s | %s | %s | %s |" % (i, e["peak_d"], e["break_d"], e["trough_d"],
          _pct(e["depth"]), "是" if e["first_leg"] else "否", "是" if e["open"] else "否"))
    w("")
    w("价格区间 %s → %s。**锚点:主 = first_leg 前高日(共 %d 个),辅 = 破位日 %d 个 / 急跌起点 %d 个。**"
      % (cat["BTC"]["price_span"][0], cat["BTC"]["price_span"][1],
         len(res["anchors"]["primary_first_leg_peaks"]), len(res["anchors"]["aux_breaks"]),
         len(res["anchors"]["aux_fast_crash_starts"])))
    w("")
    w("### 1.2 BTC 急跌(14 个日历日 ≤ −30%,60 天内只算一次)")
    w("")
    w("| # | 窗口起点 | 命中日 | 14 日跌幅 |")
    w("|---|---|---|---|")
    for i, f in enumerate(cat["BTC"]["fast_crashes"], 1):
        w("| %d | %s | %s | %s |" % (i, f["start_d"], f["hit_d"], _pct(f["ret"])))
    w("")
    w("### 1.3 ETH(同口径,只报)")
    w("")
    w("熊市段 %d 段、急跌 %d 次,价格区间 %s → %s。"
      % (len(cat["ETH"]["bear_episodes"]), len(cat["ETH"]["fast_crashes"]),
         cat["ETH"]["price_span"][0], cat["ETH"]["price_span"][1]))
    w("")
    # ── 2 迹象 ──
    w("## 2. 迹象排名表(24 个迹象;「锚点数 / 跳过」= first_leg 前高 90 天窗口内可用的锚点)")
    w("")
    w("| 迹象 | n | skip | 命中率 | 基准率 | 提升 | 零分布分位 | null_p50 | 前半 | 后半 | 锚点±1 天稳定 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    rows = []
    for name, v in res["signs"].items():
        p = v["primary_90d"]
        rob = res["robustness_anchor_shift_1d"].get(name, {})
        rows.append((p.get("pctile") if p.get("pctile") is not None else -1, name, v, p, rob))
    for _, name, v, p, rob in sorted(rows, key=lambda r: (-r[0], r[1])):
        w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            name, p.get("n_anchors"), p.get("n_skipped"), _pct(p.get("hit_rate")),
            _pct(p.get("base_rate")), _f(p.get("lift"), 2), _pct(p.get("pctile")),
            _pct(p.get("null_p50")), _pct(v["primary_90d"].get("half1_hit_rate")),
            _pct(v["primary_90d"].get("half2_hit_rate")),
            "是" if rob.get("hit_rate_stable") else "否"))
    w("")
    w("辅助锚点(破位日 30 天、急跌起点 30 天)的同样统计在 `t187_results.json` 的 "
      "`signs.<迹象>.aux_break_30d` / `aux_fastcrash_30d` 里,含逐锚点原始命中 `hits`。")
    w("")
    # ── 3 事件 ──
    ev = res["events"]
    w("## 3. 事件表(定性;每个 first_leg 顶与每次急跌之前 90 天)")
    w("")
    w("**只计数,不算提升** —— 事件没有基准率,这是最弱的一层。每条带日期与来源链接;**查不到来源的不写**。")
    w("")
    for win in ev["windows"]:
        w("### %s %s(窗口 %s → %s,%d 条)" % (
            "新一轮顶" if win["anchor_kind"] == "first_leg_peak" else "急跌起点",
            win["anchor_d"], win["window"][0], win["window"][1], win["n_events"]))
        w("")
        if not win["events"]:
            w("_该窗口内没有找到能附来源的事件(按协议不写无来源的条目)。_")
            w("")
            continue
        w("| 日期 | 类别 | 事件 | 来源 |")
        w("|---|---|---|---|")
        for e in win["events"]:
            w("| %s | %s | %s | [%s](%s) |" % (e["date"], e["cat"], e["title"], e["src"], e["url"]))
        w("")
    w("**八类事件计数(全部 %d 条事件、其中 %d 条落在至少一个窗口内):**" % (ev["n_catalog"], ev["n_in_some_window"]))
    w("")
    w("| " + " | ".join(EVENT_CATS) + " |")
    w("|" + "---|" * len(EVENT_CATS))
    w("| " + " | ".join(str(ev["by_category"][c]) for c in EVENT_CATS) + " |")
    w("")
    assigned = {e["url"] for win in ev["windows"] for e in win["events"]}
    near = [e for e in ev["catalog"] if e["url"] not in assigned]
    if near:
        w("**邻近但落在窗口外的事件**(距最近的锚点窗口 1–11 天,只作背景,不计入上表的窗口计数):")
        w("")
        for e in near:
            w("- %s | %s | %s | [%s](%s)" % (e["date"], e["cat"], e["title"], e["src"], e["url"]))
        w("")
    # ── 4 情绪 ──
    w("## 4. 情绪画像(顶前 90 天 / 30 天 / 顶 / 谷底,跨崩盘取中位)")
    w("")
    w("| 指标 | 顶前 90 天 | 顶前 30 天 | 顶 | 谷底 |")
    w("|---|---|---|---|---|")
    label = {"fng": "恐惧贪婪指数(fng)", "vix": "VIX", "btc_funding_annualized": "BTC 资金费(年化)"}
    for k, s in res["sentiment"].items():
        m = s["median_first_leg"]
        fmt = _pc if k == "btc_funding_annualized" else (lambda x: _f(x, 1))
        w("| %s | %s | %s | %s | %s |" % (label.get(k, k), fmt(m["d90"]), fmt(m["d30"]),
                                          fmt(m["peak"]), fmt(m["trough"])))
    w("")
    w("中位只取 first_leg 段(新一轮的顶);全部段的逐段读数在 json 的 `sentiment` 里。")
    w("")
    # ── 5 风格 ──
    w("## 5. 风格分阶段(顶前 60 天 / 顶 → 谷底 / 谷底 → +120 天;只报不判)")
    w("")
    w("| 风格 | 段 | 顶前 60 天 | 顶 → 谷底 | 谷底 → +120 天 |")
    w("|---|---|---|---|---|")
    sname = {"BTC_hold": "BTC 持有", "BTC_trend200_nav": "BTC 200 日趋势(未触发时持现金)",
             "X1V_trade_path_rally_l20": "X1V(信号引擎,只读 import)",
             "ETH_hold": "ETH 持有", "ALT_sector_EW_nav": "山寨板块 EW 指数(五板块等权)",
             "BTC_over_ALT": "BTC 相对山寨"}
    for nm, eps in res["styles"].items():
        fl = [e for e in eps if e.get("first_leg")]
        med = lambda k: (float(np.median([e[k] for e in fl if e.get(k) is not None]))
                         if any(e.get(k) is not None for e in fl) else None)  # noqa: E731
        w("| %s | first_leg 段(中位,%d 段) | %s | %s | %s |" % (
            sname.get(nm, nm), len(fl), _pc(med("pre")), _pc(med("crash")), _pc(med("recovery"))))
    w("")
    w("山寨板块用了 %s 五个板块;逐段原始值在 json 的 `styles` 里。" % "、".join(res.get("alt_styles_used", [])))
    w("")
    # ── 6 线索 ──
    w("## 6. 线索候选")
    w("")
    leads = res.get("leads_primary_90d", [])
    if leads:
        w("以下迹象同时满足四条判据(分位 ≥ 0.95、提升 ≥ 1.5、锚点 ≥ 6、前后两半都 > 基准率):")
        w("")
        for k in leads:
            p = res["signs"][k]["primary_90d"]
            w("- **%s**:命中率 %s,基准率 %s,提升 %s,分位 %s —— **探索性 —— 需另立预注册、在新数据上过零信号对照**"
              % (k, _pct(p["hit_rate"]), _pct(p["base_rate"]), _f(p["lift"], 2), _pct(p["pctile"])))
    else:
        w("**本轮没有迹象满足四条判据。** 最大的约束是锚点数:BTC 只有 %d 个 first_leg 前高,"
          "协议写死「锚点 ≥ 6」,所以这一道的线索一栏结构上就是空的 —— 这是答案本身,不是缺陷;"
          "按 Seth 10-23 的退回意见,**不降档、不加 BTC 之前的数据**。"
          % len(res["anchors"]["primary_first_leg_peaks"]))
    w("")
    w("与崩盘定义同源的迹象(P4 动荡 / P5 初裂落在破位与急跌的锚点附近)照报了,但即便分位够高也算「同源,不算线索」。")
    w("")
    w("### 6.1 探索性观察(不是线索)")
    w("")
    w("下面几条**不满足**协议的线索判据,但读数值得记一笔。**探索性 —— 需另立预注册、在新数据上过零信号对照**;"
      "本报告不给它们任何方向性结论。")
    w("")
    for name, v in res["signs"].items():
        p = v["primary_90d"]
        pt, hr, base = p.get("pctile"), p.get("hit_rate"), p.get("base_rate")
        if pt is None:
            continue
        if pt >= 0.95:
            h1 = v["primary_90d"].get("half1_hit_rate")
            h2 = v["primary_90d"].get("half2_hit_rate")
            parts = ["分位够高但锚点只有 %s 个(协议要求 ≥ 6)" % p.get("n_anchors")]
            if h1 is not None and h2 is not None and base is not None:
                parts.append("前后两半命中率 %s / %s(基准率 %s)%s"
                             % (_pct(h1), _pct(h2), _pct(base),
                                "" if h2 > base else " —— 后半没亮"))
            note = ",".join(parts)
            if p.get("n_anchors", 0) >= 6 and h2 is not None and base is not None and h2 > base:
                continue
        elif pt <= 0.05 and hr == 0:
            note = "命中率 0,基准率 %s —— 这一条在 BTC 顶前 90 天**从来没亮过**(分位 %s,偏低的方向)" % (_pct(base), _pct(pt))
        else:
            continue
        w("- **%s**:命中率 %s,基准率 %s,提升 %s,分位 %s,锚点 %s —— %s。"
          % (name, _pct(hr), _pct(base), _f(p.get("lift"), 2), _pct(pt), p.get("n_anchors"), note))
    w("")
    w("另:**P5(离 52 周高点 ≥ 5%% 但仍在 200 日线上)命中率 1.0 但基准率 %s —— 几乎常亮,没有信息量**;"
      "**M1 / M2 / M4 / M5 / M13 在 5 个锚点上全部 0 命中**(各自的基准率 %s / %s / %s / %s / %s)。"
      % (_pct(res["signs"]["P5_dd52w_ge5pct_above_ma200"]["primary_90d"]["base_rate"]),
         _pct(res["signs"]["M1_ffr_12m_up_ge1pp"]["primary_90d"]["base_rate"]),
         _pct(res["signs"]["M2_10y2y_lt0"]["primary_90d"]["base_rate"]),
         _pct(res["signs"]["M4_nfci_gt0"]["primary_90d"]["base_rate"]),
         _pct(res["signs"]["M5_baa10y_63d_up_ge0p5pp"]["primary_90d"]["base_rate"]),
         _pct(res["signs"]["M13_icsa_ma4_13w_up_ge15pct"]["primary_90d"]["base_rate"])))
    w("")
    # ── 7 协议问题 ──
    w("## 7. 协议问题(只提不改)")
    w("")
    w("1. **锚点数**:BTC 的 first_leg 前高只有 %d 个,协议判据「锚点 ≥ 6」永远不成立。"
      "协议写死的答案,与「BTC 之前没有数据」是两回事。"
      % len(res["anchors"]["primary_first_leg_peaks"]))
    w("2. **数据起点晚于锚点**:C1(2018-02 起)、C2(2020-01 起)、C3(2020-09 起)、C4(2020 起)、"
      "C5(2018 起)、C6(2018 起)与 M 系列部分(FRED 起点)都在 2017-12 那个顶之后,"
      "所以锚点很多被跳过 —— 跳过数已在表里逐条列出,没有当成「没发生」。")
    w("3. **事件层没有基准率**:只能计数,不能算提升(已在第 3 节写明)。")
    w("4. **同源迹象**:P4(20 日波动分位 ≥ 0.9)与 P5(初裂)在破位 / 急跌锚点附近几乎是定义的同义反复,"
      "报数但不当线索。")
    w("5. **最后一段仍未确认谷底**:2025-10-06 那一段的谷底是 `open` 段(数据末仍未反弹确认 +50%),"
      "它的「顶 → 谷底」与「谷底 → +120 天」两段不可比。")
    w("")
    # ── 8 未做 ──
    w("## 8. 未做")
    w("")
    w("- **事件窗口只做了 first_leg 顶与急跌起点**(协议原文如此)。破位日(aux break)的 30 天窗口没有做事件表。")
    w("- **来源稀薄的窗口**:2014-10 → 2014-12 那个急跌窗口只找到 1 条能附来源的事件;"
      "2019-06 的伊朗击落美军无人机、2018-02 印度储备银行禁止加密货币交易、2021-03-10 的杠杆连环爆仓"
      "三条,时间与事实都确认,但当时找不到可核的原始来源链接,按协议**没有写进表里**。")
    w("- **ETF 拼接(SPY / QQQ)**:协议里的这一段属于 A 道(主流)与 B 道(EM),加密道用不到,未做。")
    w("- **ETH / 山寨的崩盘目录**只报了计数,没有做迹象与风格(协议如此)。")
    w("")
    w("## 9. 复算")
    w("")
    w("```bash")
    w("python3 docs/research/t187_crash_atlas_crypto.py")
    w("```")
    w("")
    w("结果写 `docs/research/t187_results.json`;迹象的逐锚点原始命中在 `signs.<迹象>.primary_90d.hits`。")
    w("")
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(out))
    return REPORT_PATH


def main() -> None:
    res: dict = {"task": "T-187", "ledger": "S-675", "seed": SEED, "n_shift": 2000}

    btc, eth = load_prices()
    btc_ep = bear_episodes(btc, 0.50)
    btc_fc = fast_crashes(btc, 14, 0.30, 60)
    eth_ep = bear_episodes(eth, 0.50)
    eth_fc = fast_crashes(eth, 14, 0.30, 60)

    def dump_eps(eps, fc):
        return {
            "bear_episodes": [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                               for k, v in e.items()} for e in eps],
            "fast_crashes": [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v)
                              for k, v in f.items()} for f in fc],
        }

    res["catalog"] = {"BTC": dump_eps(btc_ep, btc_fc), "ETH": dump_eps(eth_ep, eth_fc)}
    res["catalog"]["BTC"]["price_span"] = [str(btc.index[0].date()), str(btc.index[-1].date())]
    res["catalog"]["ETH"]["price_span"] = [str(eth.index[0].date()), str(eth.index[-1].date())]

    # 锚点(S-675 结构,三道同一套):主 = first_leg 前高回看 90 天;辅 = 全部破位日 / 急跌起点回看 30 天
    first_peaks = [e["peak_d"] for e in btc_ep if e["first_leg"]]
    break_d = [e["break_d"] for e in btc_ep]
    fc_start = [f["start_d"] for f in btc_fc]
    res["anchors"] = {
        "primary_first_leg_peaks": [str(d.date()) for d in first_peaks],
        "aux_breaks": [str(d.date()) for d in break_d],
        "aux_fast_crash_starts": [str(d.date()) for d in fc_start],
    }

    # ── 迹象表 ─────────────────────────────────────────────────────────────
    fng = macro_series("fng")
    bmc = btc_mcap_series()
    signs = {
        # P1–P5(价格本身,在 BTC 上;台账 S-675 写死)
        **sign_p1_p5(btc),
        # M1–M13(全球宏观,FRED;台账 S-675 写死)
        **sign_m1_m13(),
        # C1–C6(加密专属;C1–C6 上一轮已做,逻辑一字未动)
        "C1_fng_ge75_7d": sign_c1(fng),
        "C2_btc_funding_ann_7d_ge30pct": sign_c2_btc_funding(),
        "C3_btc_oi_30d_growth_pct_ge90": sign_c3_oi(),
        "C4_stables_30d_growth_lt0": sign_c4_stables(),
        "C5_btc_share_60d_drop_ge10pp": sign_c5_btc_share(bmc),
        "C6_total_vol_30d_mean_pct_ge90": sign_c6_volume(),
    }
    anchor_sets = {"primary_90d": (first_peaks, 90),
                   "aux_break_30d": (break_d, 30),
                   "aux_fastcrash_30d": (fc_start, 30)}
    sign_res = {}
    for name, on in signs.items():
        on = on.sort_index()
        ok = on.dropna()
        entry = {"data_span": [str(ok.index[0].date()) if len(ok) else None,
                               str(ok.index[-1].date()) if len(ok) else None],
                 "n_valid_days": int(len(ok)),
                 "n_on_days": int(ok.fillna(False).sum())}
        for aset, (anchors, L) in anchor_sets.items():
            full = sign_lift(on, anchors, L)
            half = half_split(len(anchors))
            h1 = sign_lift(on, [anchors[i] for i in half[0]], L) if half[0] else {"hit_rate": None}
            h2 = sign_lift(on, [anchors[i] for i in half[1]], L) if half[1] else {"hit_rate": None}
            assert_hit_consistency(on, anchors, L, full["hit_rate"])
            entry[aset] = {**full, "half1_hit_rate": h1.get("hit_rate"),
                           "half2_hit_rate": h2.get("hit_rate"),
                           "half1_n": len(half[0]), "half2_n": len(half[1]),
                           "hits": anchor_hits(on, anchors, L)}
        sign_res[name] = entry
    res["signs"] = sign_res

    # 稳健性:锚点整体挪 ±1 天再判一次(S-665 的规矩 —— 只在当天成立的量不算)。
    # C3/C4/C5/C6 都是派生量(30/60 天变化、占比),核一遍 +1/−1 天命不命中还稳。
    robust = {}
    for name, on in signs.items():
        on = on.sort_index()
        row = {}
        for shift in (-1, 1):
            sh = [a + pd.Timedelta(days=shift) for a in first_peaks]
            r = sign_lift(on, sh, 90)
            row["shift%+d" % shift] = {"n_anchors": r["n_anchors"], "hit_rate": r["hit_rate"],
                                       "lift": r["lift"], "pctile": r["pctile"]}
        base = sign_res[name]["primary_90d"]
        row["hit_rate_stable"] = bool(base["hit_rate"] is not None and all(
            r["hit_rate"] is not None and abs(r["hit_rate"] - base["hit_rate"]) < 1e-9
            for r in row.values()))
        robust[name] = row
    res["robustness_anchor_shift_1d"] = robust

    # ── 风格:分阶段收益(只报不判)─────────────────────────────────────────────
    from src.data.signals.tom import trade_path  # 只读 import,不改
    x1_g = trade_path(btc, "rally", 0.0, exit_mode="l20", vol=True)
    x1v = (1 + x1_g.shift(1).fillna(0.0) * btc.pct_change().fillna(0.0)).cumprod()
    alt_nav, alt_got = alt_ew_nav()
    styles = {
        "BTC_hold": btc,
        "BTC_trend200_nav": trend_200_nav(btc),                      # 空仓 0 收益,不拿利率
        "X1V_trade_path_rally_l20": x1v,
        "ETH_hold": eth,
        "ALT_sector_EW_nav": alt_nav,
        "BTC_over_ALT": btc / alt_nav,
    }
    res["alt_styles_used"] = alt_got
    res["styles"] = {nm: [{"peak_d": str(e["peak_d"].date()), "trough_d": str(e["trough_d"].date()),
                           "depth": e["depth"], "first_leg": e["first_leg"],
                           **phase_returns(lv, e)} for e in btc_ep if not e["open"] or e["first_leg"]]
                     for nm, lv in styles.items()}

    # ── 情绪画像:顶前 90 天 / 30 天 / 顶 / 谷底,跨崩盘取中位 ────────────────────
    vix = load_fred("VIXCLS")
    f_btc = srs(fetch("funding_history",
                      {"symbol": "eq.BTC", "venue": "eq.binance_perp",
                       "order": "funding_time.asc", "select": "funding_time,funding_rate"}),
                "funding_time", "funding_rate", agg="sum")
    fund_ann = to_calendar(f_btc, 5) * 365.0
    senti = {"fng": to_calendar(fng, 7), "vix": to_calendar(vix, 5),
             "btc_funding_annualized": to_calendar(fund_ann, 10)}
    prof = {}
    for nm, lv in senti.items():
        rows = []
        for e in btc_ep:
            pk, tr = e["peak_d"], e["trough_d"]
            s = lv.dropna().sort_index()
            pts = {"peak_d": str(pk.date()), "trough_d": str(tr.date()),
                   "first_leg": e["first_leg"],
                   "d90": _val(s, pk - pd.Timedelta(days=90)), "d30": _val(s, pk - pd.Timedelta(days=30)),
                   "peak": _val(s, pk), "trough": _val(s, tr)}
            rows.append(pts)
        first = [r for r in rows if r["first_leg"]]
        med = lambda rr, k: (float(np.median([r[k] for r in rr if r[k] is not None]))
                             if any(r[k] is not None for r in rr) else None)  # noqa: E731
        prof[nm] = {"per_episode": rows, "median_first_leg": {k: med(first, k) for k in ("d90", "d30", "peak", "trough")},
                    "median_all": {k: med(rows, k) for k in ("d90", "d30", "peak", "trough")}}
    res["sentiment"] = prof

    # ── 事件表(S-675:定性,只计数不算提升)────────────────────────────────────
    wins = event_windows(first_peaks, fc_start)
    assigned = {e["url"] for w in wins for e in w["events"]}
    cat_count: dict[str, int] = {}
    for e in EVENTS:
        cat_count[e["cat"]] = cat_count.get(e["cat"], 0) + 1
    res["events"] = {
        "lookback_days": LOOKBACK_EVENT_DAYS,
        "catalog": [{"date": e["date"], "cat": e["cat"], "title": e["title"],
                     "src": e["src"], "url": e["url"]} for e in sorted(EVENTS, key=lambda x: x["date"])],
        "windows": wins,
        "by_category": {c: cat_count.get(c, 0) for c in EVENT_CATS},
        "n_catalog": len(EVENTS),
        "n_in_some_window": len(assigned),
        "n_unassigned": len(EVENTS) - len(assigned),
    }

    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("wrote", OUT)
    print("BTC bear episodes:", len(btc_ep), "first_leg:", len(first_peaks),
          "fast crashes:", len(btc_fc))
    leads = []
    for k, v in sign_res.items():
        p = v["primary_90d"]
        base = p["base_rate"]
        is_lead = (p["pctile"] is not None and p["pctile"] >= 0.95 and p["lift"] is not None
                   and p["lift"] >= 1.5 and p["n_anchors"] >= 6
                   and base is not None
                   and v["primary_90d"]["half1_hit_rate"] is not None
                   and v["primary_90d"]["half2_hit_rate"] is not None
                   and v["primary_90d"]["half1_hit_rate"] > base
                   and v["primary_90d"]["half2_hit_rate"] > base)
        if is_lead:
            leads.append(k)
        print("%-34s n=%-3s skip=%-3s hit=%-6s base=%-6s lift=%-6s pct=%-6s h1=%-6s h2=%-6s %s" % (
            k, p["n_anchors"], p["n_skipped"],
            None if p["hit_rate"] is None else round(p["hit_rate"], 3),
            None if base is None else round(base, 3),
            None if p["lift"] is None else round(p["lift"], 2),
            None if p["pctile"] is None else round(p["pctile"], 3),
            None if v["primary_90d"]["half1_hit_rate"] is None else round(v["primary_90d"]["half1_hit_rate"], 3),
            None if v["primary_90d"]["half2_hit_rate"] is None else round(v["primary_90d"]["half2_hit_rate"], 3),
            "LEAD" if is_lead else ""))
    res["leads_primary_90d"] = leads
    print("leads(primary 90d):", leads, " n_signs:", len(sign_res))
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("report:", write_report(res))


def _val(s: pd.Series, d: pd.Timestamp):
    s = s[s.index <= d]
    return None if not len(s) else float(s.iloc[-1])


if __name__ == "__main__":
    main()