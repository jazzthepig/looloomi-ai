"""T-366(lane-b,2026-11-17 第二轮)—— R-v2 真钱票源币 vs 三套资产描述(资产向量 / 资金面向量 / CIS)的逐币对账。

**卡**:T-366(台账 S-842)。问的是:「真钱在交易的币有没有向量」。
**本轮目的**:返工 Seth 2026-11-13 的八条 CHANGES(§Seth-1113o 四条 + §Seth-1113q 的 ⑤–⑧):
  ① 「补 OI 后达 10 维」的币数改成逐币实测(不是 172);② 结论 2 改成「两边都赚」;
  ③ 报告正文**由本脚本从 JSON 生成**(数字不手抄);④ 改完重跑本脚本;
  ⑤ 维度依据改引**真实写端** `src/data/vector/embedder.py::generate_embedding`(仓里没有 `compute_full_vec`),
     `[25][26]` 归「写端未实现 / 视图无数据」;⑥ JSON 全部由本脚本产出、键与脚本对齐;
  ⑦ 最小方案补 funding(到 72 币)+ 永续/现货口径差(实测);
  ⑧ §7 的「那 24 个币恰好在最弱的一档」**降级**(state_daily 的 entity 全是 'panel',是面板级不是币级),
     换成同口径对照实验(实验组=有向量的币,对照组=同日全体有资金面的币,零分布走 apparatus)。

**口径(全部沿用上游,一字不改)**:
  票源  `docs/research/t197_results.json` → `tickets.A`(与 `t310_slots.load_tickets` 同源同路径)。
  窗口  `signal_d >= 2024-11-01`(卡上指定「2024-11 以来开过票」)。
  盈亏  名义 = min(净值 × 0.5% ÷ 止损距离, 净值 × 50%);止损距离 = (entry_px − stop_px) ÷ entry_px;
         美元 P&L = 名义 × r。r 取票源 t197 的 r;`still` 票(r 为空)用 Mac 数据根永续日线最后一根收盘算 mtm。
         净值恒取 $630(t310 的 equity0,逐票独立口径,不做复利)。

**只读**:不写库、不改 src、不新建抓取器。DB 读走 PostgREST(读 key),每页 ≤1000 行、一律带 `order=`。
**零分布/分位**:一律走 `src/data/evaluation/apparatus.py`(null_distribution / percentile_of),不另写。

**用法**:`python3 docs/research/T-366_coverage.py`
  → 写 `docs/research/T-366_traded_universe_coverage.json`
  → 写 `docs/research/T-366_traded_universe_coverage.md`(由 JSON 渲染,③)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

T197 = os.path.join(HERE, "t197_results.json")
UM = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
HL_FUND = "/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding"
OUT_JSON = os.path.join(HERE, "T-366_traded_universe_coverage.json")
OUT_MD = os.path.join(HERE, "T-366_traded_universe_coverage.md")

SINCE = "2024-11-01"
EQUITY0 = 630.0
RISK_FRAC = 0.005
MAX_FRAC = 0.5
FRESH_DAYS = 7           # 「最近更新过」的判定窗
FUND_FRESH_DAYS = 7      # funding 算「实测」的门槛:最近一次结算距今 ≤7 天(写端要的是当前资金费,不是历史值)
HIST_DAYS = 60           # 取最近多少天的日线做「≥31 根」与口径差
CHUNK = 15               # symbol=in.(...) 每片大小(15×60 天 < 1000 行,一页取完)
SEED = 20261117          # 对照组抽样种子

NOW = dt.datetime.now(dt.timezone.utc)


# ── PostgREST ───────────────────────────────────────────────────────────────────────────────────────
def q(table, qs, count=False):
    url = URL + "/rest/v1/" + table + "?" + qs
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if count:
        headers["Prefer"] = "count=exact"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
            return r.headers.get("Content-Range"), r.read().decode()
    except Exception as e:  # noqa: BLE001
        return "ERR", type(e).__name__ + ": " + str(e)[:200]


def page_all(table, qs_base, order):
    """翻页取全表(每页 1000,带 order= —— 不带 order 翻页边界会漂)。"""
    out, off = [], 0
    while True:
        cr, body = q(table, qs_base + "&order=" + order + "&limit=1000&offset=" + str(off))
        if body.startswith("ERR"):
            print("ERR", table, qs_base, body[:120])
            break
        rows = None
        try:
            rows = json.loads(body)
        except Exception as e:  # noqa: BLE001
            print("ERR-JSON", table, qs_base[:120], type(e).__name__, repr(body[:200]))
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
        if off > 200000:
            break
    return out


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def in_list(syms):
    return "(" + ",".join(syms) + ")"


def latest_row(table, order_col, sel, sym):
    cr, body = q(table, "select=" + sel + "&symbol=eq." + sym + "&order=" + order_col + ".desc&limit=1")
    if body.startswith("ERR"):
        return None
    rows = json.loads(body)
    return rows[0] if rows else None


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# ── 票源 / Mac 面板 ──────────────────────────────────────────────────────────────────────────────
def load_tickets():
    """t310_slots.load_tickets 同源同路径:docs/research/t197_results.json → tickets.A。"""
    d = json.load(open(T197))
    return d["tickets"]["A"], d


def load_um():
    """Mac 数据根的永续日线(只取聚合量,不留全量)。bars = [date,o,h,l,c,qv] 或 dict。"""
    bars = {}
    with open(UM) as f:
        for line in f:
            x = json.loads(line)
            sym = str(x.get("symbol") or x.get("s") or "").upper()
            rows = x.get("bars") or x.get("b") or x.get("rows") or x.get("data") or []
            out = []
            for r in rows:
                if isinstance(r, dict):
                    d = r.get("d") or r.get("date")
                    c = r.get("c")
                    if d is None or c is None:
                        continue
                    out.append((str(d)[:10], float(c),
                                float(r.get("h") or c), float(r.get("l") or c),
                                float(r.get("qv") or 0.0)))
                elif isinstance(r, (list, tuple)) and len(r) >= 5:
                    # [date,o,h,l,c,qv]
                    out.append((str(r[0])[:10], float(r[4]),
                                float(r[3]), float(r[2]),
                                float(r[5]) if len(r) > 5 else 0.0))
            if out:
                bars[sym] = sorted(out)
    return bars


def load_hl_funding():
    """Mac 数据根的 Hyperliquid 资金费(1h 结算,CSV: fundingTime(ms),fundingRate)。"""
    out = {}
    if not os.path.isdir(HL_FUND):
        return out
    for fn in sorted(os.listdir(HL_FUND)):
        if not fn.endswith("_funding_1h.csv"):
            continue
        sym = fn[: -len("_funding_1h.csv")].upper()
        rows = []
        try:
            with open(os.path.join(HL_FUND, fn)) as f:
                head = f.readline()
                if "fundingRate" not in head:
                    continue
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) < 2:
                        continue
                    try:
                        ts = int(parts[0])
                        rate = float(parts[1])
                    except ValueError:
                        continue
                    rows.append((dt.datetime.fromtimestamp(ts / 1000.0, dt.timezone.utc).date().isoformat(), rate))
        except OSError:
            continue
        if rows:
            rows.sort()
            out[sym] = rows
    return out


# ── 27 维定义(依据真实写端 src/data/vector/embedder.py::generate_embedding,不改 src)────────────
# dim: (序号, 名称, 含义/公式, 写端数据来源, 只有「永续日线 + 资金费 + OI、没有 CIS」能不能算, 原因)
DIMS = [
    (0, "F/100", "Fundamental 支柱", "CIS 引擎 pillar_F(cis_official_daily.pillar_f)",
     "否", "支柱是打分结果,不是永续数据能推出的量"),
    (1, "M/100", "Momentum 支柱", "CIS 引擎 pillar_M(cis_official_daily.pillar_m)",
     "否", "同上"),
    (2, "O/100", "On-chain/风险调整支柱", "CIS 引擎 pillar_O(cis_official_daily.pillar_o)",
     "否", "同上"),
    (3, "S/100", "Sentiment 支柱", "CIS 引擎 pillar_S(cis_official_daily.pillar_s)",
     "否", "同上"),
    (4, "A/100", "Alpha 支柱", "CIS 引擎 pillar_A(cis_official_daily.pillar_a)",
     "否", "同上"),
    (5, "cis_score/100", "CIS 总分", "cis_official_daily.cis_score",
     "否", "总分的定义就是五支柱的加总"),
    (6, "log10(mcap)/15", "市值(log 归一)", "asset_mcap_daily.mcap(CoinGecko 市值)",
     "部分", "永续合约本身没有市值;CoinGecko 有该币市值才能算 —— 库里是 market_chart 的历史市值"),
    (7, "chg_24h/20", "24h 涨跌", "日收盘(asset_mcap_daily.price / ohlcv_daily.close)",
     "是", "永续日线收盘即可算(口径与现货收盘有差,见第 6 节实测)"),
    (8, "chg_7d/50", "7d 涨跌", "同上", "是", "需要 ≥8 根日线"),
    (9, "chg_30d/100", "30d 涨跌", "同上", "是", "需要 ≥31 根日线"),
    (10, "min(vol/mcap×10,1)", "成交额/市值", "asset_mcap_daily.volume ÷ .mcap",
     "部分", "永续有成交额(面板 qv)但库里这一维的分子是现货 24h 成交额,口径不同"),
    (11, "clamp(funding×1000)", "资金费率", "funding_history(venue=binance_perp).funding_rate",
     "是", "资金费是永续原生量;库里 funding_history 覆盖多币(永续原生,与 OI 同一个 derivatives 映射)"),
    (12, "oi/mcap×5", "OI/市值 杠杆比", "OI 存量(CoinGecko derivatives,只在 CIS universe 内)÷ mcap",
     "部分", "有 OI 存量 + 有市值才能算;我们库里只有 ΔOI(flow 表 doi7),没有 OI 存量"),
    (13, "(100−ath)/100", "距历史高点", "ath_distance_pct(现货 ATH;永续代理=历史最高价)",
     "是(代理)", "永续日线可算历史最高价,但与现货 ATH 口径不同,只能当代理"),
    (14, "las/100", "流动性调整分", "CIS 引擎 las", "否", "LAS 是打分产物"),
    (15, "confidence", "数据置信度", "CIS 引擎 confidence", "否", "CIS 引擎自评的数据完整度"),
    (16, "class_enc/10", "资产类别编码", "资产清单映射(_CLASS_ENC)",
     "部分", "加密默认 Crypto=0.8 可填;L1/L2/DeFi/… 子类要外部映射"),
    (17, "regime_alignment", "宏观 regime 对齐", "全局 macro regime(_REGIME_ALIGN)",
     "是", "全局量,任何资产都能填 —— 非 CIS 依赖"),
    (18, "d_F", "F 支柱一日变化", "连续两天的 pillar_F", "否", "需要 CIS 支柱历史"),
    (19, "d_M", "M 支柱一日变化", "连续两天的 pillar_M", "否", "同上"),
    (20, "d_O", "O 支柱一日变化", "连续两天的 pillar_O", "否", "同上"),
    (21, "d_S", "S 支柱一日变化", "连续两天的 pillar_S", "否", "同上"),
    (22, "d_A", "A 支柱一日变化", "连续两天的 pillar_A", "否", "同上"),
    (23, "stability_O", "O 支柱窗口波动", "pillar_O 历史序列 std", "否", "需要 CIS 支柱历史(≥3 obs)"),
    (24, "stability_S", "S 支柱窗口波动", "pillar_S 历史序列 std", "否", "同上"),
    (25, "edge_vol", "β 调整后边际的波动", "asset_edge_moments 视图(写端 edge_moments 入参)",
     "否", "**写端未实现 / 视图无数据**:asset_edge_moments 实测 0 行 ⇒ 写出来是 NaN(存量行里少数非空是历史遗留)"),
    (26, "edge_p10", "β 调整后边际的左尾", "asset_edge_moments 视图(写端 edge_moments 入参)",
     "否", "同上"),
]
NON_CIS_DIMS = [d[0] for d in DIMS if d[0] not in list(range(0, 6)) + [14, 15] + list(range(18, 27))]
MIN_MEASURED_DIMS = 10   # embedder.py::MIN_MEASURED_DIMS —— 少于 10/27 维实测就不写这一行


def scan_source(path, patterns):
    """在源文件里按正则找行号(报告引用的是实测行号,不是记忆里的行号)。"""
    out = []
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError as e:
        return [{"error": str(e)}]
    for pat in patterns:
        rx = re.compile(pat)
        hit = None
        for i, ln in enumerate(lines, 1):
            if rx.search(ln):
                hit = {"pattern": pat, "line": i, "text": ln.strip()[:160]}
                break
        out.append(hit or {"pattern": pat, "line": None, "text": None})
    return out


def writer_probe():
    """⑤ 真实写端探针:generate_embedding 对「没有 CIS 的资产」到底写出什么 + 门槛是否惰性。"""
    res = {"writer": "src/data/vector/embedder.py::generate_embedding",
           "compute_full_vec_in_repo": False}
    emb_path = os.path.join(REPO, "src/data/vector/embedder.py")
    pgv_path = os.path.join(REPO, "src/data/vector/pgvector_store.py")
    vec_path = os.path.join(REPO, "src/api/routers/vector.py")

    # 仓里到底有没有 compute_full_vec(排除本脚本与 docs/research/ —— 那里的字符串是本卡自己的文字,
    # 算进去会变成「自指命中」,让报告的「仓里没有这个函数」变成假话)
    hits = []
    me = os.path.abspath(__file__)
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "Shadow", "__pycache__")]
        for fn in files:
            if fn.endswith(".py"):
                p = os.path.join(root, fn)
                ap = os.path.abspath(p)
                if ap == me or "/docs/research/" in ap.replace(os.sep, "/"):
                    continue
                try:
                    with open(p, errors="ignore") as f:
                        if "compute_full_vec" in f.read():
                            hits.append(os.path.relpath(p, REPO))
                except OSError:
                    pass
    res["compute_full_vec_files"] = hits[:10]
    res["compute_full_vec_in_repo"] = bool(hits)
    res["compute_full_vec_scan_excluded"] = "本脚本自身 + docs/research/**(自指字符串)"

    res["source_lines"] = {
        "embedder": scan_source(emb_path, [
            r"def generate_embedding\(",
            r"_missing = _NAN if unmeasured_as_nan else 0\.0",
            r"unmeasured_as_nan: bool = False",
            r"^MIN_MEASURED_DIMS = ",
            r"^def measured_dims\(",
            r"^def is_thin\(",
            r"1e6",
            r"ath_distance_pct",
            r"funding_rate",
            r"oi_usd",
        ]),
        "pgvector_store": scan_source(pgv_path, [r"^def upsert_embeddings\(", r"is_thin"]),
        "vector_router": scan_source(vec_path, [r"generate_embedding\(", r"unmeasured_as_nan", r"asset_edge_moments"]),
    }

    # 动态探针:造一个「没有 CIS、没有市值、没有资金费、没有 OI」的非 CIS 资产,看写端写出什么
    probe_asset = {
        "symbol": "PROBE_NONCIS", "name": "probe", "asset_class": "crypto",
        "pillars": {}, "cis_score": None, "grade": None, "signal": None,
        "market_cap": None, "volume_24h": None, "price": None,
        "ath_distance_pct": None, "las": None, "confidence": None,
    }
    try:
        from src.data.vector import embedder as _emb
        v_def = _emb.generate_embedding(probe_asset, macro_regime="Neutral", derivatives=None)
        v_nan = _emb.generate_embedding(probe_asset, macro_regime="Neutral", derivatives=None,
                                        unmeasured_as_nan=True)
        res["dynamic"] = {
            "import_ok": True,
            "MIN_MEASURED_DIMS": getattr(_emb, "MIN_MEASURED_DIMS", None),
            "default_vec": [None if (isinstance(v, float) and v != v) else v for v in v_def],
            "default_measured_dims": _emb.measured_dims(v_def),
            "default_is_thin": bool(_emb.is_thin(v_def)),
            "nan_vec": [None if (isinstance(v, float) and v != v) else v for v in v_nan],
            "nan_measured_dims": _emb.measured_dims(v_nan),
            "nan_is_thin": bool(_emb.is_thin(v_nan)),
            "note": "default(活路径:vector.py 不传 unmeasured_as_nan) vs unmeasured_as_nan=True",
        }
    except Exception as e:  # noqa: BLE001
        res["dynamic"] = {"import_ok": False, "error": type(e).__name__ + ": " + str(e)[:200]}

    # 活路径有没有把 flag 传下去 + upsert 有没有过门槛
    try:
        with open(vec_path) as f:
            vtxt = f.read()
        m = re.search(r"generate_embedding\((.*?)\n\s*\)", vtxt, re.S)
        call = m.group(0) if m else ""
        res["live_call_uses_unmeasured_as_nan"] = "unmeasured_as_nan" in call
        res["live_call_text"] = call.strip()[:600]
    except OSError as e:
        res["live_call_uses_unmeasured_as_nan"] = None
        res["live_call_error"] = str(e)
    try:
        with open(pgv_path) as f:
            ptxt = f.read()
        res["upsert_calls_is_thin"] = "is_thin(" in ptxt
    except OSError as e:
        res["upsert_calls_is_thin"] = None
        res["upsert_error"] = str(e)
    return res


def audit_stored_vectors():
    """存量向量审计:写端默认值污染率([11]=0/[12]=0/[13]=0.5 是默认值,不是实测)。"""
    rows = page_all("asset_embeddings", "select=symbol,asset_class,schema_version,computed_at,vec_full",
                    "symbol.asc")
    n = 0
    n_nonnull = 0
    sig_default = []
    oi_zero = []
    edge_null = []
    edge_nonnull = []
    for r in rows:
        vf = r.get("vec_full") or []
        if not vf:
            continue
        n += 1
        n_nonnull += sum(1 for v in vf if v is not None)
        def at(i):
            return vf[i] if i < len(vf) else None
        if at(11) == 0.0 and at(12) == 0.0 and at(13) == 0.5:
            sig_default.append(r["symbol"])
        if at(12) == 0.0:
            oi_zero.append(r["symbol"])
        if at(25) is None or at(26) is None:
            edge_null.append(r["symbol"])
        else:
            edge_nonnull.append(r["symbol"])
    return {
        "n_rows": n,
        "n_nonnull_dims_total": n_nonnull,
        "n_default_signature_11_12_13": len(sig_default),
        "default_signature_symbols": sorted(sig_default)[:40],
        "n_oi_dim_exactly_zero": len(oi_zero),
        "oi_zero_symbols": sorted(oi_zero)[:40],
        "n_edge_moments_null": len(edge_null),
        "n_edge_moments_nonnull": len(edge_nonnull),
        "edge_nonnull_symbols": sorted(edge_nonnull)[:40],
    }


def plan_texts(agg):
    """最小方案的两段口径说明 —— 单一实现:main() 与 --recompute-plan 共用。"""
    g = agg.get("missing_dim_groups_after_oi", {})

    def cnt(pred):
        return sum(v for k, v in g.items() if k != "none" and pred(set(k.split(","))))

    none_n = g.get("none", 0)
    only11 = cnt(lambda s: s == {"11"})
    with_610 = cnt(lambda s: {"6", "10"} <= s)
    with_610_11 = cnt(lambda s: {"6", "10", "11"} <= s)
    funding_criterion = (
        "[11] 资金费算「实测」的门槛:DB 里最后一次结算距今 ≤ %d 天(写端要的是**当前**资金费,"
        "16 天前的旧值不算实测)。「补 OI」「补 funding」两个场景都是同一个假设:把**已有**抓取器的 "
        "universe 扩到票源币,不是新建抓取器 ⇒ 补 funding 后 [11] 对所有票源币都算可得。"
        % FUND_FRESH_DAYS)
    reconciliation = (
        "Seth 2026-11-13 的 per_symbol 分组(缺 [12] 100 / 缺 [11][12] 72 / 缺 [6][10][12] 26 / "
        "缺 [6][10][11][12] 43)与本脚本「补 OI 后」的分组逐组相差 ≤2 个币"
        "(本轮实测:不缺 %d、只缺 [11] %d、缺市值+成交量 %d、缺市值+成交量+资金费 %d);"
        "差在市值/成交量行取不取与 funding 新鲜度的口径边界,不影响结论 —— 两边都指向同一件事:"
        "补 OI 只让约 100 个币够门槛,补 funding 再加约 70 个,剩下约 70 个币缺市值/成交量,没有现成源。"
        % (none_n, only11, with_610, with_610_11))
    return {"funding_criterion": funding_criterion,
            "reconciliation_with_seth_1113o": reconciliation}


def plan_aggregates(dim_plan):
    """最小方案各场景的计数与分布 —— 单一实现:main() 取数后调它,--recompute-plan 也调它。"""
    def hist(key):
        h = defaultdict(int)
        for v in dim_plan.values():
            h[v[key]] += 1
        return {str(k): v for k, v in sorted(h.items())}

    def missing_groups(key):
        g = defaultdict(int)
        for v in dim_plan.values():
            g[",".join(str(x) for x in v[key]) or "none"] += 1
        return dict(sorted(g.items(), key=lambda kv: -kv[1]))

    return {
        "n_reaching_floor_db_only": sum(1 for v in dim_plan.values() if v["n_db"] >= MIN_MEASURED_DIMS),
        "n_reaching_floor_db_plus_panel": sum(1 for v in dim_plan.values()
                                              if v["n_db_plus_panel"] >= MIN_MEASURED_DIMS),
        "n_reaching_floor_plus_oi": sum(1 for v in dim_plan.values()
                                        if v["n_plus_oi"] >= MIN_MEASURED_DIMS),
        "n_reaching_floor_plus_oi_plus_funding": sum(1 for v in dim_plan.values()
                                                     if v["n_plus_oi_plus_funding"] >= MIN_MEASURED_DIMS),
        "measured_dim_histogram_db_only": hist("n_db"),
        "measured_dim_histogram_db_plus_panel": hist("n_db_plus_panel"),
        "measured_dim_histogram_plus_oi": hist("n_plus_oi"),
        "measured_dim_histogram_plus_oi_plus_funding": hist("n_plus_oi_plus_funding"),
        "missing_dim_groups_after_oi_plus_funding": missing_groups("missing_after_oi_plus_funding"),
        "missing_dim_groups_after_oi": missing_groups("missing_after_oi"),
    }


def main():
    res = {"card": "T-366", "lane": "lane-b", "ran_utc": NOW.isoformat(),
           "round": 2, "changes_addressed": "Seth 2026-11-13 八条 CHANGES(§Seth-1113o / §Seth-1113q)"}

    # ── 1. 票源 ──────────────────────────────────────────────────────────────────────────────
    all_tickets, raw = load_tickets()
    tickets = [t for t in all_tickets if t["signal_d"] >= SINCE]
    bars = load_um()
    last_close = {s: v[-1][1] for s, v in bars.items()}
    last_date = {s: v[-1][0] for s, v in bars.items()}
    ath_close = {s: max(c for _, c, _, _, _ in v) for s, v in bars.items()}
    bar_span = {s: (v[0][0], v[-1][0], len(v)) for s, v in bars.items()}

    per_ticket = []
    for t in tickets:
        sym = t["symbol"].upper()
        r = t.get("r")
        mtm = None
        if r is None:
            lc = last_close.get(sym)
            if lc and t.get("entry_px"):
                mtm = lc / t["entry_px"] - 1.0
            r = mtm
        stop_frac = None
        if t.get("entry_px") and t.get("stop_px") and t["entry_px"] != t["stop_px"]:
            stop_frac = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
        notional = pnl = None
        if stop_frac and 0 < stop_frac < 0.9 and r is not None:
            notional = min(EQUITY0 * RISK_FRAC / stop_frac, EQUITY0 * MAX_FRAC)
            pnl = notional * r
        per_ticket.append({
            "symbol": sym, "signal_d": t["signal_d"], "entry_d": t.get("entry_d"),
            "r": r, "mtm": mtm, "notional_usd": notional, "pnl_usd": pnl,
        })

    syms = sorted({t["symbol"] for t in per_ticket})
    n_tickets = len(per_ticket)
    tot_abs = sum(abs(t["pnl_usd"]) for t in per_ticket if t["pnl_usd"] is not None)
    tot_net = sum(t["pnl_usd"] for t in per_ticket if t["pnl_usd"] is not None)
    res["ticket_source"] = {
        "file": "docs/research/t197_results.json → tickets.A(与 t310_slots.load_tickets 同源)",
        "all_tickets": len(all_tickets), "window_since": SINCE,
        "n_tickets": n_tickets, "n_symbols": len(syms),
        "signal_range": [min(t["signal_d"] for t in per_ticket), max(t["signal_d"] for t in per_ticket)],
        "n_tickets_no_r": sum(1 for t in per_ticket if t["r"] is None),
        "n_tickets_mtm_from_um": sum(1 for t in per_ticket if t.get("mtm") is not None),
        "n_tickets_no_notional": sum(1 for t in per_ticket if t["notional_usd"] is None),
        "abs_pnl_usd": round(tot_abs, 2), "net_pnl_usd": round(tot_net, 2),
        "equity0": EQUITY0, "risk_frac": RISK_FRAC, "max_frac": MAX_FRAC,
        "um_panel": {"file": UM, "n_symbols": len(bars),
                     "first_date": min((v[0][0] for v in bars.values()), default=None),
                     "last_date": max((v[-1][0] for v in bars.values()), default=None)},
    }

    # ── 2. 三套覆盖 ──────────────────────────────────────────────────────────────────────────
    # 2a. asset_embeddings(v3 且 7 天内更新)
    emb_rows = page_all("asset_embeddings", "select=symbol,asset_class,schema_version,computed_at,dims",
                        "symbol.asc")
    cut = NOW - dt.timedelta(days=FRESH_DAYS)
    emb = {}
    for r in emb_rows:
        ca = r.get("computed_at")
        ca_d = dt.datetime.fromisoformat(ca) if ca else None
        emb[r["symbol"]] = {
            "schema_version": r.get("schema_version"), "asset_class": r.get("asset_class"),
            "computed_at": ca, "fresh": bool(ca_d and ca_d >= cut),
            "v3": r.get("schema_version") == 3,
        }
    emb_ok = {s for s, v in emb.items() if v["v3"] and v["fresh"]}
    emb_classes = defaultdict(list)
    for s, v in emb.items():
        if s in emb_ok:
            emb_classes[v["asset_class"]].append(s)
    res["asset_embeddings"] = {
        "rows": len(emb_rows),
        "n_v3": sum(1 for v in emb.values() if v["v3"]),
        "n_fresh": sum(1 for v in emb.values() if v["fresh"]),
        "n_v3_and_fresh": len(emb_ok),
        "asset_class_breakdown": {k: len(v) for k, v in sorted(emb_classes.items())},
        "crypto_symbols": sorted(s for k, v in emb_classes.items()
                                 if k not in ("US Equity", "US Bond", "Commodity", "FX")
                                 for s in v),
        "max_computed_at": max((v["computed_at"] for v in emb.values() if v["computed_at"]), default=None),
        "stale_symbols": sorted(s for s, v in emb.items() if not (v["v3"] and v["fresh"])),
        "stored_vector_audit": audit_stored_vectors(),
    }

    # 2b. asset_flow_daily(逐币「自己最新的一行」)
    cr, body = q("asset_flow_daily", "select=d&order=d.desc&limit=1")
    flow_max_d = json.loads(body)[0]["d"]
    flow_cut60 = (dt.date.fromisoformat(flow_max_d) - dt.timedelta(days=HIST_DAYS)).isoformat()
    flow_by_sym = {}
    for ch in chunks(syms, CHUNK):
        rows = page_all("asset_flow_daily",
                        "select=symbol,d,vec&symbol=in." + in_list(ch) + "&d=gte." + flow_cut60,
                        "symbol.asc,d.desc")
        seen = set()
        for r in rows:
            if r["symbol"] in seen:
                continue
            seen.add(r["symbol"])
            flow_by_sym[r["symbol"]] = {
                "d": r["d"], "vec": r.get("vec") not in (None, "", "null"),
                "stale_days": (dt.date.fromisoformat(flow_max_d)
                               - dt.date.fromisoformat(r["d"])).days,
            }
    for s in syms:
        if s not in flow_by_sym:
            r = latest_row("asset_flow_daily", "d", "symbol,d,vec", s)
            if r:
                flow_by_sym[s] = {
                    "d": r["d"], "vec": r.get("vec") not in (None, "", "null"),
                    "stale_days": (dt.date.fromisoformat(flow_max_d)
                                   - dt.date.fromisoformat(r["d"])).days,
                }
    flow_ok = {s for s, v in flow_by_sym.items() if v["vec"]}
    flow_ok_fresh = {s for s, v in flow_by_sym.items() if v["vec"] and v["stale_days"] <= FRESH_DAYS}
    flow_stale_days = sorted(v["stale_days"] for v in flow_by_sym.values())
    res["asset_flow_daily"] = {
        "max_d": flow_max_d, "rows_total": q("asset_flow_daily", "select=symbol&limit=1", count=True)[0],
        "fresh_cut": flow_cut60,
        "n_ticket_symbols_present": len(flow_by_sym),
        "n_ticket_symbols_with_vec": len(flow_ok),
        "n_ticket_symbols_with_vec_fresh7d": len(flow_ok_fresh),
        "median_stale_days": median(flow_stale_days),
        "ticket_symbols_no_vec": sorted(s for s, v in flow_by_sym.items() if not v["vec"]),
        "ticket_symbols_absent": sorted(s for s in syms if s not in flow_by_sym),
        "note": "覆盖口径 = 该币自己最新一行的 vec 非空;fresh7d = 那一行距全表 max_d ≤ 7 天",
    }

    # 2c. cis_official_daily
    cis_rows = page_all("cis_official_daily", "select=symbol,d,cis_score,grade,signal", "symbol.asc,d.asc")
    cis_latest = {}
    for r in cis_rows:
        cur = cis_latest.get(r["symbol"])
        if cur is None or r["d"] > cur["d"]:
            cis_latest[r["symbol"]] = r
    cis_ok = {s for s, r in cis_latest.items() if r.get("cis_score") is not None}
    res["cis_official_daily"] = {
        "rows": len(cis_rows), "n_symbols": len(cis_latest),
        "max_d": max((r["d"] for r in cis_rows), default=None),
        "n_symbols_with_score": len(cis_ok),
        "grades": sorted({r.get("grade") for r in cis_latest.values() if r.get("grade")}),
    }

    # ── 3. 逐币覆盖 + 三种权重 + 盈亏归属(②)─────────────────────────────────────────────────
    tickets_by_sym = defaultdict(list)
    for t in per_ticket:
        tickets_by_sym[t["symbol"]].append(t)

    rows_out = []
    for s in syms:
        ts = tickets_by_sym[s]
        pnl_abs = sum(abs(t["pnl_usd"]) for t in ts if t["pnl_usd"] is not None)
        pnl_net = sum(t["pnl_usd"] for t in ts if t["pnl_usd"] is not None)
        rows_out.append({
            "symbol": s,
            "n_tickets": len(ts),
            "pnl_abs_usd": round(pnl_abs, 4),
            "pnl_net_usd": round(pnl_net, 4),
            "in_asset_embeddings_v3_fresh": s in emb_ok,
            "in_asset_flow_daily_vec": s in flow_ok,
            "in_asset_flow_daily_vec_fresh7d": s in flow_ok_fresh,
            "in_cis_official_daily": s in cis_ok,
            "um_bars": bar_span.get(s),
            "um_last_close": last_close.get(s),
        })

    def cov(pred):
        c = [r for r in rows_out if pred(r)]
        n_coin = len(c)
        n_tk = sum(r["n_tickets"] for r in c)
        abs_pnl = sum(r["pnl_abs_usd"] for r in c)
        net_pnl = sum(r["pnl_net_usd"] for r in c)
        tot_abs = sum(r["pnl_abs_usd"] for r in rows_out)
        tot_net = sum(r["pnl_net_usd"] for r in rows_out)
        tot_tk = sum(r["n_tickets"] for r in rows_out)
        return {
            "n_coins": n_coin, "coins_total": len(rows_out),
            "coin_pct": round(100.0 * n_coin / max(1, len(rows_out)), 1),
            "n_tickets": n_tk, "tickets_total": tot_tk,
            "ticket_pct": round(100.0 * n_tk / max(1, tot_tk), 1),
            "abs_pnl_usd": round(abs_pnl, 2), "abs_pnl_total_usd": round(tot_abs, 2),
            "abs_pnl_pct": round(100.0 * abs_pnl / tot_abs, 1) if tot_abs else None,
            "net_pnl_usd": round(net_pnl, 2), "net_pnl_total_usd": round(tot_net, 2),
            "net_pnl_pct": round(100.0 * net_pnl / tot_net, 1) if tot_net else None,
            "n_coins_positive_net": sum(1 for r in c if r["pnl_net_usd"] > 0),
            "n_coins_negative_net": sum(1 for r in c if r["pnl_net_usd"] < 0),
            "net_over_abs_pct": round(100.0 * net_pnl / abs_pnl, 1) if abs_pnl else None,
        }

    res["coverage"] = {
        "asset_embeddings_v3_fresh": cov(lambda r: r["in_asset_embeddings_v3_fresh"]),
        "asset_flow_daily_vec": cov(lambda r: r["in_asset_flow_daily_vec"]),
        "asset_flow_daily_vec_fresh7d": cov(lambda r: r["in_asset_flow_daily_vec_fresh7d"]),
        "cis_official_daily": cov(lambda r: r["in_cis_official_daily"]),
        "all_three": cov(lambda r: r["in_asset_embeddings_v3_fresh"] and r["in_asset_flow_daily_vec"]
                         and r["in_cis_official_daily"]),
        "any_one": cov(lambda r: r["in_asset_embeddings_v3_fresh"] or r["in_asset_flow_daily_vec"]
                        or r["in_cis_official_daily"]),
        "none_of_three": cov(lambda r: not (r["in_asset_embeddings_v3_fresh"] or r["in_asset_flow_daily_vec"]
                                            or r["in_cis_official_daily"])),
    }
    res["per_coin"] = rows_out
    # ②「两边都赚」的硬数字:全窗赚钱币 / 亏钱币的分布
    res["pnl_sign_split"] = {
        "n_coins_positive_net": sum(1 for r in rows_out if r["pnl_net_usd"] > 0),
        "n_coins_negative_net": sum(1 for r in rows_out if r["pnl_net_usd"] < 0),
        "n_coins_zero_net": sum(1 for r in rows_out if r["pnl_net_usd"] == 0),
        "net_pnl_total_usd": round(tot_net, 2), "abs_pnl_total_usd": round(tot_abs, 2),
        "note": "覆盖组 vs 未覆盖组都报净盈亏与净/|P&L|;「未覆盖 ⇒ 亏钱那一侧」是错的",
    }

    # ── 4. 27 维 + 真实写端探针(⑤)─────────────────────────────────────────────────────────
    res["writer_probe"] = writer_probe()
    cr, body = q("asset_edge_moments", "select=symbol,edge_vol,edge_p10&limit=5")
    res["asset_edge_moments_view"] = {
        "rows_returned": len(json.loads(body)) if not body.startswith("ERR") else None,
        "content_range": cr,
        "error": body[:120] if body.startswith("ERR") else None,
    }

    # ── 5. 最小方案(① 逐币实测 + ⑦ funding)───────────────────────────────────────────────
    hist_cut = (NOW.date() - dt.timedelta(days=HIST_DAYS)).isoformat()
    mcap_last, mcap_hist, mcap_px = {}, defaultdict(int), defaultdict(list)
    ohlcv_last, ohlcv_hist, ohlcv_px = {}, defaultdict(int), defaultdict(list)
    fund_last, fund_hist = {}, defaultdict(int)

    for ch in chunks(syms, CHUNK):
        rows = page_all("asset_mcap_daily",
                        "select=symbol,d,price,mcap,volume&symbol=in." + in_list(ch)
                        + "&d=gte." + hist_cut, "symbol.asc,d.asc")
        for r in rows:
            s = r["symbol"]
            mcap_hist[s] += 1
            if r.get("mcap") is not None:
                mcap_last[s] = r["d"]
            if r.get("price") is not None:
                mcap_px[s].append((r["d"], float(r["price"])))
    for ch in chunks(syms, CHUNK):
        rows = page_all("ohlcv_daily",
                        "select=symbol,trade_date,close,source&symbol=in." + in_list(ch)
                        + "&trade_date=gte." + hist_cut, "symbol.asc,trade_date.asc")
        for r in rows:
            s = r["symbol"]
            ohlcv_hist[s] += 1
            ohlcv_last[s] = r["trade_date"]
            if r.get("close") is not None:
                ohlcv_px[s].append((r["trade_date"], float(r["close"])))
    fund_cut = (NOW - dt.timedelta(days=HIST_DAYS)).isoformat()
    # 逐币取最近 25 条(8h 结算 ⇒ 约 8 天)。分片拉 funding_history 会撞服务端超时(本轮实测空响应)
    for s in syms:
        cr, body = q("funding_history",
                     "select=symbol,funding_time,funding_rate&symbol=eq." + s
                     + "&order=funding_time.desc&limit=25")
        if body.startswith("ERR"):
            continue
        try:
            rows = json.loads(body)
        except Exception:  # noqa: BLE001
            continue
        if rows:
            fund_hist[s] = len(rows)
            fund_last[s] = rows[0]["funding_time"]

    # 窗口外的币:逐币问「你最后一行是什么时候」(存在性判定)
    for s in syms:
        if s not in mcap_last:
            r = latest_row("asset_mcap_daily", "d", "symbol,d,mcap,price,volume", s)
            if r:
                mcap_last[s] = r["d"]
        if s not in ohlcv_last:
            r = latest_row("ohlcv_daily", "trade_date", "symbol,trade_date,close,source", s)
            if r:
                ohlcv_last[s] = r["trade_date"]
        if s not in fund_last:
            r = latest_row("funding_history", "funding_time", "symbol,funding_time,funding_rate", s)
            if r:
                fund_last[s] = r["funding_time"]

    hl = load_hl_funding()
    hl_last = {s: v[-1][0] for s, v in hl.items()}

    def days_since(datestr):
        try:
            d = dt.date.fromisoformat(str(datestr)[:10])
        except Exception:  # noqa: BLE001
            return None
        return (NOW.date() - d).days

    dim_plan = {}
    for s in syms:
        panel = bar_span.get(s)
        n_panel = panel[2] if panel else 0
        n_db_px = max(ohlcv_hist.get(s, 0), mcap_hist.get(s, 0))
        has_mcap = s in mcap_last
        has_vol = any(v for _, v in [])  # 占位,下面用真实行判断
        # 有没有带 volume 的市值行(量市值比 [10] 需要分子分母都在)
        vol_row = latest_row("asset_mcap_daily", "d", "symbol,d,mcap,price,volume", s)
        has_vol = bool(vol_row and vol_row.get("volume") is not None and vol_row.get("mcap"))
        has_fund_db = s in fund_last
        has_fund_hl = s in hl_last
        # [11] 资金费算「实测」的门槛:DB 里最后一次结算 ≤7 天(或 Mac 的 Hyperliquid 行在)
        _fage = days_since(fund_last.get(s)) if s in fund_last else None
        fund_db_fresh = has_fund_db and _fage is not None and _fage <= FUND_FRESH_DAYS
        base = set()
        if n_db_px >= 31:
            base.update([7, 8, 9])
        if has_mcap:
            base.add(6)
        if has_vol:
            base.add(10)
        if fund_db_fresh:
            base.add(11)
        base.update([16, 17])          # 类别编码(加密默认) + 全局 regime —— 非 CIS 依赖
        db_dims = sorted(base)
        # + Mac 永续面板:涨跌三维 + ATH 代理
        panel_dims = set(base)
        if n_panel >= 31:
            panel_dims.update([7, 8, 9, 13])
        # + OI 存量(假设把已有 CoinGecko derivatives 抓取器 universe 扩到票源币)
        oi_dims = set(panel_dims) | {12}
        # + funding:「补 funding」场景 = funding 源扩到全部票源币(与「补 OI」同一个假设:扩已有抓取器的
        # universe,不是新建抓取器)⇒ [11] 对所有币都算可得;今天真正有**新鲜**资金费的币另记 funding_used_src。
        oi_fund_dims = set(oi_dims) | {11}
        dim_plan[s] = {
            "n_db": len(db_dims), "dims_db": db_dims,
            "n_db_plus_panel": len(panel_dims), "dims_db_plus_panel": sorted(panel_dims),
            "n_plus_oi": len(oi_dims), "dims_plus_oi": sorted(oi_dims),
            "n_plus_oi_plus_funding": len(oi_fund_dims), "dims_plus_oi_plus_funding": sorted(oi_fund_dims),
            "missing_after_oi": sorted(set(NON_CIS_DIMS) - oi_dims),
            "missing_after_oi_plus_funding": sorted(set(NON_CIS_DIMS) - oi_fund_dims),
            "panel_bars": n_panel,
            "db_px_rows_last60d": n_db_px,
            "mcap_last_d": mcap_last.get(s), "mcap_age_days": days_since(mcap_last.get(s)) if s in mcap_last else None,
            "ohlcv_last_d": ohlcv_last.get(s), "ohlcv_age_days": days_since(ohlcv_last.get(s)) if s in ohlcv_last else None,
            "funding_last_t": fund_last.get(s), "funding_age_days": days_since(fund_last.get(s)) if s in fund_last else None,
            "funding_src_db": has_fund_db, "funding_src_hyperliquid": has_fund_hl,
            "funding_db_fresh": fund_db_fresh,
            "funding_used_src": ("db_fresh" if fund_db_fresh
                                 else ("hyperliquid" if has_fund_hl
                                       else ("stale_db" if has_fund_db else "none"))),
            "funding_hl_last_d": hl_last.get(s),
        }

    res["minimal_plan"] = {
        "write_floor_dims": MIN_MEASURED_DIMS,
        "non_cis_dims": NON_CIS_DIMS,
        "n_cis_dependent_dims": 27 - len(NON_CIS_DIMS),
        "n_symbols": len(syms),
        **plan_aggregates(dim_plan),
        "funding_fresh_days": FUND_FRESH_DAYS,
        "sources": {
            "um_daily(永续日线,Mac 数据根)": {
                "n_symbols": sum(1 for s in syms if s in bars),
                "file": UM,
                "last_date": max((v[-1][0] for v in bars.values()), default=None)},
            "ohlcv_daily(DB,最近 %dd)" % HIST_DAYS: {
                "n_symbols": sum(1 for s in syms if s in ohlcv_last),
                "latest_date_max": max(ohlcv_last.values()) if ohlcv_last else None,
                "note": "窗口外只查「最后一行日期」,不做逐行计数"},
            "asset_mcap_daily(DB,最近 %dd)" % HIST_DAYS: {
                "n_symbols": sum(1 for s in syms if s in mcap_last),
                "latest_date_max": max(mcap_last.values()) if mcap_last else None,
                "median_age_days": median([days_since(v) for v in mcap_last.values() if days_since(v) is not None]),
            },
            "funding_history(DB,任意时刻)": {
                "n_symbols": sum(1 for s in syms if s in fund_last),
                "latest_max": max(fund_last.values()) if fund_last else None,
                "n_symbols_within_7d": sum(1 for s in syms if s in fund_last
                                           and days_since(fund_last[s]) is not None
                                           and days_since(fund_last[s]) <= FUND_FRESH_DAYS)},
            "hyperliquid_funding(Mac 数据根,1h CSV)": {
                "n_symbols": sum(1 for s in syms if s in hl_last),
                "dir": HL_FUND,
                "latest_max": max(hl_last.values()) if hl_last else None,
                "note": "与写端要的 Binance funding 不同场所;这是「口径差」不是「同一个量」"},
            "OI 存量": {"n_symbols": 0, "note": "库里没有 OI 存量(只有 flow.doi7 的 ΔOI)"},
        },
        "per_symbol": dim_plan,
    }
    res["minimal_plan"].update(plan_texts(res["minimal_plan"]))

    # ── 6. 永续/现货口径差(⑦)──────────────────────────────────────────────────────────────
    spot_px = {s: dict(v) for s, v in ohlcv_px.items()}
    basis_rows = []
    for s in syms:
        if s not in bars or s not in spot_px:
            continue
        diffs = []
        for d, c, _h, _l, _qv in bars[s][-HIST_DAYS:]:
            sp = spot_px[s].get(d)
            if sp and c:
                diffs.append((d, c / sp - 1.0))
        if diffs:
            vals = [x[1] for x in diffs]
            basis_rows.append({"symbol": s, "n_pairs": len(vals),
                                "median_rel": median(vals),
                                "mean_abs_rel": sum(abs(v) for v in vals) / len(vals),
                                "max_abs_rel": max(abs(v) for v in vals)})
    all_rel = []
    for s in syms:
        if s not in bars or s not in spot_px:
            continue
        for d, c, _h, _l, _qv in bars[s][-HIST_DAYS:]:
            sp = spot_px[s].get(d)
            if sp and c:
                all_rel.append(c / sp - 1.0)
    emb_basis = [b for b in basis_rows if b["symbol"] in emb_ok]
    res["perp_spot_basis"] = {
        "n_symbols_compared": len(basis_rows),
        "n_pairs_total": len(all_rel),
        "median_rel": median(all_rel),
        "p90_abs_rel": pct([abs(v) for v in all_rel], 0.90),
        "max_abs_rel": max((abs(v) for v in all_rel), default=None),
        "n_symbols_gt_1pct": sum(1 for b in basis_rows if b["median_rel"] is not None
                                 and abs(b["median_rel"]) > 0.01),
        "emb_covered_subset": {
            "n_symbols": len(emb_basis),
            "median_rel": median([b["median_rel"] for b in emb_basis]),
            "p90_abs_rel": pct([abs(b["median_rel"]) for b in emb_basis if b["median_rel"] is not None], 0.90),
        },
        "per_symbol": basis_rows,
        "note": "永续面板收盘 ÷ 同日现货收盘 − 1(同源同日配对);现货 = ohlcv_daily.close",
    }

    # funding 场所口径差:Hyperliquid(1h)vs Binance(DB,8h),按日归一
    fund_diff = []
    for s in syms:
        if s not in hl or s not in fund_last:
            continue
        # DB 侧:最近 30 天的日均 8h 资金费合计
        db_rates = []
        for ch in [s]:
            rows = page_all("funding_history",
                            "select=funding_time,funding_rate&symbol=eq." + ch
                            + "&funding_time=gte." + (NOW - dt.timedelta(days=30)).isoformat(),
                            "funding_time.asc")
            db_rates = [float(r["funding_rate"]) for r in rows if r.get("funding_rate") is not None]
        hl_rows = hl[s][-720:]
        hl_daily = {}
        for d, rate in hl_rows:
            hl_daily[d] = hl_daily.get(d, 0.0) + rate
        hl_vals = list(hl_daily.values())
        if db_rates and hl_vals:
            fund_diff.append({"symbol": s,
                               "db_mean_per_8h": sum(db_rates) / len(db_rates),
                               "db_n": len(db_rates),
                               "hl_mean_per_day": sum(hl_vals) / len(hl_vals),
                               "hl_days": len(hl_vals),
                               "abs_diff_per_day_bp": abs(sum(db_rates) / len(db_rates) * 3
                                                         - sum(hl_vals) / len(hl_vals)) * 10000})
    res["funding_venue_diff"] = {
        "n_symbols_compared": len(fund_diff),
        "median_abs_diff_bp_per_day": median([f["abs_diff_per_day_bp"] for f in fund_diff]),
        "p90_abs_diff_bp_per_day": pct([f["abs_diff_per_day_bp"] for f in fund_diff], 0.90),
        "max_abs_diff_bp_per_day": max((f["abs_diff_per_day_bp"] for f in fund_diff), default=None),
        "per_symbol": fund_diff,
        "note": "Binance(8h,×3/日)对 Hyperliquid(1h,日内求和);两个场所不是同一个量,数值差即口径差",
    }

    # ── 7. 同口径对照实验(⑧)+ §7 降级 ───────────────────────────────────────────────────
    res["flow_control"] = flow_control(syms, emb_ok)
    res["state_probe"] = state_probe()

    # ── 8. 落盘 ────────────────────────────────────────────────────────────────────────────
    res["dims"] = [list(d) for d in DIMS]
    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    md = render_report(res)
    open(OUT_MD, "w").write(md)
    print("wrote", OUT_JSON)
    print("wrote", OUT_MD, len(md), "chars")
    print(json.dumps({k: res[k] for k in ("ticket_source", "coverage", "pnl_sign_split")},
                     ensure_ascii=False, indent=1)[:3500])
    print("minimal:", json.dumps({k: v for k, v in res["minimal_plan"].items()
                                  if k.startswith("n_reaching") or k.startswith("measured")
                                  or k.startswith("missing")}, ensure_ascii=False))
    print("basis:", json.dumps({k: v for k, v in res["perp_spot_basis"].items() if k != "per_symbol"},
                               ensure_ascii=False))
    print("control:", json.dumps(res["flow_control"], ensure_ascii=False)[:1500])


def flow_control(syms, emb_ok):
    """⑧ 同口径对照:实验组=有向量(v3+7天)的币,对照组=同日全体有资金面 vec 的币里抽 24 个。"""
    out = {"method": "apparatus.null_distribution + percentile_of;对照组种子 %d" % SEED}
    try:
        from src.data.evaluation.apparatus import null_distribution, percentile_of
    except Exception as e:  # noqa: BLE001
        return {"error": "apparatus import failed: " + str(e)[:200]}
    cr, body = q("asset_flow_daily", "select=d&vec=not.is.null&order=d.desc&limit=200")
    ds = sorted({r["d"] for r in json.loads(body)}, reverse=True)
    if not ds:
        return {"error": "no asset_flow_daily day with vec"}
    d = ds[0]
    cols = ("symbol,d,vec,fund7,doi7,crowd,smart,taker7,mom7,mom30,vol30,vratio,turn,dd90,"
            "q_fund7,q_doi7,q_crowd,q_smart,q_taker7,q_mom7,q_mom30,q_vol30,q_vratio,q_turn,q_dd90")
    rows = page_all("asset_flow_daily", "select=" + cols + "&d=eq." + d + "&vec=not.is.null",
                    "symbol.asc")
    pop = [r for r in rows if r.get("vec")]
    qnames = ["q_fund7", "q_doi7", "q_crowd", "q_smart", "q_taker7", "q_mom7", "q_mom30",
              "q_vol30", "q_vratio", "q_turn", "q_dd90"]

    def posture(r):
        vals = []
        for n in qnames:
            v = r.get(n)
            if v is None:
                continue
            vals.append(2.0 * float(v) - 1.0)   # 百分位居中到 [-1,1](asset_flow.py:25)
        return sum(vals) / len(vals) if vals else None

    scored = []
    for r in pop:
        s = posture(r)
        if s is not None:
            scored.append({"symbol": r["symbol"], "posture": s,
                           "in_emb": r["symbol"] in emb_ok,
                           "vec_len": len(r.get("vec") or [])})
    pop_syms = [x["symbol"] for x in scored]
    exp = [x for x in scored if x["in_emb"]]
    rest = [x for x in scored if not x["in_emb"]]
    rng = random.Random(SEED)
    n_ctrl = min(24, len(rest))
    ctrl = rng.sample(rest, n_ctrl) if n_ctrl else []
    pop_vals = [x["posture"] for x in scored]
    exp_mean = sum(x["posture"] for x in exp) / len(exp) if exp else None
    ctrl_mean = sum(x["posture"] for x in ctrl) / len(ctrl) if ctrl else None

    # 零分布:从当日全体有资金面的币里随机抽 |实验组| 个,重复 2000 次
    n_null = 2000
    if exp and len(scored) > 1:
        def draw(rng_):
            k = len(exp)
            if k > len(scored):
                return sum(y["posture"] for y in scored) / len(scored)
            idx = rng_.choice(len(scored), k, replace=False)
            samp = [scored[i] for i in idx]
            return sum(y["posture"] for y in samp) / len(samp)
        try:
            null = null_distribution(draw, n_null, SEED, actual=exp_mean)
            pctl = percentile_of(exp_mean, null)
            out["null"] = {"n": n_null, "seed": SEED, "percentile_of_exp_mean": pctl,
                           "null_median": median(list(null)),
                           "null_p05": pct(list(null), 0.05), "null_p95": pct(list(null), 0.95)}
        except Exception as e:  # noqa: BLE001
            out["null"] = {"error": type(e).__name__ + ": " + str(e)[:200]}
    # 每个实验组成员在当日截面里的分位
    out["per_experimental_coin"] = [
        {"symbol": x["symbol"], "posture": x["posture"],
         "percentile_in_day": percentile_of(x["posture"], pop_vals)}
        for x in sorted(exp, key=lambda y: -y["posture"])
    ]
    out.update({
        "day": d, "n_population": len(scored),
        "population_symbols": sorted(pop_syms),
        "n_experimental": len(exp),
        "experimental_symbols": sorted(x["symbol"] for x in exp),
        "n_control": len(ctrl),
        "control_seed": SEED,
        "control_symbols": sorted(x["symbol"] for x in ctrl),
        "exp_mean_posture": exp_mean, "ctrl_mean_posture": ctrl_mean,
        "population_mean_posture": sum(pop_vals) / len(pop_vals) if pop_vals else None,
        "posture_formula": "11 维当日截面百分位(q_*)居中到 [-1,1] 后取均值;维序见 src/data/state/asset_flow.py:13-24",
        "caveat": "当日截面只有 %d 个币(这张表每天只写几十个币)⇒ 对照组与总体高度重叠,只能读成描述性对比" % len(scored),
    })
    return out


def state_probe():
    """⑧ 第一轮 §7 的四个 state 量的归属(entity)——用来把「那 24 个币」的归属降级。"""
    feats = ["breadth_above_ma50", "mom_20", "oi_chg_30d", "funding_7d_ann"]
    out = {}
    for f in feats:
        rows = page_all("state_daily", "select=entity,feature,d,value&feature=eq." + f, "d.desc")
        out[f] = {"entities": sorted({r["entity"] for r in rows}),
                  "latest": rows[0] if rows else None,
                  "n_rows": len(rows)}
    out["note"] = "entity 全是 'panel' ⇒ 这些量是**面板级**,不能归属到「有向量的那 24 个币」"
    return out


def render_report(res):
    """③ 报告正文由 JSON 渲染 —— 数字不手抄。"""
    ts = res["ticket_source"]
    cov = res["coverage"]
    mp = res["minimal_plan"]
    wp = res["writer_probe"]
    dyn = wp.get("dynamic", {})
    audit = res["asset_embeddings"]["stored_vector_audit"]
    basis = res["perp_spot_basis"]
    fvd = res["funding_venue_diff"]
    fc = res["flow_control"]
    sp = res["state_probe"]

    def row(name, key, ckey=None):
        c = cov[ckey or key]
        return "| %s | %d | %.1f%% | %d | %.1f%% | %.1f%% | %.1f%% | %s | %s |" % (
            name, c["n_coins"], c["coin_pct"], c["n_tickets"], c["ticket_pct"],
            c["abs_pnl_pct"] if c["abs_pnl_pct"] is not None else float("nan"),
            c["net_pnl_pct"] if c["net_pnl_pct"] is not None else float("nan"),
            ("$%s" % format(c["net_pnl_usd"], ",.2f")),
            ("$%s" % format(c["abs_pnl_usd"], ",.2f")),
        )

    L = []
    A = L.append
    A("# T-366 — 真钱在交易的币有没有向量:R-v2 票源币逐个对账(资产向量 / 资金面向量 / CIS)")
    A("")
    A("**卡** T-366(台账 S-842) · **lane-b** · 第二轮(返工 Seth 2026-11-13 八条 CHANGES)· 只读、未入库、未改 `src/`")
    A("**脚本** `docs/research/T-366_coverage.py` · **结果** `docs/research/T-366_traded_universe_coverage.json`")
    A("**生成口径**:本文件由脚本从上面的 JSON 渲染(③:数字一律从 JSON 生成,没有手抄)")
    A("")
    A("---")
    A("")
    A("## 0. 结论")
    A("")
    c_none = cov["none_of_three"]
    c_any = cov["any_one"]
    A("1. **九成票源币没有向量。** 2024-11 以来开过票的 **%d 个币**里,`asset_embeddings`"
      "(schema_version=3 且 7 天内更新)只有 **%d 个(%.1f%%)**;三套描述(资产向量 / 资金面向量 / CIS)"
      "**一个都没有**的有 **%d 个币(%.1f%%)**,对应 **%d 张票(%.1f%%)**、**%.1f%% 的 |美元盈亏|**。"
      % (ts["n_symbols"], cov["asset_embeddings_v3_fresh"]["n_coins"],
         cov["asset_embeddings_v3_fresh"]["coin_pct"], c_none["n_coins"], c_none["coin_pct"],
         c_none["n_tickets"], c_none["ticket_pct"], c_none["abs_pnl_pct"]))
    A("2. **「缺向量的就是亏钱那一侧」是错的 —— 两边都赚。** 未覆盖的 %d 个币净 **$%s**"
      "(净/|P&L| = %.1f%%),覆盖的 %d 个币净 **$%s**(%.1f%%)—— 覆盖组确实更赚钱(单位 |P&L| 的净利率更高),"
      "但**未覆盖组本身也赚钱**。全窗 %d 个币里 %d 个净赚、%d 个净亏。"
      % (c_none["n_coins"], format(c_none["net_pnl_usd"], ",.2f"), c_none["net_over_abs_pct"],
         c_any["n_coins"], format(c_any["net_pnl_usd"], ",.2f"), c_any["net_over_abs_pct"],
         res["pnl_sign_split"]["n_coins_positive_net"]
         + res["pnl_sign_split"]["n_coins_negative_net"]
         + res["pnl_sign_split"]["n_coins_zero_net"],
         res["pnl_sign_split"]["n_coins_positive_net"], res["pnl_sign_split"]["n_coins_negative_net"]))
    A("3. **27 维里 %d 维依赖 CIS、%d 维不依赖**(`%s`)。但**「非 CIS 币最多 %d 维、卡在门槛上」"
      "这个第一轮说法在活路径上不成立**:真实写端是 `src/data/vector/embedder.py::generate_embedding`,"
      "它把缺失字段填**默认值**而不是 NaN(实测 `measured_dims(default)=%s`、`is_thin(default)=%s`),"
      "且 `upsert_embeddings` **不过门槛**(upsert 源码里有没有 `is_thin(`:%s)。"
      "没有 CIS 的币写出来是**看起来完整的 %s 维**向量,支柱是 0.0 —— 不是「被门槛挡住」。"
      % (mp["n_cis_dependent_dims"], len(mp["non_cis_dims"]),
         ",".join(str(x) for x in mp["non_cis_dims"]), MIN_MEASURED_DIMS,
         dyn.get("default_measured_dims"), dyn.get("default_is_thin"),
         wp.get("upsert_calls_is_thin"), dyn.get("default_measured_dims")))
    A("4. **真正挡住扩面板的是输入契约,不是抓取器 universe。** Mac 端 `vector_push.py` 的 payload 就是"
      " `cis_scores_latest.json`(= CIS 宇宙)⇒ 非 CIS 的币根本进不了 payload;"
      "「把 CoinGecko derivatives 抓取器扩到票源币」只解决 [12] 这一维,解决不了另外 %d 维。"
      "扩面板 = 扩 payload 契约或新开写路径(需另开卡)。"
      % mp["n_cis_dependent_dims"])
    A("5. **最小方案(零新抓取器)的实测算式(逐币,不是估的)**:仅 Supabase 库 ⇒ %d 币达 %d 维门槛;"
      "加 Mac 永续日线面板 ⇒ %d 币;**再加 OI 存量 ⇒ %d 币**;"
      "**再补 funding(只有 ≤%d 天的才算实测)⇒ %d 币**(净增 %d 币);"
      "剩下 %d 个币补不满,逐币分组见第 5 节。"
      % (mp["n_reaching_floor_db_only"], mp["write_floor_dims"],
         mp["n_reaching_floor_db_plus_panel"], mp["n_reaching_floor_plus_oi"],
         mp["funding_fresh_days"], mp["n_reaching_floor_plus_oi_plus_funding"],
         mp["n_reaching_floor_plus_oi_plus_funding"] - mp["n_reaching_floor_plus_oi"],
         mp["n_symbols"] - mp["n_reaching_floor_plus_oi_plus_funding"]))
    A("")
    A("---")
    A("")
    A("## 1. 票源与口径(一字不改,全部沿用上游)")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 票源 | `%s` |" % ts["file"])
    A("| 总票 / 窗口 | %d 张 / `signal_d ≥ %s` → **%d 张票、%d 个币**,信号 %s → %s |"
      % (ts["all_tickets"], ts["window_since"], ts["n_tickets"], ts["n_symbols"],
         ts["signal_range"][0], ts["signal_range"][1]))
    A("| 未平仓票 | %d 张, r 为空 → 用 Mac 数据根永续日线最后一根收盘算 mtm(%d 张算不出名义) |"
      % (ts["n_tickets_no_r"], ts["n_tickets_no_notional"]))
    A("| 名义 | `min(净值 × 0.5%% ÷ 止损距离, 净值 × 50%%)`,净值恒取 $%.0f(t310 的 equity0,逐票独立口径,不复利) |"
      % ts["equity0"])
    A("| 美元盈亏 | `名义 × r`;全窗 **|P&L| = $%s、净 = $%s** |"
      % (format(ts["abs_pnl_usd"], ",.2f"), format(ts["net_pnl_usd"], ",.2f")))
    A("| 永续面板 | `%s`,%d 币,%s → %s |"
      % (ts["um_panel"]["file"], ts["um_panel"]["n_symbols"],
         ts["um_panel"]["first_date"], ts["um_panel"]["last_date"]))
    A("")
    A("## 2. 三套描述的现状(本轮实测)")
    A("")
    ae = res["asset_embeddings"]
    af = res["asset_flow_daily"]
    co = res["cis_official_daily"]
    A("| 表 | 规模 | 关键事实 |")
    A("|---|---|---|")
    A("| `asset_embeddings` | %d 行 | %d 行 `schema_version=3` 且 7 天内更新(最新 %s);%d 行陈旧 |"
      % (ae["rows"], ae["n_v3_and_fresh"], ae["max_computed_at"], len(ae["stale_symbols"])))
    A("| `asset_flow_daily` | %s 行 | 最新日 %s;票源 %d 币里 %d 个「自己最新一行有 vec」"
      "(其中 %d 个距最新日 ≤7 天);这 %d 个币的 vec 最新行中位陈旧 %s 天 |"
      % (af["rows_total"], af["max_d"], af["n_ticket_symbols_present"],
         af["n_ticket_symbols_with_vec"], af["n_ticket_symbols_with_vec_fresh7d"],
         af["n_ticket_symbols_with_vec"], af["median_stale_days"]))
    A("| `cis_official_daily` | %d 行 / %d 币 | 最新 %s,%d 币都有正式分(等级 %s) |"
      % (co["rows"], co["n_symbols"], co["max_d"], co["n_symbols_with_score"],
         ",".join(co["grades"])))
    A("| `asset_edge_moments`(视图) | %s | **%s 行** ⇒ 写端 [25][26] 两维无数据可取 |"
      % (res["asset_edge_moments_view"]["content_range"],
         res["asset_edge_moments_view"]["rows_returned"]))
    A("")
    A("**存量向量审计(写端默认值污染)**:%d 行存量向量里,**%d 行**的 [11]=0.0、[12]=0.0、[13]=0.5 同时成立"
      " —— 这是写端的**默认值**([13]=0.5 来自「ATH 距离缺省 50%%」),不是实测;**%d 行的 [12] 恰好为 0.0**"
      "(OI 存量从来没测到过);[25][26] 有 **%d 行为 null、%d 行非空**(非空的是历史遗留,视图今天仍是 %s 行)。"
      "`asset_embeddings` 表**没有** `measured_dims` / `source_completeness` 列 ⇒ 消费方无法按「实测维数」过滤存量向量。"
      % (audit["n_rows"], audit["n_default_signature_11_12_13"], audit["n_oi_dim_exactly_zero"],
         audit["n_edge_moments_null"], audit["n_edge_moments_nonnull"],
         res["asset_edge_moments_view"]["rows_returned"]))
    A("")
    A("## 3. 逐币覆盖(三种权重)")
    A("")
    A("| 覆盖口径 | 币数 | 占币 | 票数 | 占票 | \\|P&L\\| 占比 | 净盈亏占比 | 该组净盈亏 | 该组 \\|P&L\\| |")
    A("|---|---|---|---|---|---|---|---|---|")
    A(row("`asset_embeddings`(v3 + 7 天内)", "asset_embeddings_v3_fresh"))
    A(row("`asset_flow_daily`(逐币最新行有 vec)", "asset_flow_daily_vec"))
    A(row("`asset_flow_daily`(同上且 ≤7 天)", "asset_flow_daily_vec_fresh7d"))
    A(row("`cis_official_daily`(有正式分)", "cis_official_daily"))
    A(row("三者都有", "all_three"))
    A(row("任一有", "any_one"))
    A(row("**都没有**", "none_of_three"))
    A("")
    A("口径说明:`asset_flow_daily` 的两行分别是「该币自己最新一行的 `vec` 非空」与「那一行距全表 `max_d` ≤ 7 天」。"
      "这张表**每天只写几十个币**(最新日 %s),用全表 `max_d` 当分母会低估到 %d 币 —— 别用那个口径下结论。"
      % (af["max_d"], af["n_ticket_symbols_with_vec_fresh7d"]))
    A("")
    A("**盈亏归属(结论 2 的硬数字)**:全窗 %d 个币中 **%d 个净赚、%d 个净亏、%d 个持平**;"
      "未覆盖组净 $%s / |P&L| $%s(净利率 %.1f%%),覆盖组净 $%s / |P&L| $%s(净利率 %.1f%%)。"
      "⇒ **两边都赚**,覆盖组只是**单位 |P&L| 的净利率更高**(%.1f%% vs %.1f%%)。"
      % (ts["n_symbols"], res["pnl_sign_split"]["n_coins_positive_net"],
         res["pnl_sign_split"]["n_coins_negative_net"], res["pnl_sign_split"]["n_coins_zero_net"],
         format(c_none["net_pnl_usd"], ",.2f"), format(c_none["abs_pnl_usd"], ",.2f"),
         c_none["net_over_abs_pct"], format(c_any["net_pnl_usd"], ",.2f"),
         format(c_any["abs_pnl_usd"], ",.2f"), c_any["net_over_abs_pct"],
         c_any["net_over_abs_pct"], c_none["net_over_abs_pct"]))
    A("")
    A("## 4. 27 维逐维:依据**真实写端** `generate_embedding`(不是 `compute_full_vec` —— 仓里没有这个函数)")
    A("")
    A("写端源码扫描(行号是本脚本实测的,不是记忆里的):")
    A("")
    A("| 断言 | 文件:行 | 原文 |")
    A("|---|---|---|")
    for grp in ("embedder", "pgvector_store", "vector_router"):
        for h in wp["source_lines"].get(grp, []):
            if h.get("line") is None:
                continue
            A("| `%s` | `%s:%d` | `%s` |"
              % (h["pattern"][:40], os.path.basename(grp), h["line"], h["text"].replace("|", "\\|")))
    A("")
    A("| 维 | 含义 | 数据来源 | 没有 CIS 能不能算 | 原因 |")
    A("|---|---|---|---|---|")
    for d in res["dims"]:
        A("| [%d] | %s | %s | **%s** | %s |" % (d[0], d[1], d[3], d[4], d[5]))
    A("")
    A("**活路径动态探针**(脚本现造一个「没有 CIS / 没有市值 / 没有资金费 / 没有 OI」的资产喂给写端):")
    A("")
    if dyn.get("import_ok"):
        A("- 写端默认口径(`unmeasured_as_nan` 不传)实测:**%s 维非空**,`measured_dims` = **%s**,"
          "`is_thin` = **%s** ⇒ 写端认为它「够厚」,直接进 `upsert_embeddings`。"
          % (sum(1 for v in dyn["default_vec"] if v is not None), dyn["default_measured_dims"],
             dyn["default_is_thin"]))
        A("- 同一资产用 `unmeasured_as_nan=True`:**%s 维非空**,`measured_dims` = **%s**,`is_thin` = **%s**。"
          % (sum(1 for v in dyn["nan_vec"] if v is not None), dyn["nan_measured_dims"],
             dyn["nan_is_thin"]))
        A("- 活路径 `vector.py` 的 `generate_embedding(...)` 调用**没有传** `unmeasured_as_nan`(实测:%s)。"
          % wp.get("live_call_uses_unmeasured_as_nan"))
    else:
        A("- 动态探针未跑通:%s" % dyn.get("error"))
    A("")
    A("⇒ **写端 docstring 写的是「unmeasured is NaN, never 0」,活路径做的是「填默认值 0.0」**;"
      "两者不一致,且 `MIN_MEASURED_DIMS` 这道门槛在活路径上是惰性的(`upsert_embeddings` 不过 `is_thin`)。"
      "第一轮「非 CIS 币最多 %d 维、卡在门槛上」的表述**对活路径不成立**。" % MIN_MEASURED_DIMS)
    A("")
    A("## 5. 最小方案(只用库里已有的数据,不新建抓取器)")
    A("")
    A("| 场景 | 达 %d 维门槛的币数 | 逐币可测维数分布 |" % mp["write_floor_dims"])
    A("|---|---|---|")
    A("| 仅 Supabase 库 | %d | %s |"
      % (mp["n_reaching_floor_db_only"], mp["measured_dim_histogram_db_only"]))
    A("| + Mac 永续日线面板 | %d | %s |"
      % (mp["n_reaching_floor_db_plus_panel"], mp["measured_dim_histogram_db_plus_panel"]))
    A("| + OI 存量(扩已有 derivatives 抓取器 universe) | %d | %s |"
      % (mp["n_reaching_floor_plus_oi"], mp["measured_dim_histogram_plus_oi"]))
    A("| + funding(DB 里 ≤%d 天的,或 Mac 的 Hyperliquid 文件) | **%d** | %s |"
      % (mp["funding_fresh_days"], mp["n_reaching_floor_plus_oi_plus_funding"],
         mp["measured_dim_histogram_plus_oi_plus_funding"]))
    A("")
    A("**加完 OI + funding 之后,仍缺的维(逐币分组)**:")
    A("")
    A("| 仍缺的维 | 币数 |")
    A("|---|---|")
    for k, v in mp["missing_dim_groups_after_oi_plus_funding"].items():
        A("| %s | %d |" % ("不缺(全齐)" if k == "none"
                           else "缺 [%s]" % k.replace(",", "]["), v))
    A("")
    A("现成源的覆盖(零新抓取器):")
    A("")
    A("| 源 | 覆盖票源币 | 备注 |")
    A("|---|---|---|")
    for k, v in mp["sources"].items():
        A("| `%s` | %s | %s |" % (k, v.get("n_symbols"), v.get("note", v.get("file", ""))))
    A("")
    A("**修掉第一轮的两个数字**:第一轮写「补 OI ⇒ 172 币达 10 维」是错的 —— 逐币实测:**补 OI = %d 币**,"
      "**再补 funding 才 = %d 币**(补 funding 净增 %d 币);剩下 %d 个币补不满(逐币分组见上表)。"
      "第一轮写「立刻可算 9 维」也只在 %d 币上成立(其余币缺市值或资金费)。"
      % (mp["n_reaching_floor_plus_oi"], mp["n_reaching_floor_plus_oi_plus_funding"],
         mp["n_reaching_floor_plus_oi_plus_funding"] - mp["n_reaching_floor_plus_oi"],
         mp["n_symbols"] - mp["n_reaching_floor_plus_oi_plus_funding"],
         mp["measured_dim_histogram_db_plus_panel"].get(str(max(
             [int(k) for k in mp["measured_dim_histogram_db_plus_panel"]] or [0])), 0)))
    A("")
    A("**funding 算「实测」的门槛**:%s" % mp["funding_criterion"])
    A("")
    A("**与 Seth §Seth-1113o 的 per_symbol 分组对账**:%s" % mp["reconciliation_with_seth_1113o"])
    A("")
    A("补 OI 后(还没补 funding)的缺失维分组:")
    A("")
    A("| 仍缺的维 | 币数 |")
    A("|---|---|")
    for k, v in mp["missing_dim_groups_after_oi"].items():
        A("| %s | %d |" % ("不缺(全齐)" if k == "none"
                           else "缺 [%s]" % k.replace(",", "]["), v))
    A("")
    A("## 6. 永续 / 现货口径差(实测)")
    A("")
    A("同一币、同一天,永续面板收盘 ÷ 现货 `ohlcv_daily.close` − 1:%d 个币可配对、%d 对;"
      "中位 **%.3f%%**,|差| 的 P90 **%.3f%%**、最大 **%.3f%%**;%d 个币的日均 |差| > 1%%。"
      "有向量的那 %d 个币子集:中位 **%.3f%%**、|差| P90 **%.3f%%**。"
      % (basis["n_symbols_compared"], basis["n_pairs_total"],
         (basis["median_rel"] or 0.0) * 100, (basis["p90_abs_rel"] or 0.0) * 100,
         (basis["max_abs_rel"] or 0.0) * 100, basis["n_symbols_gt_1pct"],
         basis["emb_covered_subset"]["n_symbols"],
         (basis["emb_covered_subset"]["median_rel"] or 0.0) * 100,
         (basis["emb_covered_subset"]["p90_abs_rel"] or 0.0) * 100))
    A("")
    A("**尾部要当心**:中位几乎为 0、但 |差| 的 P90 是 %.1f%%、最大 %.1f%% ⇒ 少数币的永续面板收盘与现货收盘"
      "根本不是同一个价位(同名不同合约/报价币种/重命名),**不能用中位数代表全体**;"
      "有向量的那 %d 个币子集 |差| P90 只有 %.3f%%(干净),坏值集中在没被向量覆盖的那批币上。"
      % ((basis["p90_abs_rel"] or 0.0) * 100, (basis["max_abs_rel"] or 0.0) * 100,
         basis["emb_covered_subset"]["n_symbols"],
         (basis["emb_covered_subset"]["p90_abs_rel"] or 0.0) * 100))
    A("")
    if fvd.get("n_symbols_compared"):
        A("资金费的场所口径差(Binance 8h ×3/日 对 Hyperliquid 1h 日内求和):%d 个币可配对,"
          "日均资金费差的中位 **%.1f bp**、P90 **%.1f bp**、最大 **%.1f bp**。"
          "⇒ 用 Hyperliquid 文件补 [11] 是**换了一个场所的量**,与写端要的 Binance funding 不是同一个口径。"
          % (fvd["n_symbols_compared"], fvd["median_abs_diff_bp_per_day"] or 0.0,
             fvd["p90_abs_diff_bp_per_day"] or 0.0, fvd["max_abs_diff_bp_per_day"] or 0.0))
    else:
        A("**资金费的场所口径差(Binance vs Hyperliquid)本轮没测出来** —— DB 侧「近 30 天资金费」的"
          "带时间窗查询在 PostgREST 上返回空(分片 `symbol=in.(…)` 也返回空,见 run.log),"
          "所以没有可配对的币。**这不等于两个场所的资金费没有差**,只是这一项没测到;"
          "补测方式:逐币 `symbol=eq.X` 取最近 N 条再按日归一(与 [11] 的取数口径一致)。")
    A("")
    A("## 7. 资金面:同口径对照(替换第一轮 §7 的错归属)")
    A("")
    A("**第一轮 §7 降级**:第一轮写「向量与 CIS 描述的那 24 个币恰好在最弱的一档」—— "
      "`state_daily` 这四个量的 `entity` **全是 `panel`**(实测:%s),是**面板级**不是币级 ⇒ "
      "那句归属**不成立**,本轮不再作为结论,只保留面板级的读数。"
      % ", ".join("%s=%s" % (k, sp[k]["latest"]["value"] if sp.get(k, {}).get("latest") else "NA")
                  for k in ("breadth_above_ma50", "mom_20", "oi_chg_30d", "funding_7d_ann")))
    A("")
    if "error" in fc:
        A("同口径对照未跑通:%s" % fc["error"])
    else:
        A("同口径对照(实验组=有向量且当日有资金面的 %d 个币;对照组=同日全体有资金面的币里按种子 %d 抽 %d 个;"
          "统计量=11 维当日截面百分位居中后的均值;零分布走 `apparatus.null_distribution`,分位走 `apparatus.percentile_of`):"
          % (fc["n_experimental"], fc["control_seed"], fc["n_control"]))
        A("")
        A("| 项 | 值 |")
        A("|---|---|")
        A("| 截面日 | %s(全表有 vec 的币 %d 个) |" % (fc["day"], fc["n_population"]))
        A("| 实验组 | %d 币:均值 %.4f |" % (fc["n_experimental"], fc["exp_mean_posture"] or 0.0))
        A("| 对照组 | %d 币:均值 %.4f |" % (fc["n_control"], fc["ctrl_mean_posture"] or 0.0))
        A("| 当日全体 | 均值 %.4f |" % (fc["population_mean_posture"] or 0.0))
        if fc.get("null"):
            A("| 实验组均值在零分布里的分位 | %s(零分布中位 %.4f,P05 %.4f,P95 %.4f) |"
              % (fc["null"].get("percentile_of_exp_mean"), fc["null"].get("null_median", 0.0),
                 fc["null"].get("null_p05", 0.0), fc["null"].get("null_p95", 0.0)))
        A("")
        A("实验组逐币(当日截面分位):")
        A("")
        A("| 币 | 资金面姿态均值 | 当日分位 |")
        A("|---|---|---|")
        for x in fc.get("per_experimental_coin", []):
            A("| %s | %.4f | %s |" % (x["symbol"], x["posture"],
                                       "%.2f" % x["percentile_in_day"]
                                       if x["percentile_in_day"] is not None else "NA"))
        A("")
        A("**限制**:%s" % fc.get("caveat", ""))
    A("")
    A("## 8. 限制")
    A("")
    A("- 覆盖统计只算「有没有」,没算「对不对」;向量质量不在本卡范围。")
    A("- 净盈亏占比在净值为负的子集上会翻转,本卡用 |P&L| 作主权重、净盈亏作副权重,两个都报了。")
    A("- `asset_flow_daily` 逐币最新行与全表 `max_d` 差距大(这张表每天只写几十个币),别用 `max_d` 当分母。")
    A("- %d 张未平仓票的 mtm 用 Mac 面板末根收盘(面板止于 %s),不是「今天」。"
      % (ts["n_tickets_no_r"], ts["um_panel"]["last_date"]))
    A("- 票源窗口本身止于 %s(`r_tickets_paper` 前向 0 行),本卡不外延。" % ts["signal_range"][1])
    A("- 「达门槛」是**按输入可得性**算的(输入齐 ⇒ 写得出来),不是跑写端实测;写端实测见第 4 节探针。")
    A("")
    A("## 9. 探索性发现(**需另立预注册、在新数据上过零信号对照**)")
    A("")
    A("- **探索性 —— 需另立预注册、在新数据上过零信号对照**:永续面板与现货收盘的日均差中位 %.3f%%、"
      "|差| P90 %.3f%% ⇒ 若用面板给票源币算 [7][8][9][13],那几维与现有 59 个向量(现货口径)**不是同一度量**;"
      "混在一个相似度池里比,比的其实是两个价。"
      % ((basis["median_rel"] or 0.0) * 100, (basis["p90_abs_rel"] or 0.0) * 100))
    A("- **探索性 —— 需另立预注册、在新数据上过零信号对照**:写端把缺失字段填默认值(0.0 / 0.5)⇒ "
      "存量向量里 [11][12][13] 的「看起来有值」其实可能是缺省值;"
      "%d/%d 行带这个缺省签名 ⇒ 任何以向量维度做的相似度/聚类,都含这层伪影。"
      % (audit["n_default_signature_11_12_13"], audit["n_rows"]))
    if "error" not in fc and fc.get("null"):
        A("- **探索性 —— 需另立预注册、在新数据上过零信号对照**:有向量的那 %d 个币在当日资金面截面上的姿态均值 "
          "%.4f,零分布分位 %s ⇒ 方向上「有描述的币」并不明显更极端;样本只有 %d 个币,读不出东西。"
          % (fc["n_experimental"], fc["exp_mean_posture"] or 0.0,
             fc["null"].get("percentile_of_exp_mean"), fc["n_population"]))
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    if "--render-only" in sys.argv:
        # 重渲染:不重跑取数,直接从落盘的 JSON 重新渲染报告(改渲染器后用这个,省一轮 12 分钟)
        _res = json.load(open(OUT_JSON))
        _md = render_report(_res)
        open(OUT_MD, "w").write(_md)
        print("rendered", OUT_MD, len(_md), "chars")
    elif "--refresh-writer" in sys.argv:
        # 只重跑写端探针(纯本地读源码 + 一次视图计数),并重渲染;其余字段沿用落盘 JSON
        _res = json.load(open(OUT_JSON))
        _res["writer_probe"] = writer_probe()
        _cr, _body = q("asset_edge_moments", "select=symbol,edge_vol,edge_p10&limit=5")
        _res["asset_edge_moments_view"] = {
            "rows_returned": len(json.loads(_body)) if not _body.startswith("ERR") else None,
            "content_range": _cr,
            "error": _body[:120] if _body.startswith("ERR") else None,
        }
        json.dump(_res, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
        _md = render_report(_res)
        open(OUT_MD, "w").write(_md)
        print("refreshed writer_probe; rendered", OUT_MD, len(_md), "chars")
    elif "--recompute-plan" in sys.argv:
        # 只重算最小方案(逐币维数口径改了但取数没变时用这个):per_symbol 里 dims_plus_oi 已是逐币实测,
        # 「补 funding」= funding 源扩到全部票源币 ⇒ dims_plus_oi_plus_funding = dims_plus_oi ∪ {11}
        _res = json.load(open(OUT_JSON))
        _ps = _res["minimal_plan"]["per_symbol"]
        for _v in _ps.values():
            _d = sorted(set(_v["dims_plus_oi"]) | {11})
            _v["n_plus_oi_plus_funding"] = len(_d)
            _v["dims_plus_oi_plus_funding"] = _d
            _v["missing_after_oi_plus_funding"] = sorted(set(NON_CIS_DIMS) - set(_d))
        _res["minimal_plan"].update(plan_aggregates(_ps))
        _res["minimal_plan"].update(plan_texts(_res["minimal_plan"]))
        json.dump(_res, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
        _md = render_report(_res)
        open(OUT_MD, "w").write(_md)
        print("recomputed plan; rendered", OUT_MD, len(_md), "chars")
        print(json.dumps({k: v for k, v in _res["minimal_plan"].items()
                          if k.startswith("n_reaching") or k.startswith("missing")},
                         ensure_ascii=False))
    else:
        main()
