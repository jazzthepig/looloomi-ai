"""T-095 补:4-臂回放 — 两个模型各自在各自窗口里跑 + 仅在共同窗口里横比。

臂:
  1. mech — z30 触发的机械概率(S-570 边际流动性 × BTC 趋势规则的简化版,只取 z30→p)。
  2. qwen — LocalQwenBackend 直连(strict json_schema + reasoning_effort=none + 缓存)。
  3. jev — 跳过(无 JEV_API_KEY,卡上允许"未跑")。
  4. shuffled — 1000 次置换(同一模型 qwen_p 在其每周的事件模型内交换)。

每道闸 (按 pump/dump 拆):
  Brier: mean((p - y)^2)
  规则超额: 三档(continuation / neutral / surrender),与 y 比出 +1 / 0 / -1 求和。
  打乱分位: shuffled 臂 1000 次 Brier 的 p10/p50/p90;Qwen Brier 必须 < p50 且 >= p90(只在
            shuffled 比 Qwen 好的概率上做对比)。

事件: outcomes.json(已含自收益、z30、btc 200日线、边际符号、FNG 档位、y 标签)。
  pump 的 y = y_beat_btc_30d;dump 的 y = y_pos_90d。

窗口: 9b = cutoff+2 个月(2025-06 → 2025-08);27b = cutoff+2 个月(2025-11 → 2026-01)。
共同窗口: 取两者最大起点(2026-01)→ 最新。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTCOMES = Path(
    "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-095_outcomes_2026-10-14.json"
)
CACHE_DIR = REPO_ROOT / "paper_trading" / "state" / "local_qwen_t095_replay"

# Probe-derived cutoffs (per T-095 acceptance (1) "经验截止月 = 最后一个答对率 ≥ 50% 的月").
# Both confirmed 2026-10-14: 9b = 2025-06 (15/40=37.5%, last >=50% month = 2025-06);
# 27b = 2025-11 (20/40=50.0%, last >=50% month = 2025-11). Plus 2 months buffer.
CUTOFF_MONTHS = {
    "qwen/qwen3.5-9b": ("2025-06", "2025-08-01"),
    "qwen/qwen3.8-27b": ("2025-11", "2026-01-01"),
}

SCHEMA_NOUL = {
    "type": "object",
    "properties": {"noul": {"type": "number", "minimum": 0.0, "maximum": 1.0}},
    "required": ["noul"],
    "additionalProperties": False,
}

PROMPT_TEMPLATE = (
    "You are an analyst. You receive an anonymized state describing an unnamed crypto "
    "asset at an unnamed time and must answer ONE bound probability question about it. "
    "Respond ONLY with JSON matching the schema {{noul: float in [0,1]}}.\n\n"
    "ANONYMIZED STATE (no symbol, no date, no price level):\n"
    "  asset z30 cross-sectional (z-score of trailing 30d return, sigma units): {z30}\n"
    "  asset own trailing 30d return: {r30}\n"
    "  asset own trailing 90d return: {r90}\n"
    "  asset own trailing 365d return: {r365}\n"
    "  BTC vs 200d MA: above={btc_above}, ratio (1 - close/MA200) = {btc_ratio}\n"
    "  Marginal liquidity sign (across all crypto): {mliq}\n"
    "  Fear & Greed band: {fng}\n\n"
    "QUESTION ({kind_label}): {question}\n\n"
    "JSON answer:"
)

PUMP_Q = (
    "In the next 30 calendar days, will the asset's return EXCEED Bitcoin's return?"
)
DUMP_Q = (
    "In the next 90 calendar days, will the asset's absolute return be POSITIVE (>= 0)?"
)


def model_safe(model_id: str) -> str:
    return model_id.replace("/", "_")


def cache_path(model_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{model_safe(model_id)}.jsonl"


def load_cache(model_id: str) -> dict[str, dict]:
    p = cache_path(model_id)
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["k"]] = row["resp"]
    return out


def append_cache(model_id: str, key: str, resp: dict) -> None:
    p = cache_path(model_id)
    with p.open("a") as fh:
        fh.write(json.dumps({"k": key, "resp": resp}) + "\n")


def post_json(url: str, body: dict, timeout: int = 60) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def call_model_noul(model_id: str, prompt: str) -> dict:
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 256,
        "seed": 42,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "noul_only", "strict": True, "schema": SCHEMA_NOUL},
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }
    return post_json(f"{BASE_URL}/v1/chat/completions", body)


def extract_reasoning_tokens(usage: dict) -> tuple[int, str]:
    ctd = usage.get("completion_tokens_details") or {}
    if isinstance(ctd, dict) and "reasoning_tokens" in ctd:
        return int(ctd["reasoning_tokens"] or 0), "completion_tokens_details"
    stats = usage.get("stats") or {}
    if isinstance(stats, dict) and "reasoning_output_tokens" in stats:
        return int(stats["reasoning_output_tokens"] or 0), "stats.reasoning_output_tokens"
    return -1, "unknown"


def parse_validate_noul(resp: dict) -> float:
    usage = resp.get("usage") or {}
    rt, where = extract_reasoning_tokens(usage)
    if rt != 0:
        raise RuntimeError(f"reasoning_tokens={rt} (field={where}) > 0 — abort")
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError("no choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not content.strip():
        raise RuntimeError("empty content")
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    parsed = json.loads(s)
    if not isinstance(parsed, dict) or "noul" not in parsed:
        raise RuntimeError(f"missing noul: {parsed}")
    v = float(parsed["noul"])
    return max(0.0, min(1.0, v))


def make_cache_key(model_id: str, prompt_text: str) -> str:
    h = hashlib.sha256()
    h.update(model_id.encode())
    h.update(b"|")
    h.update(prompt_text.encode())
    return h.hexdigest()


def build_prompt(ev: dict) -> tuple[str, str]:
    kind = ev["kind"]
    if kind == "pump":
        kind_label = "pump: z30>=3 (non-BTC)"
        question = PUMP_Q
    elif kind == "dump":
        kind_label = "dump: z30<=-2"
        question = DUMP_Q
    else:
        raise ValueError(f"unknown kind: {kind}")
    return (
        PROMPT_TEMPLATE.format(
            z30=round(ev["_z30"], 3),
            r30=round(ev["self_ret_30d"], 4),
            r90=round(ev["self_ret_90d"], 4),
            r365=round(ev["self_ret_365d"], 4),
            btc_above=bool(ev["btc_above_ma200"]),
            btc_ratio=round(ev["btc_ma200_ratio"], 4),
            mliq=ev["marginal_liq_sign"],
            fng=ev["fng_band"],
            kind_label=kind_label,
            question=question,
        ),
        kind,
    )


def y_field(ev: dict) -> str:
    """Pump = y_beat_btc_30d; dump = y_pos_90d."""
    return "y_beat_btc_30d" if ev["kind"] == "pump" else "y_pos_90d"


def y_of(ev: dict) -> int:
    return int(ev[y_field(ev)])


def brier(p: float, y: int) -> float:
    return (p - float(y)) ** 2


def mech_prob(ev: dict) -> float:
    """S-570 mech arm: z30 触发的固定概率。

    pump (z30 >= 3): p = clip(0.5 + 0.05 * (z30 - 3), 0.30, 0.85)
    dump (z30 <= -2): p = clip(0.5 + 0.05 * (z30 + 2), 0.15, 0.70)
    """
    z = ev["_z30"]
    if ev["kind"] == "pump":
        return max(0.30, min(0.85, 0.5 + 0.05 * (z - 3.0)))
    return max(0.15, min(0.70, 0.5 + 0.05 * (z + 2.0)))


def to_choice(p: float) -> str:
    """T-093 三档:<0.4 surrender / 0.4-0.6 neutral / >=0.6 continuation."""
    if p >= 0.6:
        return "continuation"
    if p < 0.4:
        return "surrender"
    return "neutral"


def run_arm_qwen(events: list, model_id: str, cache: dict) -> list:
    out = []
    for ev in events:
        prompt, _ = build_prompt(ev)
        key = make_cache_key(model_id, prompt)
        if key in cache:
            resp = cache[key]
        else:
            t0 = time.monotonic()
            resp = call_model_noul(model_id, prompt)
            print(f"  [call] {ev['_symbol']} {ev['_d']} {ev['kind']} z={ev['_z30']:.2f} "
                  f"elapsed={1000*(time.monotonic()-t0):.0f}ms", flush=True)
            cache[key] = resp
            append_cache(model_id, key, resp)
        p = parse_validate_noul(resp)
        out.append({**ev, "qwen_p": p, "qwen_choice": to_choice(p)})
    return out


def run_arm_mech(events: list) -> list:
    out = []
    for ev in events:
        p = mech_prob(ev)
        out.append({**ev, "qwen_p": p, "qwen_choice": to_choice(p)})
    return out


def iso_week(d: str) -> str:
    y, m, dd = d.split("-")
    iso = date(int(y), int(m), int(dd)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def shuffled_brier_stats(events: list, n_sims: int = 1000, seed: int = 20261014) -> dict:
    """Shuffle qwen_p across same-ISO-week events; recompute Brier per sim."""
    weeks: dict[str, list] = defaultdict(list)
    for ev in events:
        weeks[iso_week(ev["_d"])].append(ev)
    rng = random.Random(seed)
    sim_briers: list[float] = []
    for _ in range(n_sims):
        briers = []
        for _, evs in weeks.items():
            ps = [e["qwen_p"] for e in evs]
            rng.shuffle(ps)
            for e, p in zip(evs, ps):
                briers.append(brier(p, y_of(e)))
        sim_briers.append(sum(briers) / len(briers) if briers else float("nan"))
    s = sorted(sim_briers)
    n = len(s)
    return {
        "n_sims": n_sims,
        "median": s[n // 2],
        "p10": s[max(0, int(0.10 * n))],
        "p90": s[min(n - 1, int(0.90 * n))],
        "min": s[0],
        "max": s[-1],
    }


def rule_excess(rows: list) -> int:
    """+1 if choice matches y, -1 if opposite, 0 if neutral."""
    score = 0
    for r in rows:
        if r["qwen_choice"] == "neutral":
            continue
        y = y_of(r)
        if r["qwen_choice"] == "continuation":
            score += 1 if y == 1 else -1
        elif r["qwen_choice"] == "surrender":
            score += 1 if y == 0 else -1
    return score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--shuffled-sims", type=int, default=1000)
    args = ap.parse_args()

    if args.model_id not in CUTOFF_MONTHS:
        print(f"unknown model: {args.model_id}; expected one of {list(CUTOFF_MONTHS)}",
              file=sys.stderr)
        return 1
    cutoff_month, window_start = CUTOFF_MONTHS[args.model_id]

    print(f"[replay] model={args.model_id} cutoff={cutoff_month} window_start={window_start}",
          flush=True)

    events_all = json.loads(OUTCOMES.read_text())
    print(f"[replay] total events in outcomes: {len(events_all)}", flush=True)

    events_window = [e for e in events_all if e["_d"] >= window_start]
    print(f"[replay] events in window: {len(events_window)}", flush=True)
    pumps = [e for e in events_window if e["kind"] == "pump"]
    dumps = [e for e in events_window if e["kind"] == "dump"]
    print(f"[replay] pumps={len(pumps)} dumps={len(dumps)}", flush=True)

    # ── Mech ──
    mech_rows = run_arm_mech(events_window)

    # ── Qwen ──
    cache = load_cache(args.model_id)
    print(f"[replay] qwen cache: {len(cache)} pre-existing entries", flush=True)
    qwen_rows = run_arm_qwen(events_window, args.model_id, cache)

    def avg_brier(rows):
        if not rows:
            return float("nan")
        return sum(brier(r["qwen_p"], y_of(r)) for r in rows) / len(rows)

    pump_mech = [r for r in mech_rows if r["kind"] == "pump"]
    dump_mech = [r for r in mech_rows if r["kind"] == "dump"]
    pump_qwen = [r for r in qwen_rows if r["kind"] == "pump"]
    dump_qwen = [r for r in qwen_rows if r["kind"] == "dump"]

    mech_pump_b = avg_brier(pump_mech)
    mech_dump_b = avg_brier(dump_mech)
    qwen_pump_b = avg_brier(pump_qwen)
    qwen_dump_b = avg_brier(dump_qwen)

    # Shuffled (on Qwen) per kind
    pump_shuf = shuffled_brier_stats(pump_qwen, n_sims=args.shuffled_sims)
    dump_shuf = shuffled_brier_stats(dump_qwen, n_sims=args.shuffled_sims)

    # Qwen vs shuffled: count sims where sim_brier < qwen_brier
    def qwen_pctile(rows, kind_label, n_sims):
        weeks: dict[str, list] = defaultdict(list)
        for r in rows:
            weeks[iso_week(r["_d"])].append(r)
        rng = random.Random(20261014)
        worse = 0
        for _ in range(n_sims):
            sim_b = 0.0
            n = 0
            for _, evs in weeks.items():
                ps = [e["qwen_p"] for e in evs]
                rng.shuffle(ps)
                for e, p in zip(evs, ps):
                    sim_b += brier(p, y_of(e))
                    n += 1
            sim_avg = sim_b / n if n else float("nan")
            qwen_avg = avg_brier(rows)
            if sim_avg < qwen_avg:
                worse += 1
        return worse / n_sims

    pump_pctile = qwen_pctile(pump_qwen, "pump", args.shuffled_sims) if pump_qwen else float("nan")
    dump_pctile = qwen_pctile(dump_qwen, "dump", args.shuffled_sims) if dump_qwen else float("nan")

    # Continuation / surrender frequencies (Qwen)
    pump_cont_freq_qwen = (
        sum(1 for r in pump_qwen if r["qwen_choice"] == "continuation") / max(1, len(pump_qwen))
    )
    dump_surr_freq_qwen = (
        sum(1 for r in dump_qwen if r["qwen_choice"] == "surrender") / max(1, len(dump_qwen))
    )

    summary = {
        "task": "T-095 replay (补, two-model windows)",
        "model": args.model_id,
        "cutoff_month": cutoff_month,
        "window_start": window_start,
        "n_events_window": len(events_window),
        "n_pumps": len(pumps),
        "n_dumps": len(dumps),
        "base_rates": {
            "pump_actual_continue_rate": sum(y_of(p) for p in pumps) / max(1, len(pumps)),
            "dump_actual_pos_rate": sum(y_of(p) for p in dumps) / max(1, len(dumps)),
        },
        "brier": {
            "pump_mech": mech_pump_b,
            "pump_qwen": qwen_pump_b,
            "pump_delta_qwen_minus_mech": qwen_pump_b - mech_pump_b,
            "dump_mech": mech_dump_b,
            "dump_qwen": qwen_dump_b,
            "dump_delta_qwen_minus_mech": qwen_dump_b - mech_dump_b,
        },
        "shuffled": {
            "pump": pump_shuf,
            "dump": dump_shuf,
            "pump_qwen_pctile_beats_shuffled": round(pump_pctile, 4),
            "dump_qwen_pctile_beats_shuffled": round(dump_pctile, 4),
            "interpretation": (
                "pctile = fraction of 1000 shuffles where sim_brier < qwen_brier. "
                "HIGH pctile = shuffled does WORSE than qwen = qwen BETTER than random. "
                "Per card acceptance (4): qwen Brier must beat mech AND be <= 10th percentile "
                "of shuffled (i.e. pctile >= 0.90)."
            ),
        },
        "rule_excess": {
            "pump_mech": rule_excess(pump_mech),
            "pump_qwen": rule_excess(pump_qwen),
            "dump_mech": rule_excess(dump_mech),
            "dump_qwen": rule_excess(dump_qwen),
        },
        "freq": {
            "pump_qwen_continuation_freq": pump_cont_freq_qwen,
            "dump_qwen_surrender_freq": dump_surr_freq_qwen,
            "pump_qwen_n": len(pump_qwen),
            "dump_qwen_n": len(dump_qwen),
        },
        "per_event": [
            {k: r.get(k) for k in
             ("_d", "_symbol", "kind", "_z30", "qwen_p", "qwen_choice",
              "y_beat_btc_30d", "y_pos_90d")}
            for r in qwen_rows
        ],
    }

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"[replay] wrote {args.out_json}", flush=True)
    else:
        print(json.dumps(
            {k: v for k, v in summary.items() if k != "per_event"},
            indent=2, ensure_ascii=False,
        ), flush=True)

    print(f"\n[replay] DONE: model={args.model_id} "
          f"pump_brier qwen={qwen_pump_b:.4f} mech={mech_pump_b:.4f} "
          f"dump_brier qwen={qwen_dump_b:.4f} mech={mech_dump_b:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())