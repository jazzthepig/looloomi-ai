"""T-095 补:Probe 关思考 + json_schema 双模型直连。

按 Seth 10-14 补充要求的顺序试 3 种关思考路径,每次回读
usage.completion_tokens_details.reasoning_tokens 必须 = 0。

用法:
    python3 research/t095/probe_thinking_off.py [model_id]

不带参数 = 探测两个模型 + 三种路径。

输出: 打印每条调用 (路径, 模型, reasoning_tokens, 完成态, content 长度, 是否过 schema 校验)
退出码: 0 = 至少一种路径在两个模型上 reasoning_tokens=0 且 schema 过;
        1 = 没有(全失败,需要换路径或换模型)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from typing import Any

BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")
MODELS = ["qwen/qwen3.5-9b", "qwen/qwen3.8-27b"]

# 单问,中性内容,不暴露日期/币名
TEST_PROMPT = (
    "Return ONLY a single JSON object with key "
    '"noul" set to a probability between 0 and 1. '
    "Question: probability that a fair coin lands heads? "
    "JSON answer:"
)
SCHEMA = {
    "type": "object",
    "properties": {"noul": {"type": "number", "minimum": 0.0, "maximum": 1.0}},
    "required": ["noul"],
    "additionalProperties": False,
}


def post_json(url: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def extract_reasoning_tokens(usage: dict[str, Any]) -> tuple[int, str]:
    """Return (n, where_found).

    Tries multiple known shapes:
      usage.completion_tokens_details.reasoning_tokens
      usage.stats.reasoning_output_tokens
    Returns -1 if unknown.
    """
    ctd = usage.get("completion_tokens_details") or {}
    if isinstance(ctd, dict) and "reasoning_tokens" in ctd:
        return int(ctd["reasoning_tokens"] or 0), "completion_tokens_details"
    stats = usage.get("stats") or {}
    if isinstance(stats, dict) and "reasoning_output_tokens" in stats:
        return int(stats["reasoning_output_tokens"] or 0), "stats.reasoning_output_tokens"
    return -1, "unknown"


def try_openai_json_schema(model: str) -> dict[str, Any]:
    """路径 ①: /v1/chat/completions + response_format json_schema strict + reasoning_effort=none."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "temperature": 0,
        "max_tokens": 256,
        "seed": 42,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "noul", "strict": True, "schema": SCHEMA},
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }
    return post_json(f"{BASE_URL}/v1/chat/completions", body)


def try_openai_json_schema_low(model: str) -> dict[str, Any]:
    """路径 ①b: /v1/chat/completions + json_schema + reasoning_effort=low(最低档)。"""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "temperature": 0,
        "max_tokens": 256,
        "seed": 42,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "noul", "strict": True, "schema": SCHEMA},
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "low",
    }
    return post_json(f"{BASE_URL}/v1/chat/completions", body)


def try_mlx_api_v1_chat(model: str) -> dict[str, Any]:
    """路径 ②: /api/v1/chat + reasoning: 'off'(该端点无 json_schema,本地校验)。"""
    body = {
        "model": model,
        "input": TEST_PROMPT,
        "temperature": 0,
        "max_tokens": 256,
        "seed": 42,
        "reasoning": "off",
    }
    return post_json(f"{BASE_URL}/api/v1/chat", body)


def try_no_think_prefix(model: str) -> dict[str, Any]:
    """路径 ③: /v1/chat/completions + json_schema + 消息开头 /no_think。"""
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": "/no_think\n" + TEST_PROMPT}
        ],
        "temperature": 0,
        "max_tokens": 256,
        "seed": 42,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "noul", "strict": True, "schema": SCHEMA},
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return post_json(f"{BASE_URL}/v1/chat/completions", body)


def schema_check_noul(parsed: Any) -> tuple[bool, str]:
    if not isinstance(parsed, dict):
        return False, f"not dict, got {type(parsed).__name__}"
    if "noul" not in parsed:
        return False, "missing 'noul' key"
    v = parsed["noul"]
    if not isinstance(v, (int, float)):
        return False, f"noul not numeric, got {type(v).__name__}"
    if not (0.0 <= float(v) <= 1.0):
        return False, f"noul {v} not in [0,1]"
    return True, f"noul={float(v):.3f}"


def try_strip_fences_parse(content: str) -> tuple[bool, str, Any]:
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        parsed = json.loads(s)
    except Exception as exc:                               # noqa: BLE001
        return False, f"json parse: {type(exc).__name__}: {str(exc)[:120]}", None
    ok, msg = schema_check_noul(parsed)
    return ok, msg, parsed


def probe(model: str, path_name: str, fn) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        resp = fn(model)
        elapsed = (time.monotonic() - t0) * 1000.0
    except Exception as exc:                               # noqa: BLE001
        return {
            "model": model,
            "path": path_name,
            "ok": False,
            "err": f"{type(exc).__name__}: {str(exc)[:160]}",
            "elapsed_ms": round((time.monotonic() - t0) * 1000.0, 1),
        }

    usage = (resp.get("usage") or {}) if isinstance(resp, dict) else {}
    rt, where = extract_reasoning_tokens(usage)
    ct = int(usage.get("completion_tokens") or 0)
    pt = int(usage.get("prompt_tokens") or 0)

    # 抽出 content
    content = ""
    if isinstance(resp, dict):
        choices = resp.get("choices")
        if isinstance(choices, list) and choices:
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content") or ""
        # /api/v1/chat 可能形态
        if not content and "output" in resp:
            content = str(resp.get("output") or "")
        if not content and "text" in resp:
            content = str(resp.get("text") or "")
        if not content and "content" in resp:
            content = str(resp.get("content") or "")

    ok_schema, msg_schema, parsed = try_strip_fences_parse(content)
    reasoning_zero = (rt == 0)

    return {
        "model": model,
        "path": path_name,
        "ok": reasoning_zero and ok_schema,
        "reasoning_tokens": rt,
        "reasoning_field": where,
        "completion_tokens": ct,
        "prompt_tokens": pt,
        "elapsed_ms": round(elapsed, 1),
        "content_len": len(content),
        "schema_ok": ok_schema,
        "schema_msg": msg_schema,
        "raw_content_head": content[:160].replace("\n", "\\n"),
    }


PATHS = [
    ("openai_json_schema_reasoning_none", try_openai_json_schema),
    ("openai_json_schema_reasoning_low", try_openai_json_schema_low),
    ("mlx_api_v1_chat_reasoning_off", try_mlx_api_v1_chat),
    ("no_think_prefix", try_no_think_prefix),
]


def main() -> int:
    target_models = sys.argv[1:] or MODELS
    print(f"# probe_thinking_off base_url={BASE_URL}")
    print(f"# target_models={target_models}")
    results = []
    for model in target_models:
        for path_name, fn in PATHS:
            r = probe(model, path_name, fn)
            results.append(r)
            print(json.dumps(r, ensure_ascii=False))
    # 总结:对每个模型,第一个通过的路径
    summary = {}
    for model in target_models:
        passing = [
            r for r in results
            if r["model"] == model and r.get("ok")
        ]
        summary[model] = [r["path"] for r in passing]
    print("\n# summary passing_paths_by_model:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 退出码
    if all(summary[m] for m in target_models):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())