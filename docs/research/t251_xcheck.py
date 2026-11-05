"""T-251 口径核对:
① S-730 的 validated universe(perp_bv_pairs ∩ binance_hist 面板)与本脚本用的 257 符号的差集;
② r_money_daily(内核写的钱曲线)的 f / cap / gross÷nav 分布 —— 独立交叉验证「40% 档会不会被触发」;
③ r_tickets_paper 的票源概况。
只读;输出紧凑 JSON。
"""
import json
import os
import sys
import urllib.error
import urllib.request

U = os.environ["SUPABASE_URL"].rstrip("/")
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}


def rest(path, rng="0-999", extra=None):
    h = dict(H)
    h["Range"] = rng
    if extra:
        h.update(extra)
    r = urllib.request.Request(U + "/rest/v1/" + path, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read()), resp.headers.get("Content-Range")
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return [], None
        raise RuntimeError(f"HTTP {e.code} on {path[:120]}: {e.read()[:200].decode('utf8','replace')}") from None


def page_all(path, order):
    out, off = [], 0
    while True:
        q = path + f"&order={order}"
        rows, _ = rest(q, f"{off}-{off+999}")
        if not rows:
            break
        out += rows
        off += 1000
        if len(rows) < 1000:
            break
    return out


def cursor_symbols(table, where=""):
    syms, last = [], ""
    while True:
        q = f"{table}?select=symbol{where}&order=symbol.asc&symbol=gt.{last}"
        rows, _ = rest(q, "0-0")
        if not rows:
            break
        s = rows[0]["symbol"]
        if s in syms:
            break
        syms.append(s)
        last = s
    return syms


out = {}

# ---- ① validated universe(S-730 口径)
pairs = page_all("perp_bv_pairs?select=symbol,kind,dead_from", "symbol.asc")
panel = set(cursor_symbols("ohlcv_daily", "&source=eq.binance_hist"))
uni_s730 = set()
for p in pairs:
    sym = p.get("symbol")
    if sym in ("USDC", "BTCDOM", "DEFI"):
        continue
    kind, dead = p.get("kind"), p.get("dead_from")
    if (kind == "coin") or (kind is None and dead is not None):
        if sym in panel:
            uni_s730.add(sym)
out["s730_universe_n"] = len(uni_s730)

local = set(json.load(open(os.path.join(os.path.dirname(__file__), "t251_results.json")))["universe"])
out["local_universe_n"] = len(local)
out["local_minus_s730"] = sorted(local - uni_s730)
out["s730_minus_local"] = sorted(uni_s730 - local)
out["pairs_rows"] = len(pairs)
out["panel_symbols_n"] = len(panel)

# ---- ② r_money_daily(内核钱曲线)
money = page_all("r_money_daily?select=d,nav,gross,taken,skipped,closed,open_n,f,cap,rule_version", "d.asc")
out["money_rows"] = len(money)
if money:
    out["money_range"] = [money[0]["d"], money[-1]["d"]]
    out["money_f"] = sorted({m["f"] for m in money})
    out["money_cap"] = sorted({m["cap"] for m in money})
    out["money_rule_version"] = sorted({m["rule_version"] for m in money})
    ratios = [(m["gross"] / m["nav"]) for m in money if m.get("gross") is not None and m.get("nav")]
    ratios.sort()
    if ratios:
        out["money_gross_over_nav"] = {
            "n": len(ratios),
            "max": ratios[-1],
            "p99": ratios[int(0.99 * (len(ratios) - 1))],
            "p95": ratios[int(0.95 * (len(ratios) - 1))],
            "median": ratios[len(ratios) // 2],
        }
    out["money_taken_total"] = sum(m.get("taken") or 0 for m in money)
    out["money_skipped_total"] = sum(m.get("skipped") or 0 for m in money)
    out["money_closed_total"] = sum(m.get("closed") or 0 for m in money)

# ---- ③ r_tickets_paper 概况
tp = page_all("r_tickets_paper?select=symbol,signal_d,status", "signal_d.asc,symbol.asc")
out["r_tickets_paper_rows"] = len(tp)
if tp:
    out["r_tickets_paper_range"] = [tp[0]["signal_d"], tp[-1]["signal_d"]]
    st = {}
    for t in tp:
        st[t.get("status")] = st.get(t.get("status"), 0) + 1
    out["r_tickets_paper_status"] = st
    out["r_tickets_paper_symbols"] = len({t["symbol"] for t in tp})

# ---- ④ style_index_pit_daily 的 style/weighting 组合(确认 gate 口径)
st_rows = page_all("style_index_pit_daily?select=style,weighting&order=d.asc", "d.asc")
combos = sorted({f"{r['style']}|{r['weighting']}" for r in st_rows})
out["style_combos"] = combos
out["style_rows"] = len(st_rows)

print(json.dumps(out, ensure_ascii=False, indent=1))
