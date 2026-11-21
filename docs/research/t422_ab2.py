"""T-422 的 ①:A 路(CG 口径)vs B 路(兜底口径)的差表 —— 2026-11-19。

三层:
  A_pub  = `cis_official_daily` 里 11-19 的**已发布官方档**(真值:当时的 live CG 锚)
  A_rep  = 用同一份输入重跑,四维走 **CG 口径**(asset_mcap_daily 的 price/mcap/volume)
  B_rep  = 用同一份输入重跑,四维走 **兜底口径**(Binance 收盘 + 流通量×价 + 币量×价)

于是:
  Δ口径(四维) = A_rep − B_rep   ← 纯净:只有价/市值/成交/chg30 不同
  Δ其余      = A_pub − A_rep   ← 含 static(CG live 的 total/max_supply)与本机环境差
                (github / chain_activity / equity_fundamentals 三张表本机 401 ⇒ 两路都没有)

只读。不写库。不外呼。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import pandas as pd

ROOT = pathlib.Path("/Users/sbb/Projects/looloomi-ai-lane-b")
sys.path.insert(0, str(ROOT))

from src.data.cis.rebuild import LEVELS, TRADFI, pct_level, score_day  # noqa: E402
from src.data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS  # noqa: E402

D = pd.Timestamp("2026-11-19")
FROM = "2026-09-20"           # 61 天:change_30d 需要 30 天前,ath 需要窗口最大
OUT = pathlib.Path("/Volumes/CometCloudAI/cometcloud-local/research/t422")

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def _get(table: str, qs: str, limit: int = 1000, offset: int = 0):
    req = urllib.request.Request(
        f"{URL}/rest/v1/{table}?{qs}&limit={limit}&offset={offset}",
        headers={**H, "Prefer": "count=exact"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers.get("Content-Range"), json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode()[:220]
    except Exception as e:  # noqa: BLE001
        return -1, None, str(e)[:220]


def fetch(table: str, qs: str, label: str) -> list[dict]:
    """分页取全(每页 ≤1000,带 order),并核总行数。"""
    rows: list[dict] = []
    off = 0
    total = None
    while True:
        st, cr, body = _get(table, qs, limit=1000, offset=off)
        if st not in (200, 206):
            raise RuntimeError(f"{label}: status={st} {str(body)[:200]}")
        if total is None and cr:
            total = int(cr.split("/")[-1])
        rows.extend(body)
        if len(body) < 1000:
            break
        off += 1000
        if off > 400000:
            break
    print(f"  {label:34s} rows={len(rows):6d} total={total}")
    if total is not None and len(rows) != total:
        raise RuntimeError(f"{label}: 抓取行数 {len(rows)} != 表内 {total}(分页漂了)")
    return rows


def _series(rows: list[dict], key: str, val: str, kv: str) -> pd.Series:
    """key=过滤列(coin_id/symbol),val=值列;日期列自动选 d / trade_date。"""
    dcol = "d" if rows and "d" in rows[0] else "trade_date"
    xs = [(pd.Timestamp(str(r[dcol])[:10]), r[val])
          for r in rows if r.get(key) == kv and r.get(val) is not None]
    if not xs:
        return pd.Series(dtype=float)
    return pd.Series(dict(xs), dtype=float).sort_index()


def main() -> None:
    crypto_syms = [s for s, v in ASSETS_CONFIG.items() if v["class"] not in TRADFI]
    tf_syms = [s for s, v in ASSETS_CONFIG.items() if v["class"] in TRADFI]
    sym2cg = {s: CRYPTO_ASSETS[s].get("coingecko") for s in crypto_syms if CRYPTO_ASSETS.get(s, {}).get("coingecko")}
    cg_ids = sorted(set(sym2cg.values()))
    print(f"加密名 {len(crypto_syms)} / 传统 {len(tf_syms)} / CG id {len(cg_ids)}")

    in_crypto = ",".join(crypto_syms)
    in_tf = ",".join(tf_syms)
    in_cg = ",".join(cg_ids)

    print("读库:")
    a_pub = fetch("cis_official_daily", f"select=*&d=eq.{D.date()}&order=symbol.asc", "A_pub 已发布官方档")
    a_pub_18 = fetch("cis_official_daily", f"select=*&d=eq.2026-11-18&order=symbol.asc", "A_pub 11-18(分位参照)")
    px_rows = fetch("ohlcv_daily", f"select=symbol,trade_date,close,high,low,volume&source=eq.binance_hist"
                                   f"&symbol=in.({in_crypto})&trade_date=gte.{FROM}&order=symbol.asc,trade_date.asc",
                    "Binance 日线(加密)")
    tf_rows = fetch("ohlcv_daily", f"select=symbol,trade_date,close,high,low,volume&source=eq.eodhd"
                                   f"&symbol=in.({in_tf})&trade_date=gte.{FROM}&order=symbol.asc,trade_date.asc",
                    "EODHD 日线(传统)")
    supply_rows = fetch("coin_supply_daily", f"select=coin_id,d,total_supply,circulating_supply&d=gte.{FROM}"
                                             f"&order=coin_id.asc,d.asc", "coin_supply_daily")
    cg_rows = fetch("asset_mcap_daily", f"select=coin_id,d,price,mcap,volume&source=eq.coingecko_pro_market_chart"
                                        f"&coin_id=in.({in_cg})&d=gte.{FROM}&order=coin_id.asc,d.asc",
                    "A 路 CG 市值/价/成交")

    pub = {r["symbol"]: r for r in a_pub}
    pub18 = {r["symbol"]: r for r in a_pub_18}

    # ── 供给量(两路共用):PIT —— 取每个名字最后一个 ≤ D 的快照 ──────────────────
    sup_by_cg: dict[str, dict] = {}
    for r in supply_rows:
        sup_by_cg.setdefault(r["coin_id"], {})[pd.Timestamp(str(r["d"])[:10])] = (
            r.get("circulating_supply"), r.get("total_supply"))

    def _pit(cg_id: str):
        days = sorted(sup_by_cg.get(cg_id, {}))
        prior = [d for d in days if d <= D]
        if not prior:
            return None, None, None
        d = prior[-1]
        circ, tot = sup_by_cg[cg_id][d]
        return (float(circ) if circ is not None else None,
                float(tot) if tot is not None else None, d)

    # ── 两套 crypto 四维 ────────────────────────────────────────────────────────
    bin_px = {s: _series(px_rows, "symbol", "close", s) for s in crypto_syms}
    bin_hi = {s: _series(px_rows, "symbol", "high", s) for s in crypto_syms}
    bin_lo = {s: _series(px_rows, "symbol", "low", s) for s in crypto_syms}
    bin_vol = {s: _series(px_rows, "symbol", "volume", s) for s in crypto_syms}
    cg_px = {s: _series(cg_rows, "coin_id", "price", sym2cg[s]) for s in crypto_syms if s in sym2cg}
    cg_mc = {s: _series(cg_rows, "coin_id", "mcap", sym2cg[s]) for s in crypto_syms if s in sym2cg}
    cg_vol = {s: _series(cg_rows, "coin_id", "volume", sym2cg[s]) for s in crypto_syms if s in sym2cg}

    def build_crypto(fb: bool, vol_from_cg: bool = False):
        out = {}
        for s in crypto_syms:
            circ, tot, asof = _pit(sym2cg.get(s) or "")
            if fb:
                px = bin_px[s]
                mc = (circ * px) if circ is not None else pd.Series(dtype=float)
                vol = (cg_vol.get(s, pd.Series(dtype=float)) if vol_from_cg else (bin_vol[s] * px))
            else:
                px, mc, vol = cg_px.get(s, pd.Series(dtype=float)), cg_mc.get(s, pd.Series(dtype=float)), \
                    cg_vol.get(s, pd.Series(dtype=float))
            out[s] = (px, mc, vol, bin_hi[s], bin_lo[s])
        return out

    # ── 共同输入:macro / funding / tvl / static_tf 全部从 A_pub 反推 ──────────────
    btc_pub = pub.get("BTC") or {}
    btc_in = btc_pub.get("inputs") or {}
    btc_dom = btc_in.get("btc_dom")
    tot_mcap = (float(btc_in["mcap"]) / (float(btc_dom) / 100.0)
                if btc_in.get("mcap") and btc_dom else None)
    fng = next((r["inputs"].get("fng") for r in a_pub if (r.get("inputs") or {}).get("fng") is not None), None)
    vix = next((r["inputs"].get("vix") for r in a_pub if (r.get("inputs") or {}).get("vix") is not None), None)
    print(f"  反推 macro: fng={fng} vix={vix} btc_dom={btc_dom} total_mcap={tot_mcap}")

    macro = {"fng": {D: fng} if fng is not None else {},
             "vix": {D: vix} if vix is not None else {},
             "total_mcap": {D: tot_mcap} if tot_mcap is not None else {}}

    funding: dict[str, dict] = {}
    for r in a_pub:
        fr = (r.get("inputs") or {}).get("funding")
        if fr is not None:
            funding[r["symbol"]] = {D: float(fr)}

    tvl: dict[str, dict] = {}
    for r in a_pub:
        tv = (r.get("inputs") or {}).get("tvl")
        if tv is not None:
            tvl[r["symbol"]] = {D: float(tv)}

    static_tf: dict[str, dict] = {}
    for r in a_pub:
        i = r.get("inputs") or {}
        if i.get("mcap") and i.get("price") and r["asset_class"] in TRADFI:
            static_tf[r["symbol"]] = {"market_cap": float(i["mcap"]), "price": float(i["price"])}

    def build_static():
        out = {}
        for s in crypto_syms:
            _, tot, asof = _pit(sym2cg.get(s) or "")
            out[s] = {"total_supply": tot, "max_supply": None, "_asof": str(asof.date()) if asof is not None else None}
        return out

    tradfi = {}
    for s in tf_syms:
        tradfi[s] = (_series(tf_rows, "symbol", "close", s), _series(tf_rows, "symbol", "high", s),
                     _series(tf_rows, "symbol", "low", s), _series(tf_rows, "symbol", "volume", s))

    assets = {k: {"class": v["class"], "coingecko": v.get("coingecko")} for k, v in ASSETS_CONFIG.items()}

    def run(fb: bool, vol_from_cg: bool = False):
        data = {"crypto": build_crypto(fb, vol_from_cg), "tradfi": tradfi, "tvl": tvl, "macro": macro,
                "funding": funding, "static": build_static(), "static_tf": static_tf,
                "fundamentals": {}, "github": {}, "migration_eff": {}}
        return score_day(D, assets, data)

    rows_a = run(False)
    rows_b = run(True)
    rows_c = run(True, vol_from_cg=True)      # 第三路:兜底价/市值 + CG 成交量 ⇒ 归因
    print(f"重跑: A_rep {len(rows_a)} 行 / B_rep {len(rows_b)} 行 / C_rep {len(rows_c)} 行")

    a_map = {r["symbol"]: r for r in rows_a}
    b_map = {r["symbol"]: r for r in rows_b}
    c_map = {r["symbol"]: r for r in rows_c}

    def pct_of(rows: list[dict]) -> dict:
        """同组当日分位(与 group_pct 同口径:按 score 排,≥5 个名字才排)。"""
        from src.data.cis.rebuild import group_pct
        group_pct(rows)
        return {r["symbol"]: r.get("pct") for r in rows}

    pct_a = pct_of(rows_a)
    pct_b = pct_of(rows_b)

    diffs = []
    for sym in sorted(set(pub) | set(a_map) | set(b_map)):
        p, a, b = pub.get(sym), a_map.get(sym), b_map.get(sym)
        c = c_map.get(sym)
        if not (p and a and b):
            continue
        diffs.append({
            "symbol": sym,
            "asset_class": p.get("asset_class"),
            "pub_cis_score": p.get("cis_score"),
            "pub_score": p.get("regime_adjusted_score"),
            "pub_grade": p.get("grade"),
            "pub_signal": p.get("signal"),
            "pub_pct": p.get("pct"),
            "pub_regime": p.get("regime"),
            "pub_miss": (p.get("inputs") or {}).get("missing") or p.get("missing"),
            "A_score": a.get("score"), "A_raw": a.get("raw_score"), "A_grade": a.get("grade"),
            "A_regime": a.get("regime"), "A_pct": pct_a.get(sym), "A_miss": a.get("missing"),
            "A_price": (a.get("inputs") or {}).get("price"), "A_mcap": (a.get("inputs") or {}).get("mcap"),
            "A_volume": (a.get("inputs") or {}).get("volume"), "A_chg30": (a.get("inputs") or {}).get("chg30"),
            "A_pillars": {k: a.get(f"pillar_{k}") for k in "fmosa"},
            "B_score": b.get("score"), "B_raw": b.get("raw_score"), "B_grade": b.get("grade"),
            "B_regime": b.get("regime"), "B_pct": pct_b.get(sym), "B_miss": b.get("missing"),
            "B_price": (b.get("inputs") or {}).get("price"), "B_mcap": (b.get("inputs") or {}).get("mcap"),
            "B_volume": (b.get("inputs") or {}).get("volume"), "B_chg30": (b.get("inputs") or {}).get("chg30"),
            "B_pillars": {k: b.get(f"pillar_{k}") for k in "fmosa"},
            "C_raw": (c or {}).get("raw_score"), "C_score": (c or {}).get("score"),
            "C_pillars": {k: (c or {}).get(f"pillar_{k}") for k in "fmosa"},
        })

    # 四维差(A_rep − B_rep)
    for d in diffs:
        d["d_score_4d"] = round((d["A_score"] or 0) - (d["B_score"] or 0), 3)
        d["d_raw_4d"] = round((d["A_raw"] or 0) - (d["B_raw"] or 0), 3)
        d["d_pct_4d"] = round((d["A_pct"] or 0) - (d["B_pct"] or 0), 4)
        d["d_score_vs_pub"] = round((d["B_score"] or 0) - (d["pub_score"] or 0), 3)
        d["d_raw_vs_pub"] = round((d["B_raw"] or 0) - (d["pub_cis_score"] or 0), 3)
        d["grade_same"] = (d["pub_grade"] == d["B_grade"])
        d["regime_same"] = (d["pub_regime"] == d["B_regime"])
        # 档位:正式档位是**滞回**档(需要 2023 起的历史分位序列 + 三张本机 401 的表)⇒ 本机不可复算。
        # 这里比的是**同一口径**:同组当日分位档位(pct_level,同 rebuild.PCT_CUTS)。
        d["pctband_pub"] = pct_level(d["pub_pct"]) if d["pub_pct"] is not None else None
        d["pctband_A"] = pct_level(d["A_pct"]) if d["A_pct"] is not None else None
        d["pctband_B"] = pct_level(d["B_pct"]) if d["B_pct"] is not None else None
        d["pctband_same"] = (d["pctband_pub"] == d["pctband_B"])
        d["pctband_same_4d"] = (d["pctband_A"] == d["pctband_B"])
        d["px_rel_diff_pct"] = (round((d["B_price"] / d["A_price"] - 1) * 100, 4)
                                if d["A_price"] and d["B_price"] else None)
        d["mcap_rel_diff_pct"] = (round((d["B_mcap"] / d["A_mcap"] - 1) * 100, 4)
                                  if d["A_mcap"] and d["B_mcap"] else None)
        for k in "fmosa":
            a_v, b_v = d["A_pillars"].get(k), d["B_pillars"].get(k)
            d[f"d_pillar_{k}"] = round((a_v or 0) - (b_v or 0), 3)
        d["d_raw_vol_only"] = round((d["A_raw"] or 0) - (d["C_raw"] or 0), 3)
        d["d_score_vol_only"] = round((d["A_score"] or 0) - (d["C_score"] or 0), 3)
        d["d_pillar_m_vol_only"] = round((d["A_pillars"].get("m") or 0) - (d["C_pillars"].get("m") or 0), 3)

    crypto_rows = [d for d in diffs if d["asset_class"] not in TRADFI]
    tf_rows_out = [d for d in diffs if d["asset_class"] in TRADFI]

    def stat(rows, key):
        xs = [r[key] for r in rows if r.get(key) is not None]
        if not xs:
            return None
        xs_s = sorted(xs)
        n = len(xs_s)
        return {"n": n, "max": round(max(xs), 3), "min": round(min(xs), 3),
                "mean": round(sum(xs) / n, 3), "median": round(xs_s[n // 2] if n % 2 else
                                                             (xs_s[n // 2 - 1] + xs_s[n // 2]) / 2, 3)}

    summary = {
        "d": str(D.date()),
        "universe": {"crypto": len(crypto_rows), "tradfi": len(tf_rows_out)},
        "口径差_A_rep_vs_B_rep(仅价/市值/成交/chg30)": {
            "Δscore": stat(crypto_rows, "d_score_4d"), "Δraw": stat(crypto_rows, "d_raw_4d"),
            "Δpct": stat(crypto_rows, "d_pct_4d"),
        },
        "兜底_vs_已发布官方档": {
            "Δscore": stat(crypto_rows, "d_score_vs_pub"), "Δraw": stat(crypto_rows, "d_raw_vs_pub"),
            "等级变了": sum(1 for r in crypto_rows if not r["grade_same"]),
            "档位变了(当日分位档,非滞回档)": sum(1 for r in crypto_rows if not r["pctband_same"]),
            "档位变了(仅四维口径差)": sum(1 for r in crypto_rows if not r["pctband_same_4d"]),
            "regime 变了": sum(1 for r in crypto_rows if not r["regime_same"]),
            "regime 标签": {"pub": sorted({r["pub_regime"] for r in crypto_rows}),
                            "B": sorted({r["B_regime"] for r in crypto_rows}),
                            "A": sorted({r["A_regime"] for r in crypto_rows})},
        },
        "tradfi_对照": {
            "Δscore": stat(tf_rows_out, "d_score_4d"),
            "等级变了": sum(1 for r in tf_rows_out if not r["grade_same"]),
        },
        "两路行数差": {
            "A_rep 有 B_rep 没有": sorted(set(a_map) - set(b_map)),
            "B_rep 有 A_rep 没有": sorted(set(b_map) - set(a_map)),
        },
        "pillar差(A_rep − B_rep,仅四维口径差)": {
            k: stat(crypto_rows, f"d_pillar_{k}") for k in "fmosa"
        },
        "归因(兜底价/市值 + CG 成交,只差成交量)": {
            "Δraw(A_rep − C_rep)": stat(crypto_rows, "d_raw_vol_only"),
            "Δscore(A_rep − C_rep)": stat(crypto_rows, "d_score_vol_only"),
            "Δpillar_M(A_rep − C_rep)": stat(crypto_rows, "d_pillar_m_vol_only"),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ab_table.json").write_text(json.dumps({"summary": summary, "rows": diffs},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "ab_rows.json").write_text(json.dumps(diffs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
