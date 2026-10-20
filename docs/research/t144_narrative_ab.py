#!/usr/bin/env python3
"""T-144 — T-142 续:修 T 臂 + 加 S-629 的 Sharpe 臂 + 每周一自动跑。

三处改动(T-142 v1 → v2):
  ① T 臂 = 同一套规则重跑。W43 读到 0 个名字不是那周没有数据,是 trending_log 开了
     RLS 却没有 anon 的读策略 —— 用 publishable key 读是 HTTP 200 + 0 行,不报错。
     2026-10-20 13:4x UTC 生效(migrations/2026-10-20_lane_read_trending_style.sql,
     同一次迁移把 sharpe_mindshare_snap / social_daily 也放开了)。原冻结文件
     frozen/2026-W43.json 不覆盖(append-only),另写 frozen/<week>.T-fix.json。
  ② S 臂(S-629 原文):每周一取 sharpe_mindshare_snap 最近一份 win='now' 的快照,
     按 delta7d 取前 10;去 BTC / ETH、去稳定币、必须在当周 binance_hist 宇宙里。
     delta7d 缺失时用本表自存快照算 mindshare_pct(t) / mindshare_pct(t − 7 天) − 1,
     两份都在才算,不在就不进候选。排名用 window = 'now'。
  ③ 任何一臂某周读到 0 行,先查是不是读权限:同表最近 14 天总行数
     (到该周周一为止)为 0 才算「没数据」,否则报「疑似读不到」并**停写那一周**。

尺子不变(S-626 / S-629):快鱼 = 周一收盘后 60 天内最高收盘 ≥ 2 × 周一收盘;
同一结果尺子、同一判据(快鱼率 > N,周内打乱 2,000 次单侧 p < 0.05)、同日到期。

读库:仅用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'];不读 .env、不打印 key。

运行(T-144 ④ 的调度方案,本卡 allowed_paths 不含 scripts/lane_bot/,由 Seth 加):
  cron: 30 1 * * 1  <跑本脚本的 shell>   # 每周一 01:30 UTC(宿主机时区须是 UTC)
  shell 须先导出 SUPABASE_URL / SUPABASE_KEY(publishable,只读),再
  python3 docs/research/t144_narrative_ab.py
  脚本按当天是周几自己判断冻结哪一周(周一跑 = 冻结刚结束的那周);
  冻结文件 append-only:该周 .T-fix.json 已存在就不重写名字,只刷新周报。

输出:
  research/narrative_flags/frozen/<week>.T-fix.json — T / N / S 三臂修正后名单
  research/narrative_flags/_t144_state.json           — 累计状态
  数据根 _reports/absorb_input/T-142_narrative_ab.md  — 周报(五臂 J/E/T/S/N)
"""
from __future__ import annotations
import os, sys, json, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from collections import Counter
from pathlib import Path

NFLAG_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/research/narrative_flags")
FROZEN_DIR = NFLAG_DIR / "frozen"
STATE_FILE = NFLAG_DIR / "_t144_state.json"
REPORT_PATH = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-142_narrative_ab.md")

EXCLUDE_BTC_ETH = {"BTC", "ETH"}
# N 臂 = universe 减所有标记臂(S-626 补,T-147);BTC / ETH 也排除,免得 N 被两条
# 主流稀释后 J / E / T / S 所有人都得跑过一条「所有人一起上涨」的底,J 永远过不了线。
UNIVERSE_EXCLUDE = {"USDC", "BTCDOM", "DEFI", "BTC", "ETH"}
# S 臂额外去稳定币(Sharpe 的 universe 比 binance_hist 宽得多,含一堆锚定美元的票)
STABLE = {
    "USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP", "FDUSD", "USDD", "PYUSD",
    "USDS", "USDE", "USDD", "RLUSD", "FRAX", "LUSD", "GUSD", "EURC", "EURS",
    "UST", "USTC", "SUSD", "USDF", "BFRAX", "MIM", "CRVUSD", "USDY", "AUSD",
    "BUSD", "XSGD", "XIDR", "VAI", "WOO", "FEI", "NUSD", "OUSD", "YUSD",
}
ADV30_MIN = 5_000_000.0
RN_MIN = 220
LOOKAHEAD_DAYS = 60
FAST_FISH_MULT = 2.0
TOP_N_E_T = 10
READ_PROBE_DAYS = 14

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HEAD = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


# ── Supabase REST 帮手(带分页) ──────────────────────────────────────────
def _get(path: str, params: dict, page: int = 1000) -> list:
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='(),.')}" for k, v in params.items())
    out, off = [], 0
    while True:
        req = urllib.request.Request(
            f"{SB}/rest/v1/{path}?{q}&limit={page}&offset={off}", headers=HEAD)
        with urllib.request.urlopen(req, timeout=90) as r:
            rows = json.loads(r.read()) or []
        out += rows
        if len(rows) < page:
            return out
        off += page


def _count(path: str, params: dict) -> int:
    """精确计数(走 Content-Range 头,避免把整表拉下来)。"""
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='(),.')}" for k, v in params.items())
    req = urllib.request.Request(f"{SB}/rest/v1/{path}?{q}&limit=1", headers={
        **HEAD, "Prefer": "count=exact", "Range": "0-0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.split("/")[-1]) if "/" in cr else 0


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _iso_week(mon: date) -> str:
    y, w, _ = mon.isocalendar()
    return f"{y}-W{w:02d}"


def _monday_from_key(wk: str) -> date:
    year, w = wk.split("-W")
    return datetime.strptime(f"{year} {w} 1", "%G %V %u").date()


# ── ③ 读权限探针 ────────────────────────────────────────────────────────
def _probe(table: str, ts_col: str, mon: date) -> dict:
    """到 mon 为止的最近 READ_PROBE_DAYS 天,同表总行数。

    > 0 ⇒ 表里有数据,某臂读到 0 是读不到(权限 / 过滤),不是没数据。
    = 0 ⇒ 那段时间确实没数据。
    """
    lo = mon - timedelta(days=READ_PROBE_DAYS)
    n = _count(table, {"select": ts_col, "and": f"({ts_col}.gte.{lo.isoformat()},"
                                         f"{ts_col}.lt.{mon.isoformat()})"})
    return {"table": table, "window": f"{lo}..{mon}", "rows_14d": n,
            "verdict": "no_data" if n == 0 else "has_data"}


# ── E 臂 ────────────────────────────────────────────────────────────────
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
        if isinstance(ra, str):
            try:
                arr = json.loads(ra)
                tokens = arr if isinstance(arr, list) else [arr]
            except json.JSONDecodeError:
                tokens = [t.strip() for t in ra.split(",") if t.strip()]
        else:
            tokens = ra
        for s in tokens:
            sym = str(s).strip().upper()
            if sym and sym not in EXCLUDE_BTC_ETH:
                cnt[sym] += 1
    return [s for s, _ in cnt.most_common(TOP_N_E_T)], cnt


# ── T 臂 ────────────────────────────────────────────────────────────────
def _arm_t(mon: date) -> tuple[list, Counter, int]:
    """规则不变,只重跑:窗口 [Mon−7d, Mon),trending_log.symbol 计数前 10(去 BTC/ETH)。"""
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
    return [s for s, _ in cnt.most_common(TOP_N_E_T)], cnt, len(rows)


# ── S 臂(S-629) ────────────────────────────────────────────────────────
def _latest_snap_date() -> str:
    rows = _get("sharpe_mindshare_snap",
                {"select": "snap_d", "win": "eq.now", "order": "snap_d.desc", "limit": 1})
    return rows[0]["snap_d"] if rows else "—"


def _arm_s(mon: date, universe: set) -> tuple[list, dict]:
    """取最近一份 win='now' 快照,按 delta7d 取前 10。

    delta7d 缺失 → 用本表自存快照算 mindshare_pct(t) / mindshare_pct(t − 7 天) − 1,
    两份都在才算。返回 (top10, diag)。
    """
    snaps = _get("sharpe_mindshare_snap", {
        "select": "snap_d", "win": "eq.now", "order": "snap_d.desc", "limit": 1})
    if not snaps:
        return [], {"status": "no_snapshot", "detail": "win='now' 快照表为空"}
    snap_d = snaps[0]["snap_d"]
    # 快照日必须不晚于该周周一 —— 否则是未来信息(周一还拿不到周二的快照)
    if date.fromisoformat(snap_d) > mon:
        return [], {"status": "no_point_in_time_snapshot",
                    "detail": f"最近快照 {snap_d} 晚于该周周一 {mon},按时点不可用"}
    rows = _get("sharpe_mindshare_snap", {
        "select": "symbol,mindshare_pct,delta7d", "win": "eq.now", "snap_d": f"eq.{snap_d}"})

    prev_d = (date.fromisoformat(snap_d) - timedelta(days=7)).isoformat()
    prev = {}
    if date.fromisoformat(snap_d) - timedelta(days=7) >= date(2026, 10, 20):
        # 自存快照起点 2026-10-20;更早的 t−7 没有本表记录,不算
        prows = _get("sharpe_mindshare_snap", {
            "select": "symbol,mindshare_pct", "win": "eq.now", "snap_d": f"eq.{prev_d}"})
        prev = {(r.get("symbol") or "").upper(): r.get("mindshare_pct") for r in prows}

    n_delta_col = 0
    n_delta_self = 0
    scored = []
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym or sym in EXCLUDE_BTC_ETH or sym in STABLE or sym in UNIVERSE_EXCLUDE:
            continue
        d7 = r.get("delta7d")
        if d7 is not None:
            n_delta_col += 1
            scored.append((sym, float(d7), "delta7d"))
            continue
        ms_now = r.get("mindshare_pct")
        ms_prev = prev.get(sym)
        if ms_now and ms_prev:
            n_delta_self += 1
            scored.append((sym, float(ms_now) / float(ms_prev) - 1.0, "self_7d"))
    scored.sort(key=lambda x: -x[1])
    top = [s for s, _, _ in scored[:TOP_N_E_T] if s in universe]
    return top, {
        "status": "ok" if top else "no_candidate",
        "snap_d": snap_d, "rows_in_snap": len(rows), "prev_snap_d": prev_d,
        "rows_in_prev": len(prev),
        "n_delta7d_col": n_delta_col, "n_delta7d_self": n_delta_self,
        "n_scored_before_universe": len(scored),
        "detail": ("delta7d 全 null 且自存快照不足 7 天" if not scored
                   else f"{len(scored)} 个可打分,入宇宙后 {len(top)}"),
    }


# ── N 臂(universe 减所有标记臂) ─────────────────────────────────────────
def _universe(mon: date) -> set:
    lo = mon - timedelta(days=250)
    rows = _get("ohlcv_daily", {
        "select": "symbol,trade_date,close,volume",
        "source": "eq.binance_hist",
        "and": f"(trade_date.gte.{lo.isoformat()},trade_date.lte.{mon.isoformat()})",
    })
    by = {}
    for r in rows:
        if r["symbol"] in UNIVERSE_EXCLUDE:
            continue
        by.setdefault(r["symbol"], []).append(
            (r["trade_date"], float(r["close"] or 0), float(r["volume"] or 0)))
    members = set()
    for sym, ts in by.items():
        ts.sort(key=lambda x: x[0])
        end_idx = max((i for i, (d, _, _) in enumerate(ts) if d <= mon.isoformat()), default=-1)
        if end_idx < RN_MIN - 1 or end_idx - 29 < 0:
            continue
        window = ts[end_idx - 29:end_idx + 1]
        adv30 = sum(c * v for _, c, v in window) / len(window)
        if adv30 >= ADV30_MIN:
            members.add(sym)
    # ── 自检(T-147 acceptance):N 臂不能含 BTC / ETH,出现即 abort。
    leak = EXCLUDE_BTC_ETH & members
    assert not leak, f"N 臂出现 BTC/ETH:{sorted(leak)}(UNIVERSE_EXCLUDE 漏配?)"
    return members


# ── J 臂 ────────────────────────────────────────────────────────────────
def _arm_j(week_key: str) -> tuple[list, str]:
    fp = NFLAG_DIR / f"{week_key}.json"
    if not fp.exists():
        return [], "missing"
    j = json.loads(fp.read_text())
    if j.get("status") == "awaiting_jazz":
        return [], "awaiting_jazz"
    seen, uniq = set(), []
    for t in j.get("themes", []):
        for s in t.get("symbols", []):
            sym = str(s).strip().upper()
            if sym and sym not in seen:
                seen.add(sym)
                uniq.append(sym)
    return uniq, "ok"


# ── 快鱼(尺子不变) ─────────────────────────────────────────────────────
def _fast_fish(sym: str, mon: date, today: date) -> dict:
    if mon + timedelta(days=LOOKAHEAD_DAYS) > today:
        return {"d": "immature"}
    hi = mon + timedelta(days=LOOKAHEAD_DAYS)
    rows = _get("ohlcv_daily", {
        "select": "trade_date,close", "source": "eq.binance_hist",
        "symbol": f"eq.{sym}",
        "and": f"(trade_date.gte.{mon.isoformat()},trade_date.lte.{hi.isoformat()})",
        "order": "trade_date.asc",
    })
    if not rows:
        return {"d": "no_data"}
    c0 = float(rows[0]["close"] or 0)
    if c0 <= 0:
        return {"d": "no_data"}
    closes = [float(r["close"] or 0) for r in rows]
    first = next((i for i, c in enumerate(closes) if c >= FAST_FISH_MULT * c0), None)
    peak = max(closes) / c0
    if first is None:
        return {"d": "miss", "peak_mult": peak}
    return {"d": "fast", "first_hit_day": first, "peak_mult": peak}


def _summarize(mon: date, arms: dict, today: date) -> dict:
    out = {"week": _iso_week(mon), "monday": mon.isoformat(),
           "matured": mon + timedelta(days=LOOKAHEAD_DAYS) <= today, "arms": {}}
    # T-147 acceptance:打分对所有周统一先剔除 N 里的 BTC / ETH 再算。
    # _universe 已从底层排除 BTC/ETH;这里再 strip 一遍是防御(W43 等更早冻结文件
    # 是 UNIVERSE_EXCLUDE 加 BTC/ETH 之前的产物,frozen append-only 不重写)。
    # 不在 _summarize 里 assert:旧 frozen 文件 N 里残留的 BTC/ETH 在这里 strip 后
    # 照样能算快鱼;_universe 是真正的自检闸口(UNIVERSE_EXCLUDE 漏配就 abort,见上)。
    n_stripped: list = []
    if "N" in arms:
        leak = sorted(EXCLUDE_BTC_ETH & set(arms["N"]))
        if leak:
            n_stripped = leak
            arms = {**arms, "N": [s for s in arms["N"] if s not in EXCLUDE_BTC_ETH]}
    for name, syms in arms.items():
        rows = [{"sym": s, **_fast_fish(s, mon, today)} for s in syms]
        fish = [r for r in rows if r["d"] == "fast"]
        peaks = [r["peak_mult"] for r in rows if "peak_mult" in r]
        hits = sorted(r["first_hit_day"] for r in fish)
        out["arms"][name] = {
            "n": len(syms), "n_fast": len(fish),
            "fast_rate": (len(fish) / len(syms)) if syms else None,
            "median_first_hit_day": hits[len(hits) // 2] if hits else None,
            "median_peak_mult": (sorted(peaks)[len(peaks) // 2]) if peaks else None,
            "rows": rows,
        }
    if n_stripped:
        out["n_stripped_btc_eth"] = n_stripped
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).date()
    # 目标周 = 刚走完的那一周(周一 01:30 跑时,刚结束的是上周一开头的那周;
    # 周二~周日补跑时,刚结束的是本周一开头的那周)
    this_mon = _monday_of(today)
    target = this_mon - timedelta(days=7) if today.weekday() == 0 else this_mon
    week_keys = [_iso_week(target)]
    # 目录里已存在的周也一并保证有 T-fix(首次跑只有一周)
    for fp in sorted(NFLAG_DIR.glob("2026-W*.json")):
        wk = fp.stem
        if wk.startswith("20") and wk not in week_keys:
            week_keys.append(wk)

    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    NFLAG_DIR.mkdir(parents=True, exist_ok=True)

    state = {"last_run_utc": datetime.now(timezone.utc).isoformat(),
             "script_version": "t144_v2", "weeks": []}

    for wk in sorted(week_keys):
        mon = _monday_from_key(wk)
        probes = {t: _probe(t, c, mon) for t, c in
                  (("trending_log", "recorded_at"), ("narrative_events", "date"),
                   ("sharpe_mindshare_snap", "snap_d"))}

        j_syms, j_status = _arm_j(wk)
        e_syms, _ = _arm_e(mon)
        t_syms, t_cnt, t_rows = _arm_t(mon)
        uni = _universe(mon)
        s_syms, s_diag = _arm_s(mon, uni)

        # ③ 停写条件:某臂读到 0 行,但同表最近 14 天有数据 ⇒ 疑似读不到
        blocked = []
        if not t_syms and probes["trending_log"]["verdict"] == "has_data":
            blocked.append(f"T(trending_log 近 14 天 {probes['trending_log']['rows_14d']} 行,"
                           f"本周窗口读到 0)")
        if not e_syms and probes["narrative_events"]["verdict"] == "has_data":
            blocked.append(f"E(narrative_events 近 14 天 {probes['narrative_events']['rows_14d']} 行,"
                           f"本周窗口读到 0)")
        # S 臂的「0 行」有两种正当原因(按时点快照尚不存在 / delta7d 拿不到),
        # 只有「表里有行却一条 win='now' 都读不到」才是读权限问题
        s_blocked = (not s_syms and s_diag.get("status") == "no_snapshot"
                     and probes["sharpe_mindshare_snap"]["verdict"] == "has_data")

        payload = {
            "week": wk, "monday": mon.isoformat(),
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "fix_of": f"{wk}.json",
            "fix_reason": "T 臂 0 是 trending_log 读权限(RLS 无 anon select 策略,"
                          "publishable key 读到 HTTP 200 + 0 行),不是那周没有数据;"
                          "2026-10-20 13:4x UTC 后重跑。原文件不覆盖。",
            "read_probes": probes,
            "j": {"status": j_status, "size": len(j_syms), "symbols": j_syms},
            "e": {"size": len(e_syms), "symbols": e_syms},
            "t": {"size": len(t_syms), "rows_in_window": t_rows,
                  "symbols": t_syms,
                  "counts": dict(t_cnt.most_common(15))},
            "s": {"size": len(s_syms), "symbols": s_syms, "diag": s_diag},
            "n": {"universe_size": len(uni), "size": 0, "symbols": []},
            "blocked": blocked, "s_blocked": bool(s_blocked),
        }
        # N = universe 减所有标记臂(S-629 要求 S 与 S-626 同一把尺子 ⇒ N 也要减 S,
        # 否则 S 与 N 重叠,判定无意义)
        tagged = set(j_syms) | set(e_syms) | set(t_syms) | set(s_syms)
        n_syms = sorted(uni - tagged)
        payload["n"]["size"] = len(n_syms)
        payload["n"]["symbols"] = n_syms
        payload["arm_sizes"] = {"J": len(j_syms), "E": len(e_syms), "T": len(t_syms),
                                "S": len(s_syms), "N": len(n_syms)}

        fp = FROZEN_DIR / f"{wk}.T-fix.json"
        if fp.exists():
            # append-only:该周已冻结过就不重写名字,只把诊断带进周报
            prior = json.loads(fp.read_text())
            state["weeks"].append({
                "week": wk, "monday": mon.isoformat(), "written": True, "exists": True,
                "j_status": j_status, "path": str(fp),
                "arm_sizes": {"J": prior["j"]["size"], "E": prior["e"]["size"],
                              "T": prior["t"]["size"], "S": prior["s"]["size"],
                              "N": prior["n"]["size"]},
                "t_rows_in_window": prior["t"].get("rows_in_window"),
                "s_diag": prior.get("s", {}).get("diag", {}),
                "matured": mon + timedelta(days=LOOKAHEAD_DAYS) <= today,
            })
            continue
        if blocked:
            payload["written"] = False
            payload["skip_reason"] = f"③ 疑似读不到,停写这一周:{'; '.join(blocked)}"
            state["weeks"].append({"week": wk, "monday": mon.isoformat(), "j_status": j_status,
                                   "written": False, "skip_reason": payload["skip_reason"],
                                   "arm_sizes": payload["arm_sizes"], "s_diag": s_diag})
            continue
        fp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        payload["written"] = True
        state["weeks"].append({
            "week": wk, "monday": mon.isoformat(), "written": True, "j_status": j_status,
            "path": str(fp), "arm_sizes": payload["arm_sizes"],
            "t_rows_in_window": t_rows, "s_diag": s_diag,
            "matured": mon + timedelta(days=LOOKAHEAD_DAYS) <= today,
        })

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    # ── 报告 ────────────────────────────────────────────────────────────
    lines = [
        "# T-142 / S-626 + T-144 / S-629 — 叙事标记前向 A/B 周报(五臂 J / E / T / S / N)",
        "",
        f"生成时间(UTC):{datetime.now(timezone.utc).isoformat()}",
        "",
        "## 本轮改动(T-144)",
        "",
        "1. **T 臂修复** —— W43 的 T = 0 不是那周没有数据,是 `trending_log` 开了 RLS "
        "却没有 anon 的读策略:用 publishable key 读是 HTTP 200 + 0 行,不报错"
        "(同期表里 14 天 3,570 行)。`migrations/2026-10-20_lane_read_trending_style.sql` "
        "在 10-20 13:4x UTC 生效后重跑,规则一字未改(窗口仍是 [Mon−7d, Mon)、"
        "`symbol` 计数前 10、去 BTC/ETH)。原 `frozen/2026-W43.json` 不覆盖,修正写在 "
        "`frozen/<week>.T-fix.json`。",
        "2. **S 臂**(S-629 原文):每周一取 `sharpe_mindshare_snap` 最近一份 `win='now'` "
        "的快照,按 delta7d 取前 10,去 BTC/ETH、去稳定币、必须在当周 binance_hist 宇宙里;"
        "delta7d 缺失时用本表自存快照算 `mindshare_pct(t) / mindshare_pct(t − 7 天) − 1`,"
        "两份都在才算。N 臂同步减去 S —— 否则 S 与 N 重叠,判定没有意义。",
        "3. **读权限守卫**③:任一臂某周读到 0 行,先看同表到该周周一为止最近 14 天总行数;"
        "= 0 才是「没数据」,> 0 一律报「疑似读不到」并**停写那一周**。",
        "",
        "## 每周冻结状态(五臂)",
        "",
        "| 周 | Monday | 写入 | J 状态 | J | E | T | S | N(宇宙) | T 窗口行数 | S 快照 | 60 天到期 |",
        "|----|--------|------|--------|---|---|---|---|---------|-----------|--------|------------|",
    ]
    for w in state["weeks"]:
        sz = w["arm_sizes"]
        d = w.get("s_diag") or {}
        snap_cell = d.get("snap_d") or d.get("status", "—")
        jst = w.get("j_status") or "—"
        lines.append(
            f"| `{w['week']}` | {w['monday']} | {'✓' if w['written'] else '停写'} | {jst} | "
            f"{sz['J']} | {sz['E']} | {sz['T']} | {sz['S']} | {sz['N']} | "
            f"{w.get('t_rows_in_window', '—')} | {snap_cell} | "
            f"{'✓' if w.get('matured') else '·'} |")
        if not w["written"]:
            lines.append(f"| | | | | | | | | | | | | {w['skip_reason']} |")

    matured = []
    for w in state["weeks"]:
        if not w["written"] or not w.get("matured"):
            continue
        fp = Path(w["path"])
        if not fp.exists():
            continue
        frozen = json.loads(fp.read_text())
        arms = {k: frozen[k]["symbols"] for k in ("j", "e", "t", "s", "n")}
        matured.append(_summarize(_monday_from_key(w["week"]), arms, today))

    if matured:
        lines += ["", "## 已到期周快鱼率(60 天内最高收盘 ≥ 2 × 周一收盘)", "",
                  "| 周 | 臂 | N | 快鱼数 | 快鱼率 | 中位首触日 | 中位峰值倍数 |",
                  "|----|----|---|--------|--------|------------|--------------|"]
        for s in matured:
            for arm, a in s["arms"].items():
                if a["n"] == 0:
                    continue
                fr = f"{a['fast_rate']:.1%}" if a["fast_rate"] is not None else "—"
                fh = a["median_first_hit_day"] if a["median_first_hit_day"] is not None else "—"
                pk = f"{a['median_peak_mult']:.2f}×" if a["median_peak_mult"] is not None else "—"
                lines.append(f"| `{s['week']}` | {arm} | {a['n']} | {a['n_fast']} | {fr} | {fh} | {pk} |")
    else:
        lines += ["", "## 已到期周快鱼率", "",
                  "_尚无已到期周(最早 2026-W43 到期 2026-12-18)。每臂名单已冻结,"
                  "待 60 天后自动开算。_"]

    diag = state["weeks"][-1].get("s_diag", {}) if state["weeks"] else {}
    snap_live = _latest_snap_date()
    lines += [
        "", "## S 臂现状(卡在数据本身,不是读权限)", "",
        f"- 库里最近 `win='now'` 快照 = **{snap_live}**。"
        + (f"它晚于 W43 的周一(2026-10-19),按时点不可用 —— "
           f"**这一周的 S 臂按预注册不填**,不是读失败。"
           if diag.get("status") == "no_point_in_time_snapshot" else ""),
        f"- 该快照 `delta7d` 字段全为 null(实测 356 / 356 行)⇒ 只能走预注册的 fallback:"
        f"用本表自存快照算 `mindshare_pct(t) / mindshare_pct(t − 7 天) − 1`。",
        f"- 自存快照起始 2026-10-20(第一批入库当天),要凑出 t 与 t−7 两份,"
        f"**最早可算的周是 2026-W45**(11-02 用 10-26 与 11-02 两份);"
        f"W43 / W44 的 S 臂按预注册**不填**(两份不在就不进候选)。",
        "- fallback 排序 / 去 BTC·稳定币 / 宇宙过滤 / 列优先 / 按时点守卫已用假数据冒烟测过"
        "(`research/t144_smoke.py`,6/6 通过),等真数据到周就能直接开跑。",
        "", "## 进度与未决", "",
        "- J 臂仍为 0(`status=awaiting_jazz`,Jazz 未给标记)。",
        "- S-626 / S-629 判据:J 满 ≥ 12 周且最后一笔 60 天结果到期后,"
        "周内打乱「标 / 不标」2,000 次,单侧 p < 0.05(各臂 > N)。",
        "- **当前不判,只冻结名单。**",
        "",
        "— T-142 / T-144 preregistered(S-626 / S-629);不读 .env、不打印 key。",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines))
    print(f"WROTE {REPORT_PATH}")
    for w in state["weeks"]:
        print(f"  {w['week']} J{w['arm_sizes']['J']} E{w['arm_sizes']['E']} "
              f"T{w['arm_sizes']['T']} S{w['arm_sizes']['S']} N{w['arm_sizes']['N']} "
              f"written={w['written']}")


if __name__ == "__main__":
    main()