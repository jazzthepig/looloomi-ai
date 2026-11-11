"""T-337 探针 v2:(a) macro_daily 的 btc_mvrv / btc_issuance_usd / fng 覆盖区间与行数(卡上开工前置条件);
(b) closes(现货 binance_hist + 永续 perp_bv_daily 覆盖)里的异常跳变 —— 解释 HOT/TWOWAY 臂 max_dd ≈ −108%。"""
import os
import sys
import json
import urllib.request
from pathlib import Path

CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t337")
U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]


def q(path):
    h = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
    r = urllib.request.Request(U + "/rest/v1/" + path, headers=h)
    with urllib.request.urlopen(r, timeout=120) as f:
        return f.headers.get("Content-Range"), json.loads(f.read().decode())


def count_series(s):
    lo, n, first, last = 0, 0, None, None
    while True:
        cr, rows = q("macro_daily?select=d&series=eq." + s + "&order=d.asc&limit=1000&offset=" + str(lo))
        if not rows:
            break
        if first is None:
            first = rows[0]["d"]
        last = rows[-1]["d"]
        n += len(rows)
        lo += len(rows)
        if len(rows) < 1000:
            break
    return n, first, last, cr


print("=== (a) macro_daily 覆盖 ===")
for s in ["btc_mvrv", "btc_issuance_usd", "btc_hashrate", "fng"]:
    n, first, last, cr = count_series(s)
    print(s, "| rows:", n, "| first:", first, "| last:", last, "| range:", cr)
    sys.stdout.flush()

perp = json.loads((CACHE / "perp_btc.json").read_text())
spot = json.loads((CACHE / "ohlcv_btc_binance_hist.json").read_text())
pclose = {}
for r in perp:
    if r.get("c") is None:
        continue
    pclose[str(r["d"])[:10]] = float(r["c"])
sclose = {}
for r in spot:
    if r.get("close") is None:
        continue
    sclose[str(r["trade_date"])[:10]] = float(r["close"])

closes = dict(sclose)
closes.update(pclose)
days = sorted(d for d in closes if "2018-02-01" <= d <= "2026-10-31")
print()
print("=== (b) 价格序列 ===")
print("days", len(days), days[0], days[-1], "| perp rows", len(pclose),
      min(pclose), max(pclose), "| spot rows", len(sclose), min(sclose), max(sclose))
print("perp 值域", min(pclose.values()), max(pclose.values()))
rets = []
for i in range(1, len(days)):
    a, b = closes[days[i - 1]], closes[days[i]]
    if a > 0:
        rets.append((abs(b / a - 1.0), days[i], a, b))
rets.sort(reverse=True)
print("--- 最大单日跳变 top 10 ---")
for r in rets[:10]:
    print("  %s %.3f -> %.3f (%+.1f%%)" % (r[1], r[2], r[3], (r[3] / r[2] - 1) * 100))
both = sorted(set(pclose) & set(sclose))
dev = sorted(((abs(pclose[d] / sclose[d] - 1.0), d) for d in both), reverse=True)
print("--- 永续/现货偏离 top 6 ---")
for v, d in dev[:6]:
    print("  %s perp %.2f spot %.2f (%+.2f%%)" % (d, pclose[d], sclose[d], (pclose[d] / sclose[d] - 1) * 100))
pd = sorted(pclose)
gaps = []
for i in range(len(pd) - 1):
    a, b = pd[i], pd[i + 1]
    g = (int(b[:4]) - int(a[:4])) * 365 + int(b[5:7]) - int(a[5:7])
    gaps.append((g, b))
gaps.sort(reverse=True)
print("--- 永续最大日期间隔 top 5 ---")
for g, d in gaps[:5]:
    print("  →", d, g, "天")

print()
print("=== (c) 永续日 bar 的日期对齐(检验「+8h」假设)===")
sd = sorted(sclose)
e0, e1, n = 0.0, 0.0, 0
for d in both:
    if d in sclose:
        e0 += abs(pclose[d] / sclose[d] - 1.0)
        n += 1
    nxt = sd[sd.index(d) + 1] if sd.index(d) + 1 < len(sd) else None
    if nxt:
        e1 += abs(pclose[d] / sclose[nxt] - 1.0)
print("mean |perp[d]/spot[d]   − 1| = %.5f" % (e0 / n))
print("mean |perp[d]/spot[d+1] − 1| = %.5f" % (e1 / n))
print("→ 第一个更小 ⇒ 永续 bar d 装的就是 UTC 第 d 天的收盘(无 +8h 偏移)" if e0 < e1
      else "→ 第二个更小 ⇒ 永续 bar d 装的是下一根 UTC 日线(≈+8h 对齐)")
for d in ["2021-04-12", "2021-04-13", "2021-04-14", "2021-04-15", "2021-01-20", "2021-01-21"]:
    nxt = sd[sd.index(d) + 1] if d in sd and sd.index(d) + 1 < len(sd) else None
    print("  %s perp %s | spot[d] %s | spot[d+1] %s"
          % (d, ("%.1f" % pclose[d]) if d in pclose else "n/a",
             ("%.1f" % sclose[d]) if d in sclose else "n/a",
             ("%.1f" % sclose[nxt]) if nxt else "n/a"))

print()
print("=== (d) 前向基准率(给 scenarios 的 prob 用)===")
fng_rows = json.loads((CACHE / "macro_fng.json").read_text())
fng = {}
for r in fng_rows:
    if r.get("value") is None:
        continue
    fng[str(r["d"])[:10]] = float(r["value"])
fd = sorted(fng)
print("fng rows", len(fng), fd[0], fd[-1], "| 最新 5 个:", [(d, fng[d]) for d in fd[-5:]])
print("BTC 最新收盘(现货):", sd[-1], "%.2f" % sclose[sd[-1]])
# 50 日前瞻收益为正的比例
H = 50
win = [d for d in sd if d >= "2018-02-01" and d <= "2026-10-31"]
pairs = [(win[i], win[i + H]) for i in range(len(win) - H) if win[i + H] in sclose]
pos = sum(1 for a, b in pairs if sclose[b] > sclose[a])
print("50 日前瞻收益为正:%d / %d = %.4f(样本 %s→%s)" % (pos, len(pairs), pos / len(pairs), pairs[0][0], pairs[-1][1]))
# fng 分布
print("fng < 60 的日占比: %.4f" % (sum(1 for d in fd if fng[d] < 60) / len(fd)))
print("fng ≤ 10 的日占比: %.4f" % (sum(1 for d in fd if fng[d] <= 10) / len(fd)))
# 50 日窗内出现过 fng ≥ 95 的比例
w95 = sum(1 for i in range(len(fd) - H) if any(fng[d] >= 95 for d in fd[i:i + H]))
print("50 日窗内出现过 fng ≥ 95 的比例: %d / %d = %.4f" % (w95, len(fd) - H, w95 / (len(fd) - H)))
w10 = sum(1 for i in range(len(fd) - H) if any(fng[d] <= 10 for d in fd[i:i + H]))
print("50 日窗内出现过 fng ≤ 10 的比例: %d / %d = %.4f" % (w10, len(fd) - H, w10 / (len(fd) - H)))
# 最近一次 fng ≥ 95 / ≤ 10 到今天有多久
last95 = max(d for d in fd if fng[d] >= 95)
last10 = max(d for d in fd if fng[d] <= 10)
print("最后一次 fng ≥ 95:", last95, "| 最后一次 fng ≤ 10:", last10, "| 距今(2026-11-11)天数:",
      (__import__("datetime").date(2026, 11, 11) - __import__("datetime").date.fromisoformat(last95)).days,
      (__import__("datetime").date(2026, 11, 11) - __import__("datetime").date.fromisoformat(last10)).days)
# fng 未来 50 天的历史同月分布:11-12 → 12-31 的 fng 落在哪些区间
hist = [fng[d] for d in fd if d[5:7] in ("11", "12") and "2018" <= d[:4] <= "2025"]
print("历年 11-12 月 fng: n=%d 中位 %.1f, <60 占比 %.3f, ≤10 占比 %.3f"
      % (len(hist), sorted(hist)[len(hist) // 2],
         sum(1 for v in hist if v < 60) / len(hist), sum(1 for v in hist if v <= 10) / len(hist)))
for lo, hi in [(0, 25), (25, 60), (60, 85), (85, 101)]:
    a = sum(1 for d in fd if lo <= fng[d] < hi) / len(fd)
    b = sum(1 for v in hist if lo <= v < hi) / len(hist)
    print("  fng ∈ [%d,%d): 全样本 %.4f | 历年 11-12 月 %.4f" % (lo, hi, a, b))


