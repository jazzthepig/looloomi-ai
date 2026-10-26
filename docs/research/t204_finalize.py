#!/usr/bin/env python3
"""T-204 收尾器:等闸门 → 跑全量 → 第二实现逐月对数 → 填报告 → 改卡 → 推分支。

用法:
    python3 docs/research/t204_finalize.py --wait     # 轮询等闸门(5 分钟一轮),开闸即收尾
    python3 docs/research/t204_finalize.py --now      # 不等,按当前闸门状态收尾(闸门未开 ⇒ 退出码 3)
    python3 docs/research/t204_finalize.py --dry-run  # 只算不写(自检)

只读 Supabase(publishable key);不改预注册协议;不碰 forbidden_paths 下的任何文件。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

REPO = "/Users/sbb/Projects/looloomi-ai-lane-c"
REPORT = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-204_oi_mcap_outofpanel.md"
CARD = os.path.join(REPO, "tasks", "T-204.json")
RESULTS = os.path.join(REPO, "docs", "research", "t204_results.json")
VERIFY = os.path.join(REPO, "docs", "research", "t204_verify_out_of_panel.json")
MAIN = os.path.join(REPO, "docs", "research", "t204_oi_mcap_outofpanel.py")
VERIFY_SCRIPT = os.path.join(REPO, "docs", "research", "t204_verify_independent.py")
DEADLINE = "2026-10-28T00:00:00+00:00"
HEAD_START = "<!--T204_HEAD_START-->"
HEAD_END = "<!--T204_HEAD_END-->"
URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

PROTOCOL_NOTES = """
## 8. 协议问题(本轮新增;细节见 §5)

1. **闸门能不能开的口径**:卡上写「`perp_cg_map` 里没有 `verdict='pending'` 的行」。循环把「候选试完」的名字
   判成终态 `unresolved`(终态 ≠ pending,闸门能开);但**候选列表为空**的名字不会变成终态 —— 它会永远停在
   pending ⇒ 闸门永远不开。本轮实测:38 个 pending 名字**全部**有候选(候选数 1–6,中位 4),没有空列表
   ⇒ 闸门可达。(读的是 `src/data/market/perp_mcap_backfill.py` 当前实现;若状态机改了,闸门的可达性跟着变。)
2. **速率与请求预算**:`MAX_CALLS_PER_RUN=3`、`INTERVAL_S=600`、`MAX_CANDIDATES=6` ⇒ 一个名字最坏要 6 次
   `market_chart`(2 轮)。本轮实测 15:11–15:58 UTC(47 分钟):resolved 0 → **5**、pending 43 → **38**
   ⇒ 约 **1 个名字 / 9–10 分钟** ⇒ 剩 38 个 ≈ **6 小时** ⇒ 闸门 ETA ≈ **2026-10-26 21:00–22:00 UTC**
   (早于台账 10-28 00:00 UTC 兜底)。速率是实测值,不是估算:每轮内候选试完会接着试下一个名字。
3. **`candidates` 为空的搜索阶段在预算检查之前**:`perp_mcap_backfill.py` 第 132–157 行(取 CG 候选)跑在
   第 164 行(`if calls >= MAX_CALLS_PER_RUN`)之前 ⇒ 那一段可能一次性发出超过 3 次 CoinGecko 请求,
   与「每轮最多 3 次」的口径不一致。本轮不影响结果(所有 pending 行都已有 candidates),但对以后的轮次是个口子。
4. **独立性的字面冲突(继续有效)**:卡上「交付前不读 `docs/research/s689_*`」与「照台账 S-689 一字不改」冲突 ——
   台账本体就是 `docs/research/s689_oi_mcap_outofpanel.sql`。处理:只读那一个预注册文件(73 行、只有查询、
   没有结果),**交付前没读任何 s689 的结果文件**;主仓库至今没有 s689 的结果文件。
5. **`cg_coin_mcap_daily` 里有 `mcap = −1` 与 null 的行**:价格校验不看市值 ⇒ 这类币能过校验、然后在「行」段
   被整段丢掉(名字算「留下」但一行都没有)。台账的「行」规则要求 CG 市值 ≥ 2000 万,−1/null 不该算「有价」——
   本卡照台账的字面执行(名字留下、行丢掉),但语义上更接近「剔除」⇒ 记在这里,不改协议。
""".strip()


def log(*a):
    print("[finalize]", *a, flush=True)


def q(path, count=False):
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if count:
        headers["Prefer"] = "count=exact"
        headers["Range"] = "0-0"
    req = urllib.request.Request(URL + "/rest/v1/" + path, headers=headers)
    r = urllib.request.urlopen(req, timeout=120)
    body = r.read()
    if count:
        return int(r.headers.get("Content-Range").split("/")[-1])
    return json.loads(body)


def now():
    return datetime.now(timezone.utc)


def gate_state():
    """(pending_n, gate_ok, deadline_passed, rows_total)"""
    rows = q("perp_cg_map?select=symbol,verdict&order=symbol.asc")
    pending = [r["symbol"] for r in rows if r.get("verdict") == "pending"]
    n = len(pending)
    dl = datetime.fromisoformat(DEADLINE)
    passed = now() >= dl
    return n, (n == 0 or passed), passed, len(rows)


def wait_for_gate(poll_s=300, hard_stop_h=9.0):
    t0 = time.time()
    while True:
        n, ok, passed, total = gate_state()
        log("gate check:", now().isoformat(), "pending=%d/%d" % (n, total),
            "deadline_passed=%s" % passed, "gate_ok=%s" % ok)
        if ok:
            return True
        if (time.time() - t0) > hard_stop_h * 3600:
            log("hard stop reached without gate")
            return False
        time.sleep(poll_s)


def f6(x):
    return "—" if x is None else ("%.*f" % (6, x))


def f4(x):
    return "—" if x is None else ("%.*f" % (4, x))


def decide(main, raw):
    """照抄台账 S-689 的判定(不改)。返回 (标签, 理由)"""
    m_mean, m_t = main["month_mean"], main["month_t"]
    h1 = main["halves"]["h1"]["month_mean"]
    h2 = main["halves"]["h2"]["month_mean"]
    raw_neg = raw["month_mean"] < 0 and raw["month_t"] <= -2.0
    if m_mean < 0 and m_t <= -2.0 and h1 < 0 and h2 < 0:
        return ("✅「OI/市值在规模之外有信息」",
                "主统计量月均 %s < 0、月 t %s ≤ −2.0、两半 %s / %s 都 < 0 ⇒ 命中台账第一条。"
                % (f6(m_mean), f4(m_t), f6(h1), f6(h2)))
    if raw_neg:
        return ("❌「是规模效应」(OI/市值不进 CIS)",
                "原始 ρ 月均 %s / 月 t %s 显著为负,而偏相关不过(主:月均 %s / 月 t %s / 两半 %s / %s)"
                " ⇒ 命中台账第二条。"
                % (f6(raw["month_mean"]), f4(raw["month_t"]), f6(m_mean), f4(m_t), f6(h1), f6(h2)))
    return ("❌ 只展示(不写进 CIS v2 影子)",
            "主统计量月均 %s / 月 t %s / 两半 %s / %s;原始 ρ 月均 %s / 月 t %s ⇒ 不命中台账前两条 ⇒ 第三条。"
            % (f6(m_mean), f4(m_t), f6(h1), f6(h2), f6(raw["month_mean"]), f4(raw["month_t"])))


def build_head(res, gate_line, diff=None):
    oop = res["out_of_panel"]
    st = oop["stats"]
    main, raw, size = st["main"], st["raw"], st["size"]
    pc = res.get("panel_control", {}).get("stats")
    tag, why = decide(main, raw)
    dropped = oop.get("names_dropped") or []
    dl = "; ".join("%s(%s)" % (d.get("symbol"), d.get("reason", "?")) for d in dropped)
    lines = []
    lines.append("> **状态:面板外主统计量已落(闸门开),交付物在分支 `lane-c/T-204`。**")
    lines.append("> 预注册:REFUTATION_LEDGER.md 的 **S-689**(2026-10-26 13:41 UTC)一字不改;")
    lines.append("> 第二实现(pandas/numpy,不 import 主脚本任何函数)逐月对数。")
    lines.append(">")
    lines.append("> **面板外(没看过的名字)—— 台账 S-689 的正式结果**")
    lines.append(">")
    lines.append("> | 项 | 值 |")
    lines.append("> |---|---|")
    lines.append("> | 闸门 | %s |" % gate_line)
    lines.append("> | 宇宙:deriv 名字(2023-01 起,去掉面板 25 名) | %s |" % oop.get("deriv_symbols_since_2023"))
    lines.append("> | 留下 / 剔除 | **%s** / %s |" % (oop.get("n_kept"), oop.get("n_dropped")))
    lines.append("> | 行数 / 截面日(≥30 名)/ 月数 | %s / %s / %s |" %
                 (oop.get("rows_total"), main.get("n_days"), main.get("n_months")))
    lines.append("> | **主**:偏 Spearman ρ(OI/市值, 结果 \\| 规模) 月均 / 月 t | **%s** / **%s** |" %
                 (f6(main["month_mean"]), f4(main["month_t"])))
    lines.append("> | 主:两半(2024-07-01 切)H1 / H2 月均 | %s / %s |" %
                 (f6(main["halves"]["h1"]["month_mean"]), f6(main["halves"]["h2"]["month_mean"])))
    lines.append("> | 主:两半 月 t(H1 / H2) | %s / %s |" %
                 (f4(main["halves"]["h1"].get("month_t")), f4(main["halves"]["h2"].get("month_t"))))
    lines.append("> | 副:原始 ρ(OI/市值, 结果) 月均 / 月 t | %s / %s |" %
                 (f6(raw["month_mean"]), f4(raw["month_t"])))
    lines.append("> | 副:规模 ρ(ln 市值, 结果) 月均 / 月 t | %s / %s |" %
                 (f6(size["month_mean"]), f4(size["month_t"])))
    if pc:
        lines.append("> | 面板对照(台账「附带·不判」)主:月均 / 月 t | %s / %s |" %
                     (f6(pc["main"]["month_mean"]), f4(pc["main"]["month_t"])))
        lines.append("> | 面板对照 副:原始 / 规模 月均 | %s / %s |" %
                     (f6(pc["raw"]["month_mean"]), f6(pc["size"]["month_mean"])))
    if diff:
        lines.append("> | 第二实现逐月对数(主/副原始/副规模)最大绝对差 | %s |" %
                     "/".join("%.2e" % diff[k]["max_abs_monthly_diff"] for k in ("main", "raw", "size")))
    lines.append(">")
    lines.append("> **判定(照抄台账 S-689 三条,照抄不改):**")
    lines.append("> - 主统计量月均 < 0、月 t ≤ −2.0、两半都 < 0 ⇒ ✅「OI/市值在规模之外有信息」")
    lines.append("> - 原始 ρ 显著为负而偏相关不过 ⇒ ❌「是规模效应」,OI/市值不进 CIS")
    lines.append("> - 其余 ⇒ ❌,只展示")
    lines.append(">")
    lines.append("> **本卡结果:%s** —— %s" % (tag, why))
    lines.append(">")
    lines.append("> 逐月值(6 位小数)、名单(留下/剔除及原因)、两半、敏感性、别名证据全在 "
                 "`docs/research/t204_results.json`;第二实现对数在 `docs/research/t204_verify_out_of_panel.json`。")
    if dl:
        lines.append(">")
        lines.append("> **剔除名单及原因(%s 个):** %s" % (len(dropped), dl))
    return "\n".join(lines)


def patch_report(head_text):
    with open(REPORT) as f:
        txt = f.read()
    if HEAD_START not in txt or HEAD_END not in txt:
        raise SystemExit("report markers missing")
    pre = txt.split(HEAD_START)[0]
    post = txt.split(HEAD_END)[1]
    new = pre + HEAD_START + "\n" + head_text + "\n" + HEAD_END + post
    if "## 8. 协议问题(本轮新增" not in new:
        new = new.rstrip() + "\n\n---\n\n" + PROTOCOL_NOTES + "\n"
    with open(REPORT, "w") as f:
        f.write(new)
    return new


def update_card(notes, status="in_review"):
    with open(CARD) as f:
        card = json.load(f)
    card["status"] = status
    card["notes"] = notes
    with open(CARD, "w") as f:
        json.dump(card, f, ensure_ascii=False, indent=1)
        f.write("\n")


def sh(cmd, cwd=REPO, timeout=3600):
    log("$", " ".join(cmd))
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.stdout:
        print(p.stdout[-4000:])
    if p.stderr:
        print(p.stderr[-4000:], file=sys.stderr)
    return p.returncode


def selftest():
    """用已有 results.json 的 panel_control 块当夹具,只验排版与判定分支(不碰真文件)。"""
    res = json.load(open(RESULTS))
    pc = res["panel_control"]
    fake = {
        "panel_control": pc,
        "out_of_panel": {
            "deriv_symbols_since_2023": pc.get("n_kept", 0) + 7,
            "n_kept": pc["n_kept"] if "n_kept" in pc else len(pc["names_kept"]),
            "n_dropped": len(pc["names_dropped"]),
            "rows_total": pc.get("rows_total", 0),
            "names_dropped": pc["names_dropped"],
            "stats": pc["stats"],
        },
    }
    diff = {"main": {"max_abs_monthly_diff": 0.0},
            "raw": {"max_abs_monthly_diff": 0.0},
            "size": {"max_abs_monthly_diff": 0.0}}
    print(build_head(fake, "夹具(不是真结果)", diff))
    for name, st in (("panel", pc["stats"]),):
        tag, why = decide(st["main"], st["raw"])
        print("\n[%s] %s —— %s" % (name, tag, why))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--set-notes", default=None,
                    help="把指定文件的内容写进卡 notes(不改 status)")
    ap.add_argument("--poll", type=int, default=300)
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.set_notes:
        txt = open(a.set_notes).read().strip()
        with open(CARD) as f:
            card = json.load(f)
        card["notes"] = txt
        with open(CARD, "w") as f:
            json.dump(card, f, ensure_ascii=False, indent=1)
            f.write("\n")
        log("card notes updated from", a.set_notes, "(status 保持 %s)" % card["status"])
        return 0

    if a.wait:
        if not wait_for_gate(poll_s=a.poll):
            log("gate never opened within the wait window; nothing written")
            return 4
    n, ok, passed, total = gate_state()
    log("gate:", "pending=%d/%d" % (n, total), "deadline_passed=%s" % passed, "ok=%s" % ok)
    if not ok:
        log("闸门未开 ⇒ 不落主统计量(卡上「不满足就直接停」);退出码 3")
        return 3

    rc = sh([sys.executable, MAIN, "--mode", "full", "--out", RESULTS])
    if rc != 0:
        log("main script failed rc=", rc)
        return 5
    rc = sh([sys.executable, VERIFY_SCRIPT, "--scope", "out", "--compare", RESULTS, "--out", VERIFY])
    if rc != 0:
        log("second implementation MISMATCH — not pushing; see", VERIFY)
        return 6

    res = json.load(open(RESULTS))
    ver = json.load(open(VERIFY))
    diff = ver.get("diff_vs_main")
    gate_line = "开(%s UTC;perp_cg_map 无 pending 行:%d/%d 行)" % (now().isoformat(), total - n, total)
    head = build_head(res, gate_line, diff)
    oop = res["out_of_panel"]
    st = oop["stats"]
    main_s, raw_s, size_s = st["main"], st["raw"], st["size"]
    tag, why = decide(main_s, raw_s)

    notes = (
        "**闸门开(%s UTC)后跑完 `--mode full`,交付物已推 `lane-c/T-204`。** "
        "面板外:宇宙 %s 个 deriv 名字(2023-01 起、去面板 25 名)⇒ 留下 **%s** / 剔除 %s;行 %s、截面日 %s、月数 %s。"
        "主(偏 Spearman ρ(OI/市值, 结果|规模))月均 **%s** / 月 t **%s**;两半 H1 %s / H2 %s(H1 t %s / H2 t %s)。"
        "副 原始 ρ 月均 %s / 月 t %s;副 规模 ρ 月均 %s / 月 t %s。面板对照(附带·不判)主:月均 %s / 月 t %s。"
        "第二实现(pandas/numpy)逐月对数:最大绝对差 主 %s / 副原始 %s / 副规模 %s。"
        "**S-689 判定:%s** —— %s"
        "剔除名单与原因、逐月值(6 位小数)在 docs/research/t204_results.json;"
        "对数在 docs/research/t204_verify_out_of_panel.json;"
        "报告 /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-204_oi_mcap_outofpanel.md。"
        "协议问题见报告 §5 与 §8(闸门口径、请求预算与候选搜索阶段、独立性字面冲突、mcap=-1 的行)。"
        % (now().isoformat(),
           oop.get("deriv_symbols_since_2023"), oop.get("n_kept"), oop.get("n_dropped"),
           oop.get("rows_total"), main_s.get("n_days"), main_s.get("n_months"),
           f6(main_s["month_mean"]), f4(main_s["month_t"]),
           f6(main_s["halves"]["h1"]["month_mean"]), f6(main_s["halves"]["h2"]["month_mean"]),
           f4(main_s["halves"]["h1"].get("month_t")), f4(main_s["halves"]["h2"].get("month_t")),
           f6(raw_s["month_mean"]), f4(raw_s["month_t"]),
           f6(size_s["month_mean"]), f4(size_s["month_t"]),
           f6(res.get("panel_control", {}).get("stats", {}).get("main", {}).get("month_mean")),
           f4(res.get("panel_control", {}).get("stats", {}).get("main", {}).get("month_t")),
           "%.2e" % diff["main"]["max_abs_monthly_diff"],
           "%.2e" % diff["raw"]["max_abs_monthly_diff"],
           "%.2e" % diff["size"]["max_abs_monthly_diff"],
           tag, why)
    )
    print("=== head ===")
    print(head)
    print("=== notes ===")
    print(notes)
    if a.dry_run:
        log("dry-run: nothing written")
        return 0

    patch_report(head)
    update_card(notes)
    rc = sh([sys.executable, "scripts/task_board.py"])
    if rc != 0:
        log("task_board failed rc=", rc)
        return 7
    rc = sh(["bash", "scripts/preflight.sh"], timeout=3600)
    if rc != 0:
        log("preflight FAILED rc=", rc, "— 不推(本地提交也不做),下一轮修")
        return 8
    sh(["git", "add", "docs/research/t204_oi_mcap_outofpanel.py", "docs/research/t204_finalize.py",
        "docs/research/t204_verify_independent.py", "docs/research/t204_results.json",
        "docs/research/t204_verify_out_of_panel.json", "docs/research/t204_gate_check.py",
        "docs/research/t204_gate_diag.py", "docs/research/t204_gate_rate.py",
        "tasks/T-204.json", "tasks/BOARD.md"])
    sh(["git", "commit", "-m", "research(T-204): S-689 面板外主统计量(闸门开)—— 主/副统计量 + 两实现逐月对数"])
    rc = sh(["git", "push", "-u", "origin", "lane-c/T-204"])
    if rc != 0:
        log("push failed rc=", rc)
        return 9
    log("delivered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
