"""S-842 / T-365:把私有台账的标题整理成 experiment_runs 的批次行(第一遍,只用标题)。

用法(仓库根目录;台账与输出都不进 git):
  python3 scripts/research/ledger_to_experiment_runs.py REFUTATION_LEDGER.md <输出.jsonl> [起始日期 YYYY-MM-DD]

只做能从标题里机械读出来的事:编号、日期、来源 lane、结论词。**标题里没有明确记号的一律 PENDING,数字一律留空** ——
不估、不猜;逐条核对正文、补数字是 T-365 的事。预注册 / 更正 / 裁定 / 撤回类标题不收,原因记在摘要里。
每行过一遍 `contracts/research_intake._normalize_experiment_run`,被拒的计数必须是 0。
"""
import collections
import json
import re
import sys

sys.path.insert(0, ".")
from src.api.contracts.research_intake import _normalize_experiment_run  # noqa: E402

HEAD = re.compile(r"^## ((?:S|M)-\d+[a-z]?)\s*(.*)$")
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
SKIP = (("预注册", "preregistration"), ("PRE-REGISTERED", "preregistration"), ("更正", "correction"), ("撤回", "retraction"),
        ("裁定", "ruling"), ("拍板", "ruling"), ("登记", "registration"))
RESULT_WORDS = ("结果", "❌", "✅", "REFUTED", "不成立", "结案", "复核", "复算", "补")


def lane_of(text: str) -> str:
    m = re.search(r"lane-([abc])", text)
    if m:
        return f"lane-{m.group(1)}"
    m = re.search(r"([ABC]) 道", text)
    if m:
        return f"lane-{m.group(1).lower()}"
    return "seth"


def verdict_of(text: str) -> str:
    if "❌" in text or "REFUTED" in text or "不成立" in text:
        return "REFUTED"
    if any(w in text for w in ("只报不判", "样本不够", "不可检验", "判不了", "INCONCLUSIVE", "作废")):
        return "INCONCLUSIVE"
    if any(w in text for w in ("两台引擎", "盲复算", "复算一致", "逐位对上")):
        return "REPLICATED"
    if "✅" in text:
        return "CANDIDATE"
    return "PENDING"


def main(path: str, out: str, since: str) -> None:
    rows, skipped, rejected = [], collections.Counter(), []
    seen: dict[str, int] = {}
    for line in open(path, encoding="utf-8"):
        m = HEAD.match(line.rstrip("\n"))
        if not m:
            continue
        num, rest = m.group(1), m.group(2).strip()
        dm = DATE.findall(rest)
        if not dm or max(dm) < since:
            continue
        is_result = any(w in rest[:40] for w in RESULT_WORDS) or "❌" in rest or "✅" in rest
        why = next((r for w, r in SKIP if w in rest and not is_result), None)
        if why:
            skipped[why] += 1
            continue
        seen[num] = seen.get(num, 0) + 1
        run_id = num if seen[num] == 1 else f"{num}.{seen[num]}"
        claim = re.sub(r"^[^—]*—\s*", "", rest, count=1) if "—" in rest else rest
        row = {"run_id": run_id, "kind": "ledger_index", "hypothesis": claim[:300], "verdict": verdict_of(rest),
               "ledger_ref": f"{num} {rest[:56]}", "window": None, "n_obs": None,
               "notes": f"由台账标题整理(S-842);标题日期 {max(dm)};数字未摘录,见台账正文"}
        norm, errs = _normalize_experiment_run(row, lane_of(rest), "ledger-index-s842")
        if norm is None:
            rejected.append((run_id, errs[:1]))
            continue
        rows.append({**row, "source_lane": lane_of(rest), "d": max(dm)})
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_m = collections.Counter((r["d"][:7], r["verdict"]) for r in rows)
    print(json.dumps({"rows": len(rows), "rejected": len(rejected), "skipped": dict(skipped),
                      "by_month_verdict": {f"{k[0]} {k[1]}": v for k, v in sorted(by_m.items())},
                      "by_lane": dict(collections.Counter(r["source_lane"] for r in rows))}, ensure_ascii=False, indent=1))
    assert not rejected, rejected[:3]


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "2026-09-01")
