"""T-289 读数打印:只打要核对的那几格,不整读 results.json。
用法: python3 docs/research/t289_show.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "t289_results.json")
if not os.path.exists(P):
    print("NO RESULTS FILE:", P)
    sys.exit(1)
R = json.load(open(P))
res = R.get("results", R)


def med(block, hk="full"):
    b = block.get(hk, {}) or {}
    ex = b.get("excess", {}) or {}
    return ex.get("median"), ex.get("n")


def line(tag, v):
    print("%-46s %s" % (tag, v))


print("=== ① squeeze:原口径 wo=0 / 挪一天 wo=1 ===")
for H in ("1", "7", "30"):
    for wo in ("0", "1"):
        b = res["squeeze"].get(H, {}).get(wo, {})
        n = (b.get("null", {}) or {}).get("full", {}) or {}
        m, nn = med(b)
        line("H=%s wo=%s median/n" % (H, wo), "%.4f (n=%s)" % (m if m is not None else float("nan"), nn))
        line("  H=%s wo=%s null_pctl / null_med" % (H, wo),
             "%s / %s" % (n.get("null_median_pctl"), n.get("null_median_median")))
for H in ("1", "7", "30"):
    for wo in ("0", "1"):
        b = res["squeeze"].get(H, {}).get(wo, {})
        for hk in ("H1", "H2"):
            m, nn = med(b, hk)
            line("  halves H=%s wo=%s %s" % (H, wo, hk),
                 "%.4f (n=%s)" % (m if m is not None else float("nan"), nn))

print("=== ①b flush(对照) ===")
for H in ("1", "7", "30"):
    for wo in ("0", "1"):
        b = res["flush"].get(H, {}).get(wo, {})
        n = (b.get("null", {}) or {}).get("full", {}) or {}
        m, nn = med(b)
        line("flush H=%s wo=%s median/n" % (H, wo),
             "%.4f (n=%s) pctl=%s" % (m if m is not None else float("nan"), nn, n.get("null_median_pctl")))

print("=== ② OI 两组 ===")
of = R.get("oi_fetch", {})
line("oi_fetch", {k: of.get(k) for k in ("symbols", "queries", "rows")})
line("oi_fetch no_oi_syms", len(of.get("no_oi_syms", []) or []))
for nm in ("squeeze", "flush"):
    for wo in ("0", "1"):
        o = (R.get("oi_sub", {}) or {}).get(nm, {}).get(wo, {})
        if not o:
            continue
        d10 = o.get("down10_excess", {}) or {}
        ot = o.get("other_excess", {}) or {}
        line("%s wo=%s n_oi / down10 / other" % (nm, wo),
             "%s / %s / %s" % (o.get("n_with_oi"), o.get("n_oi_down_10"), o.get("n_other")))
        line("  %s wo=%s down10 med / other med" % (nm, wo),
             "%s (n=%s) / %s (n=%s)" % (d10.get("median"), d10.get("n"),
                                        ot.get("median"), ot.get("n")))

print("=== ③ R-v2 回放 ===")
rv = R.get("rv2", {})
for k in ("source", "n_tickets", "n_blocked", "n_rest", "blocked_mean_r",
          "rest_mean_r", "blocked_mean_r_all", "n_closed"):
    if k in rv:
        line("rv2." + k, rv[k])
bb = rv.get("block_boot", {})
if bb:
    line("rv2.block_boot", {k: bb.get(k) for k in (
        "n_closed", "n_blocked", "draws", "seed", "observed_blocked_minus_rest",
        "null_median", "p_le_0")})
bk = rv.get("book", {})
if "error" in bk:
    line("rv2.book", bk["error"])
else:
    line("book n_full / n_rule", "%s / %s" % (bk.get("n_full"), bk.get("n_rule")))
    line("book nav_to / f / cap", "%s / %s / %s" % (bk.get("nav_to"), bk.get("f"), bk.get("cap")))
    for who in ("full", "rule_S"):
        s = bk.get(who, {}) or {}
        line("  book %s" % who, {k: s.get(k) for k in ("end", "mdd", "sharpe", "n", "ret")})
    line("  rule_S_R_not_lower", bk.get("rule_S_R_not_lower"))
    line("  rule_S_mdd_not_worse", bk.get("rule_S_mdd_not_worse"))
for hk, h in (rv.get("book_halves", {}) or {}).items():
    line("  halves %s" % hk, "n_full=%s n_rule=%s" % (h.get("n_full"), h.get("n_rule")))
    for who in ("full", "rule_S"):
        s = h.get(who, {}) or {}
        line("    %s %s" % (hk, who), {k: s.get(k) for k in ("end", "mdd", "sharpe")})

print("=== 判定 ===")
line("verdict_s768", json.dumps(R.get("verdict_s768", {}), ensure_ascii=False))
line("registration", json.dumps(R.get("registration", {}), ensure_ascii=False))
print("=== 事件 ===")
line("events", json.dumps(R.get("events", {}), ensure_ascii=False))
line("concentration", json.dumps(R.get("concentration", {}), ensure_ascii=False))
line("selfcheck", json.dumps(R.get("selfcheck", {}), ensure_ascii=False)[:600])
