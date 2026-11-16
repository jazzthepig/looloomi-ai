"""T-365 第 3 轮探针 v2。

两件事:
 1) patch 24 行 → 主文件里的 d(月份)归属,确认前两轮各自做了哪个月;
 2) 目标月的每个台账小节:抽前 N 行里的「结论信号行」(预注册 / 更正 / 结果 / 判据 / 数字),
    用来把 100 多条候选池缩到「结果类」那十几条。

用法:
  python3 docs/research/_t365_round3.py map
  python3 docs/research/_t365_round3.py scan 2026-09 [每节行数]
"""
import json
import os
import re
import sys

LEDGER = "/Users/sbb/Projects/looloomi-ai/REFUTATION_LEDGER.md"
MAIN = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/experiment_runs_backfill.jsonl"
PATCH = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/experiment_runs_backfill_patch.jsonl"

SIG = re.compile(
    r"(预注册|更正|复核|结果|判据|判定|结论|REFUT|REPLIC|CANDIDAT|INCONCLUS|PENDING|"
    r"❌|✅|🔴|🟡|⚪|未过|通过|推翻|不判|只报|审计|记录)"
)
NUM = re.compile(r"(total_return|max_dd|sharpe|Sharpe|t=|p=|p_value|胜率|命中率|年化|回撤|超额|%)")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def ledger_sections():
    """{run_id: (lineno, title, body_lines)} —— body 只取标题后 25 行。"""
    out = {}
    cur, body = None, []
    with open(LEDGER, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            m = re.match(r"^## ((?:S|M)-\d+(?:\.\d+)?)[ \t]*(.*)$", line)
            if m:
                if cur:
                    out[cur] = (out[cur][0], out[cur][1], body[:25])
                cur, body = m.group(1), []
                out[cur] = (i, m.group(2).rstrip(), [])
                continue
            if cur and len(body) < 25:
                body.append(line.rstrip())
    if cur:
        out[cur] = (out[cur][0], out[cur][1], body[:25])
    return out


def do_map():
    main_rows = {r["run_id"]: r for r in load_jsonl(MAIN)}
    for r in load_jsonl(PATCH):
        m = main_rows.get(r["run_id"], {})
        print(f"{r['run_id']:9s} d={str(m.get('d')):12s} lane={str(m.get('source_lane')):9s} "
              f"verdict={r.get('verdict')}")


def do_scan(month, nlines):
    led = ledger_sections()
    main_rows = load_jsonl(MAIN)
    patched = {r["run_id"] for r in load_jsonl(PATCH)}
    month_rows = [r for r in main_rows if str(r.get("d", "")).startswith(month)]
    print(f"# {month}: {len(month_rows)} 行")
    for r in month_rows:
        rid = r["run_id"]
        sec = led.get(rid)
        if not sec:
            print(f"{rid}: (台账无此节)")
            continue
        lineno, title, body = sec
        hits = []
        for b in body[:nlines]:
            b = b.strip()
            if b and (SIG.search(b) or NUM.search(b)):
                hits.append(b[:150])
        tag = "PATCH" if rid in patched else "    "
        print(f"--- {rid} L{lineno} [{tag}] {title[:80]}")
        for h in hits[:4]:
            print(f"      {h}")


PRE = re.compile(r"(预注册|更正|补记|复核更正|勘误)")
RES = re.compile(r"(推翻|判据|结论|结果|未过|通过|REFUT|REPLIC|INCONCLUS|CANDIDAT|"
                 r"❌|✅|🔴|🟡|⚪|不判|只报|假说|检验|回放|回测)")
SKIP = re.compile(r"(审计|工程|故障|部署|记录|清单|体检|普查|盘点|清册|排期|"
                   r"动线|治理|流程|规范|口径提醒)")


def do_pick(month, nlines):
    """按上一轮口径挑「结果类」:非预注册/更正,且正文前 nlines 行有结果信号。"""
    led = ledger_sections()
    main_rows = load_jsonl(MAIN)
    patched = {r["run_id"] for r in load_jsonl(PATCH)}
    month_rows = [r for r in main_rows if str(r.get("d", "")).startswith(month)]
    picked, skipped = [], []
    for r in month_rows:
        rid = r["run_id"]
        sec = led.get(rid)
        if not sec:
            skipped.append((rid, "台账无节"))
            continue
        lineno, title, body = sec
        head = title + " " + " ".join(body[:nlines])
        if PRE.search(head):
            skipped.append((rid, "预注册/更正"))
            continue
        hit = [b.strip()[:130] for b in body[:nlines]
               if b.strip() and RES.search(b)]
        if hit:
            picked.append((rid, lineno, title, hit[:2], rid in patched))
        else:
            skipped.append((rid, "前 %d 行无结果信号" % nlines))
    print(f"# {month}: 总 {len(month_rows)} → 候选 {len(picked)} / 跳过 {len(skipped)}")
    for rid, lineno, title, hit, in_patch in picked:
        print(f"{rid:9s} L{lineno:<6d} {'PATCH' if in_patch else '     '} {title[:72]}")
        for h in hit:
            print(f"          {h}")
    print("\n# 跳过原因分布:")
    import collections
    for k, v in collections.Counter(s[1] for s in skipped).most_common():
        print(f"  {v:3d}  {k}")


def do_titles(month):
    """整月标题列表(一行一条)—— 人工挑结果类。"""
    led = ledger_sections()
    main_rows = load_jsonl(MAIN)
    patched = {r["run_id"] for r in load_jsonl(PATCH)}
    month_rows = [r for r in main_rows if str(r.get("d", "")).startswith(month)]
    print(f"# {month}: {len(month_rows)} 行")
    for i, r in enumerate(month_rows):
        rid = r["run_id"]
        sec = led.get(rid)
        ln = sec[0] if sec else None
        title = sec[1] if sec else "(台账无节)"
        print(f"{i:3d} {rid:9s} L{str(ln):6s} {'PATCH' if rid in patched else '     '} {title[:88]}")


def do_review(nlines):
    """patch 全部行:台账小节正文里的「结论句」,用来按尺子 v2 复核。"""
    led = ledger_sections()
    patch_rows = load_jsonl(PATCH)
    main_rows = {r["run_id"]: r for r in load_jsonl(MAIN)}
    for r in patch_rows:
        rid = r["run_id"]
        sec = led.get(rid)
        m = main_rows.get(rid, {})
        print(f"\n=== {rid} | patch.verdict={r.get('verdict')} | 主文件 lane={m.get('source_lane')} d={m.get('d')}")
        if not sec:
            print("   (台账无节)")
            continue
        ln, title, body = sec
        print(f"   L{ln} {title[:100]}")
        for b in body[:nlines]:
            b = b.strip()
            if b and (SIG.search(b) or NUM.search(b)):
                print(f"   > {b[:150]}")


if __name__ == "__main__":
    if sys.argv[1] == "map":
        do_map()
    elif sys.argv[1] == "pick":
        do_pick(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    elif sys.argv[1] == "titles":
        do_titles(sys.argv[2])
    elif sys.argv[1] == "review":
        do_review(int(sys.argv[2]) if len(sys.argv) > 2 else 25)
    else:
        do_scan(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10)
