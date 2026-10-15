"""T-095 补:污染探针 — 两个模型各自跑 40 题,带 reasoning_tokens=0 + schema 校验。

验收门槛(任何一次不满足就 abort):
  - usage.completion_tokens_details.reasoning_tokens 必须 = 0
  - JSON 必须过 strict json_schema (answer_index ∈ {0,1,2,3} + confidence ∈ [0,1])
  - 不重试成默认值

缓存键 = (model_id, sha256(prompt_dict))。磁盘缓存写到
paper_trading/state/local_qwen_t095_probe/<model_safe>.jsonl。
支持断点续跑:启动时先扫已有缓存行,跳过已经答对的题。

用法:
    python3 research/t095/run_probe.py <model_id> [--out-json PATH]
例:
    python3 research/t095/run_probe.py qwen/qwen3.5-9b
    python3 research/t095/run_probe.py qwen/qwen3.8-27b
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")

# 仓库根 = lane-a worktree 根
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE_QUESTIONS = Path(
    "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-095_probe_questions_2026-10-14.json"
)
CACHE_DIR = REPO_ROOT / "paper_trading" / "state" / "local_qwen_t095_probe"
SCHEMA = {
    "type": "object",
    "properties": {
        "answer_index": {"type": "integer", "minimum": 0, "maximum": 3},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["answer_index", "confidence"],
    "additionalProperties": False,
}


def model_safe(model_id: str) -> str:
    return model_id.replace("/", "_")


def cache_path(model_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{model_safe(model_id)}.jsonl"


def load_cache(model_id: str) -> dict[str, dict]:
    """Map cache_key → raw API response (already validated once)."""
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


def extract_reasoning_tokens(usage: dict) -> tuple[int, str]:
    ctd = usage.get("completion_tokens_details") or {}
    if isinstance(ctd, dict) and "reasoning_tokens" in ctd:
        return int(ctd["reasoning_tokens"] or 0), "completion_tokens_details"
    stats = usage.get("stats") or {}
    if isinstance(stats, dict) and "reasoning_output_tokens" in stats:
        return int(stats["reasoning_output_tokens"] or 0), "stats.reasoning_output_tokens"
    return -1, "unknown"


def make_cache_key(model_id: str, prompt_dict: dict) -> str:
    h = hashlib.sha256()
    h.update(model_id.encode())
    h.update(b"|")
    h.update(json.dumps(prompt_dict, sort_keys=True).encode())
    return h.hexdigest()


def call_model(model_id: str, prompt_text: str) -> dict:
    """Path ① (only working path per probe_thinking_off.py 2026-10-14):

    /v1/chat/completions + response_format json_schema strict + reasoning_effort=none +
    chat_template_kwargs.enable_thinking=false + temperature=0 + seed=42 + max_tokens=256.
    Returns full API response (must pass reasoning_tokens=0 + schema validation downstream).
    """
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt_text}],
        "temperature": 0,
        "max_tokens": 256,
        "seed": 42,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "probe_q", "strict": True, "schema": SCHEMA},
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }
    return post_json(f"{BASE_URL}/v1/chat/completions", body)


def parse_and_validate(resp: dict) -> dict:
    """Return parsed {"answer_index": int, "confidence": float} or raise."""
    usage = resp.get("usage") or {}
    rt, where = extract_reasoning_tokens(usage)
    if rt != 0:
        raise RuntimeError(
            f"reasoning_tokens={rt} (field={where}) > 0 — must abort, NOT fallback"
        )
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError("no choices in response")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("content empty")
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    parsed = json.loads(s)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"top-level not dict, got {type(parsed).__name__}")
    if "answer_index" not in parsed or "confidence" not in parsed:
        raise RuntimeError(f"missing required keys: {list(parsed.keys())}")
    ai = parsed["answer_index"]
    cf = parsed["confidence"]
    if not isinstance(ai, int) or ai not in (0, 1, 2, 3):
        raise RuntimeError(f"answer_index not in {{0,1,2,3}}: {ai!r}")
    if not isinstance(cf, (int, float)) or not (0.0 <= float(cf) <= 1.0):
        raise RuntimeError(f"confidence not in [0,1]: {cf!r}")
    return {"answer_index": int(ai), "confidence": float(cf)}


def build_prompt(q: dict) -> str:
    """Single-question prompt. No system msg. Per Seth: 不塞多个事件,一次一问。"""
    opts = q["options"]
    opts_text = "\n".join(f"  {i}. {o}" for i, o in enumerate(opts))
    return (
        "You are an analyst answering ONE bound multiple-choice question about a "
        "specific historical month. The question has a single correct option from "
        "the list. Respond ONLY with a single JSON object using the schema:\n"
        '{"answer_index": <0-3>, "confidence": <float 0-1>}\n\n'
        f"QUESTION (month={q['month']}): {q['q']}\n"
        f"OPTIONS:\n{opts_text}\n\n"
        "JSON answer:"
    )


def experience_cutoff_month(per_month: list[dict]) -> str | None:
    """Last month with acc_rate >= 0.5 (per T-095 acceptance (1)).

    Walk from oldest → newest, but keep the LAST passing one.
    Note: single-question months are noisy (1/1 = 100% or 0/1 = 0%); we use ≥0.5 as
    the threshold and require n_total >= 1 (always true here).
    """
    passing = [r for r in per_month if r["acc_rate"] >= 0.5]
    if not passing:
        return None
    return passing[-1]["month"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id", help="qwen/qwen3.5-9b or qwen/qwen3.8-27b")
    ap.add_argument("--out-json", default=None,
                    help="where to write per-question results (default: stdout summary only)")
    ap.add_argument("--limit", type=int, default=None, help="only first N questions (for testing)")
    args = ap.parse_args()

    questions_blob = json.loads(PROBE_QUESTIONS.read_text())
    questions = questions_blob["questions"]
    if args.limit:
        questions = questions[: args.limit]

    print(f"[probe] model={args.model_id} base_url={BASE_URL}", flush=True)
    print(f"[probe] n_questions={len(questions)} cache={cache_path(args.model_id)}", flush=True)

    cache = load_cache(args.model_id)
    print(f"[probe] cached_responses={len(cache)}", flush=True)

    per_q: list[dict] = []
    for q in questions:
        prompt = build_prompt(q)
        prompt_dict = {"model": args.model_id, "prompt": prompt}
        key = make_cache_key(args.model_id, prompt_dict)

        # 命中缓存 — replay (already validated; re-parse to refresh correctness vs Q)
        if key in cache:
            resp = cache[key]
            validated = parse_and_validate(resp)
            correct = int(validated["answer_index"] == q["answer"])
            per_q.append({
                "id": q["id"], "month": q["month"], "kind": q["kind"],
                "true_answer": q["answer"],
                "model_answer_index": validated["answer_index"],
                "confidence": round(validated["confidence"], 4),
                "correct": correct,
                "cached": True,
            })
            print(f"  [cache-hit] {q['id']} {q['month']} → {validated['answer_index']} "
                  f"({'OK' if correct else 'X'})", flush=True)
            continue

        t0 = time.monotonic()
        try:
            resp = call_model(args.model_id, prompt)
        except Exception as exc:                             # noqa: BLE001
            print(f"  [ABORT] {q['id']} {q['month']}: HTTP/parse fail: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return 2
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        # 验收门槛 — 任何不满足立即 abort
        try:
            validated = parse_and_validate(resp)
        except Exception as exc:                             # noqa: BLE001
            print(f"  [ABORT] {q['id']} {q['month']}: validation fail: {exc}", flush=True)
            return 3

        correct = int(validated["answer_index"] == q["answer"])
        append_cache(args.model_id, key, resp)
        usage = resp.get("usage") or {}
        ct = int(usage.get("completion_tokens") or 0)
        pt = int(usage.get("prompt_tokens") or 0)
        per_q.append({
            "id": q["id"], "month": q["month"], "kind": q["kind"],
            "true_answer": q["answer"],
            "model_answer_index": validated["answer_index"],
            "confidence": round(validated["confidence"], 4),
            "correct": correct,
            "cached": False,
            "elapsed_ms": round(elapsed_ms, 1),
            "completion_tokens": ct,
            "prompt_tokens": pt,
        })
        print(f"  [fresh] {q['id']} {q['month']} → {validated['answer_index']} "
              f"({'OK' if correct else 'X'}) elapsed_ms={elapsed_ms:.0f} "
              f"tokens={pt}+{ct}", flush=True)

    # 汇总
    n_correct = sum(r["correct"] for r in per_q)
    n_total = len(per_q)
    overall_acc = n_correct / n_total if n_total else 0.0

    # per-month
    months: dict[str, dict] = {}
    for r in per_q:
        m = months.setdefault(r["month"], {"month": r["month"], "n_correct": 0, "n_total": 0})
        m["n_correct"] += r["correct"]
        m["n_total"] += 1
    per_month = []
    for m in sorted(months.values(), key=lambda x: x["month"]):
        m["acc_rate"] = round(m["n_correct"] / m["n_total"], 4) if m["n_total"] else 0.0
        per_month.append(m)
    cutoff = experience_cutoff_month(per_month)

    summary = {
        "task": "T-095 contamination probe (补)",
        "model": args.model_id,
        "backend_name": "local_qwen_lmstudio_strict",
        "n_questions": n_total,
        "n_correct": n_correct,
        "overall_acc": round(overall_acc, 4),
        "experience_cutoff_month": cutoff,
        "per_month": per_month,
        "per_question": per_q,
        "acceptance_gates": {
            "reasoning_tokens_required_zero": True,
            "json_schema_strict_required": True,
            "fallback_on_failure": "abort (no defaults)",
            "seed": 42,
            "temperature": 0,
            "max_tokens": 256,
        },
    }

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"[probe] wrote {args.out_json}", flush=True)
    else:
        print(json.dumps(
            {k: v for k, v in summary.items() if k != "per_question"},
            indent=2, ensure_ascii=False
        ), flush=True)

    print(f"\n[probe] DONE: model={args.model_id} acc={n_correct}/{n_total}={overall_acc:.1%} "
          f"cutoff={cutoff}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())