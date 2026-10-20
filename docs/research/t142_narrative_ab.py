#!/usr/bin/env python3
"""T-142 / S-626 — 叙事标记前向 A/B 评分器。

每周按时点冻结 J / E / T / N 四臂名单到 research/narrative_flags/frozen/YYYY-Www.json;
对已到期(Mon + 60 天 ≤ 今日)的周算「快鱼率」与「早不早」指标。

口径(S-626 预注册,REFUTATION_LEDGER 29159–65):
  J = cometcloud-local/research/narrative_flags/YYYY-Www.json 中 themes[].symbols
      (status ≠ awaiting_jazz 才算;改了就是新一周)
  E = Mon 前 7 天 narrative_events.related_assets 计数前 10(去 BTC / ETH)
  T = Mon 前 7 天 trending_log.symbol 计数前 10(去 BTC / ETH)
  N = 当周 binance_hist 宇宙(rn ≥ 220,30 日均成交额(close×volume)≥ 500 万美元)中
      没被任何臂标记的名字。
  快鱼 = 周一收盘后 60 天内最高收盘 ≥ 2 × 周一收盘(只报大鱼 S-618 120 天 3 倍)。
  早不早 = 快鱼首次触发日 k(0..K-1),报中位 k 中位数(越小越早)。
  判:J 满 ≥ 12 周且最后一笔 60 天结果到期后,周内打乱「标 / 不标」2,000 次,
      单侧 p < 0.05(J > N)。当前 N = 0,J 的判据未到。

读库:仅用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'];不读 .env、不打印 key。

输出:
  research/narrative_flags/frozen/YYYY-Www.json — 当周冻结名单(append-only)
  research/narrative_flags/_t142_state.json     — 全周累计状态(只为幂等)
  数据根 _reports/absorb_input/T-142_narrative_ab.md — 周报(汇总四臂名 + 累计指标)
"""
from __future__ import annotations
import os, sys, json, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from collections import Counter
from pathlib import Path

# ── 路径(固定,改这里要更新 prereg) ────────────────────────────────────────
NFLAG_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/research/narrative_flags")
FROZEN_DIR = NFLAG_DIR / "frozen"
STATE_FILE = NFLAG_DIR / "_t142_state.json"
REPORT_PATH = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-142_narrative_ab.md")

EXCLUDE_BTC_ETH = {"BTC", "ETH"}
UNIVERSE_EXCLUDE = {"USDC", "BTCDOM", "DEFI"}
ADV30_MIN = 5_000_000.0
RN_MIN = 220
LOOKAHEAD_DAYS = 60
FAST_FISH_MULT = 2.0
TOP_N_E_T = 10

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HEAD = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


# ── Supabase REST 帮手 ───────────────────────────────────────────────────
def _get(path: str, params: dict, page: int = 1000) -> list:
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='(),.')}" for k, v in params.items())
    out, off = [], 0
    while True:
        req = urllib.request.Request(
            f"{SB}/rest/v1/{path}?{q}&limit={page}&offset={off}", headers=HEAD)
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read()) or []
        out += rows
        if len(rows) < page:
            return out
        off += page


def _iso_week(mon: date) -> str:
    y, w, _ = mon.isocalendar()
    return f"{y}-W{w:02d}"


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ── 取 E 臂(narrative_events.related_assets 计数前 10) ────────────────
def _arm_e(mon: date) -> tuple[list, Counter]:
    lo, hi = mon - timedelta(days=7), mon
    rows = _get("narrative_events", {
        "select": "related_assets",
        "and": f"(date.gte.{lo.isoformat()},date.lt.{hi.isoformat()})",
    })
    cnt = Counter()
    for r in rows:
        ra = r.get("related_assets")
        if not ra:
            continue
        # 兼容三种形态:
        #   ① JSON 字符串数组:'["BTC","ETH"]'
        #   ② 逗号分隔字符串:'BNB,ETH'  ← 监听器有的样本里见过
        #   ③ 单 token:'ETH'
        if isinstance(ra, str):
            try:
                arr = json.loads(ra)
                if isinstance(arr, list):
                    tokens = arr
                else:
                    tokens = [arr]
            except json.JSONDecodeError:
                tokens = [t.strip() for t in ra.split(",") if t.strip()]
        else:
            tokens = ra
        for s in tokens:
            sym = str(s).strip().upper()
            if sym and sym not in EXCLUDE_BTC_ETH:
                cnt[sym] += 1
    top = [s for s, _ in cnt.most_common(TOP_N_E_T)]
    return top, cnt


# ── 取 T 臂(trending_log.symbol 计数前 10) ───────────────────────────
def _arm_t(mon: date) -> tuple[list, Counter]:
    lo, hi = mon - timedelta(days=7), mon
    rows = _get("trending_log", {
        "select": "symbol",
        "and": f"(recorded_at.gte.{lo.isoformat()},recorded_at.lt.{hi.isoformat()})",
    })
    cnt = Counter()
    for r in rows:
        s = (r.get("symbol") or "").strip().upper()
        if not s or s in EXCLUDE_BTC_ETH:
            continue
        cnt[s] += 1
    top = [s for s, _ in cnt.most_common(TOP_N_E_T)]
    return top, cnt


# ── 取 N 臂(universe - J ∪ E ∪ T) ──────────────────────────────────────
def _universe(mon: date) -> set:
    """binance_hist 上 Mon 当日 rn ≥ 220、30 日均 close×vol ≥ 500 万美元的币集合。

    窗口 = Mon 之前 250 天(保证 rn ≥ 220 + 30 日 adv30 都有足够历史)。
    """
    lo = mon - timedelta(days=250)
    hi = mon
    rows = _get("ohlcv_daily", {
        "select": "symbol,trade_date,close,volume",
        "source": "eq.binance_hist",
        "and": f"(trade_date.gte.{lo.isoformat()},trade_date.lte.{hi.isoformat()})",
    })
    by = {}
    for r in rows:
        if r["symbol"] in UNIVERSE_EXCLUDE:
            continue
        by.setdefault(r["symbol"], []).append((r["trade_date"], float(r["close"] or 0), float(r["volume"] or 0)))
    members = set()
    for sym, ts in by.items():
        ts.sort(key=lambda x: x[0])
        # 找到 trade_date ≤ mon 的最后一根
        end_idx = max((i for i, (d, _, _) in enumerate(ts) if d <= mon.isoformat()), default=-1)
        if end_idx < RN_MIN - 1:
            continue
        if end_idx - 29 < 0:
            continue
        window = ts[end_idx - 29:end_idx + 1]
        adv30 = sum(c * v for _, c, v in window) / len(window)
        if adv30 >= ADV30_MIN:
            members.add(sym)
    return members


# ── 取 J 臂 ────────────────────────────────────────────────────────────
def _arm_j(week_key: str) -> tuple[list, str]:
    """读 narrative_flags/YYYY-Www.json,只在 status ≠ awaiting_jazz 时返回。"""
    fp = NFLAG_DIR / f"{week_key}.json"
    if not fp.exists():
        return [], "missing"
    j = json.loads(fp.read_text())
    if j.get("status") == "awaiting_jazz":
        return [], "awaiting_jazz"
    syms = []
    for t in j.get("themes", []):
        for s in t.get("symbols", []):
            sym = str(s).strip().upper()
            if sym:
                syms.append(sym)
    # 去重保序
    seen, uniq = set(), []
    for s in syms:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq, "ok"


# ── 写冻结名单(append-only,已存在就 skip) ──────────────────────────────
def _freeze(week_key: str, payload: dict) -> str:
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    fp = FROZEN_DIR / f"{week_key}.json"
    if fp.exists():
        return "exists"
    fp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return "wrote"


# ── 取 60 天前向 close,算快鱼与早不早 ──────────────────────────────────
def _forward_closes(sym: str, mon: date) -> tuple[list, float]:
    """[Mon, Mon+60] close 序列 + Mon close。空返回 ([], 0)。"""
    hi = mon + timedelta(days=LOOKAHEAD_DAYS)
    rows = _get("ohlcv_daily", {
        "select": "trade_date,close",
        "source": "eq.binance_hist",
        "symbol": f"eq.{sym}",
        "and": f"(trade_date.gte.{mon.isoformat()},trade_date.lte.{hi.isoformat()})",
        "order": "trade_date.asc",
    })
    if not rows:
        return [], 0.0
    c0 = float(rows[0]["close"] or 0)
    closes = [float(r["close"] or 0) for r in rows]
    return closes, c0


def _fast_fish(sym: str, mon: date, today: date) -> dict:
    """返回 {'d':'fast'|'miss'|'early_k_days'|'peak_mult'}。只在 Mon+60d ≤ today 时算。"""
    if mon + timedelta(days=LOOKAHEAD_DAYS) > today:
        return {"d": "immature"}
    closes, c0 = _forward_closes(sym, mon)
    if not closes or c0 <= 0:
        return {"d": "no_data"}
    target = FAST_FISH_MULT * c0
    first_hit = next((i for i, c in enumerate(closes) if c >= target), None)
    if first_hit is None:
        return {"d": "miss", "peak_mult": max(closes) / c0}
    return {
        "d": "fast",
        "first_hit_day": first_hit,             # 0 = Mon 收盘当天就达成
        "peak_mult": max(closes) / c0,
    }


# ── 周内汇总 ────────────────────────────────────────────────────────────
def _summarize_week(week_key: str, arms: dict, today: date) -> dict:
    """对四臂各算:fast 数 / rate / 中位 first_hit_day / 中位 peak_mult。"""
    mon_str = week_key.split("-W")[0] + "-W" + week_key.split("-W")[1]
    year, wk = week_key.split("-W")
    mon = date.fromisoformat(f"{year}-W{wk}-1") if False else None
    # 重建 Monday
    from datetime import datetime as _dt
    mon = _dt.strptime(f"{year} {wk} 1", "%G %V %u").date()
    out = {"week": week_key, "monday": mon.isoformat(), "matured": mon + timedelta(days=LOOKAHEAD_DAYS) <= today,
           "arms": {}}
    for arm_name, syms in arms.items():
        rows = []
        for s in syms:
            rows.append({"sym": s, **_fast_fish(s, mon, today)})
        fish = [r for r in rows if r["d"] == "fast"]
        misses = [r for r in rows if r["d"] == "miss"]
        peaks = [r["peak_mult"] for r in rows if "peak_mult" in r]
        hits = [r["first_hit_day"] for r in fish]
        out["arms"][arm_name] = {
            "n": len(syms),
            "n_fast": len(fish),
            "fast_rate": (len(fish) / len(syms)) if syms else None,
            "median_first_hit_day": (sorted(hits)[len(hits) // 2] if hits else None),
            "median_peak_mult": (sorted(peaks)[len(peaks) // 2] if peaks else None),
            "rows": rows,
        }
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).date()
    NFLAG_DIR.mkdir(parents=True, exist_ok=True)
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 列已存在的周
    week_keys = []
    for fp in sorted(NFLAG_DIR.glob("2026-W*.json")):
        wk = fp.stem
        if "-" in wk and wk.startswith("20"):
            week_keys.append(wk)

    # 2. 冻结周(append-only)
    state = {"last_run_utc": datetime.now(timezone.utc).isoformat(), "frozen": []}
    for wk in week_keys:
        # Monday
        year, w = wk.split("-W")
        mon = datetime.strptime(f"{year} {w} 1", "%G %V %u").date()
        j_syms, j_status = _arm_j(wk)
        e_syms, _ = _arm_e(mon)
        t_syms, _ = _arm_t(mon)
        uni = _universe(mon)
        tagged = set(j_syms) | set(e_syms) | set(t_syms)
        n_syms = sorted(uni - tagged)

        payload = {
            "week": wk,
            "monday": mon.isoformat(),
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "j": {"status": j_status, "symbols": j_syms},
            "e": {"size": len(e_syms), "symbols": e_syms},
            "t": {"size": len(t_syms), "symbols": t_syms},
            "n": {"universe_size": len(uni), "size": len(n_syms), "symbols": n_syms},
        }
        status = _freeze(wk, payload)
        state["frozen"].append({"week": wk, "status": status,
                                "j_status": j_status,
                                "j_n": len(j_syms), "e_n": len(e_syms),
                                "t_n": len(t_syms), "n_n": len(n_syms),
                                "matured": (mon + timedelta(days=LOOKAHEAD_DAYS)) <= today})

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    # 3. 累计报告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# T-142 / S-626 — 叙事标记前向 A/B 周报",
        "",
        f"生成时间(UTC):{datetime.now(timezone.utc).isoformat()}",
        "",
        "## 每周冻结状态",
        "",
        "| 周 | Monday | 冻结 | J 状态 | J 数 | E 数 | T 数 | N 数 | 60 天到期 |",
        "|----|--------|------|--------|------|------|------|------|------------|",
    ]
    for f in state["frozen"]:
        lines.append(
            f"| `{f['week']}` | "
            f"{datetime.strptime(f['week'].split('-W')[0] + ' ' + f['week'].split('-W')[1] + ' 1', '%G %V %u').date().isoformat()} | "
            f"{f['status']} | {f['j_status']} | {f['j_n']} | {f['e_n']} | "
            f"{f['t_n']} | {f['n_n']} | "
            f"{'✓' if f['matured'] else '·' } |"
        )

    # 4. 对到期周算快鱼
    matured_rows = []
    for f in state["frozen"]:
        if not f["matured"]:
            continue
        wk = f["week"]
        year, w = wk.split("-W")
        mon = datetime.strptime(f"{year} {w} 1", "%G %V %u").date()
        fp = FROZEN_DIR / f"{wk}.json"
        if not fp.exists():
            continue
        frozen = json.loads(fp.read_text())
        arms = {
            "J": frozen["j"]["symbols"],
            "E": frozen["e"]["symbols"],
            "T": frozen["t"]["symbols"],
            "N": frozen["n"]["symbols"],
        }
        summary = _summarize_week(wk, arms, today)
        matured_rows.append(summary)

    if matured_rows:
        lines.extend([
            "",
            "## 已到期周快鱼率(60 天内 max ≥ 2× Mon close)",
            "",
            "| 周 | 臂 | N | 快鱼数 | 快鱼率 | 中位首触日 | 中位峰值倍数 |",
            "|----|----|---|--------|--------|------------|--------------|",
        ])
        for s in matured_rows:
            for arm_name, a in s["arms"].items():
                if a["n"] == 0:
                    continue
                fr = f"{a['fast_rate']:.1%}" if a['fast_rate'] is not None else "—"
                fh = a["median_first_hit_day"] if a["median_first_hit_day"] is not None else "—"
                pk = f"{a['median_peak_mult']:.2f}×" if a["median_peak_mult"] is not None else "—"
                lines.append(f"| `{s['week']}` | {arm_name} | {a['n']} | {a['n_fast']} | {fr} | {fh} | {pk} |")
    else:
        lines.extend([
            "",
            "## 已到期周快鱼率",
            "",
            "_本周尚无已到期周(最早 Mon + 60d = 2026-12-18)。每臂名单已冻结,_待 W43 等到 60 天后自动开算。_",
        ])

    lines.extend([
        "",
        "## 进度与未决",
        "",
        "- 当前已冻结 J 臂数 = 0(W43 status=awaiting_jazz,Jazz 未给)。",
        "- S-626 判据要求 J 满 ≥ 12 周且最后一笔 60 天到期后跑周内打乱 2,000 次单侧 p。",
        "- 未到判据,**当前不判,只冻结名单**。",
        "",
        "— T-142 / S-626 preregistered;不读 .env;不打印 key。",
    ])

    REPORT_PATH.write_text("\n".join(lines))
    print(f"WROTE {REPORT_PATH}")
    print(f"FROZEN: {sum(1 for f in state['frozen'] if f['status'] == 'wrote')} wrote / "
          f"{sum(1 for f in state['frozen'] if f['status'] == 'exists')} exists")


if __name__ == "__main__":
    main()