"""src/mcp/lmstudio_bridge.js v2 against a mock LM Studio (2026-10-14).

v1 picked `/v1/models[0]` when two models were loaded, "turned thinking off" with parameters LM Studio
ignores (three real calls spent their whole budget thinking), and put the compliance block into every
prompt. These tests pin the v2 contract: never guess the model, verify reasoning=off from the tokens
actually spent, validate judgments instead of defaulting, compliance only where text can reach users.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "src" / "mcp" / "lmstudio_bridge.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

M9 = {"type": "llm", "key": "qwen/qwen3.5-9b", "display_name": "Qwen3.5 9B", "params_string": "9B",
      "quantization": {"name": "Q4_K_M"}, "format": "gguf", "max_context_length": 262144,
      "loaded_instances": [{"id": "qwen/qwen3.5-9b", "config": {"context_length": 262144}}],
      "capabilities": {"reasoning": {"allowed_options": ["off", "on"], "default": "on"}}}
M27 = {**M9, "key": "qwen/qwen3.8-27b", "display_name": "Qwen3.8 27B",
       "loaded_instances": [{"id": "qwen/qwen3.8-27b", "config": {"context_length": 119552}}]}
UNLOADED = {**M9, "key": "other/model", "loaded_instances": []}
ON_ONLY = {**M9, "key": "think/only", "loaded_instances": [{"id": "think/only", "config": {}}],
           "capabilities": {"reasoning": {"allowed_options": ["on"], "default": "on"}}}


class Mock:
    def __init__(self):
        self.models = [M9, M27, UNLOADED]
        self.completions = "clean"   # clean | thinks | out_of_range | http400
        self.rest = "clean"          # clean | thinks
        self.answer = {"q1": 0.25, "phase": "stabilising"}
        self.requests: list[tuple[str, dict]] = []


def _server(mock: Mock):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            mock.requests.append(("GET " + self.path, {}))
            if self.path == "/api/v1/models":
                self._send(200, {"models": mock.models})
            else:
                self._send(404, {"error": "nope"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            mock.requests.append(("POST " + self.path, body))
            if self.path == "/v1/chat/completions":
                if mock.completions == "http400":
                    return self._send(400, {"error": "unknown field reasoning_effort"})
                ans = dict(mock.answer)
                if mock.completions == "out_of_range":
                    ans["q1"] = 1.3
                thinks = mock.completions == "thinks"
                return self._send(200, {
                    "choices": [{"message": {"content": json.dumps(ans),
                                             **({"reasoning_content": "let me think"} if thinks else {})},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                              "completion_tokens_details": {"reasoning_tokens": 50 if thinks else 0}}})
            if self.path == "/api/v1/chat":
                thinks = mock.rest == "thinks"
                out = ([{"type": "reasoning", "content": "hmm"}] if thinks else []) + \
                      [{"type": "message", "content": "```json\n" + json.dumps(mock.answer) + "\n```"
                        if "QUESTIONS" in body.get("input", "") else "plain answer"}]
                return self._send(200, {"output": out, "stats": {"input_tokens": 90, "total_output_tokens": 15,
                                                                 "reasoning_output_tokens": 40 if thinks else 0}})
            self._send(404, {"error": "nope"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def lm():
    mock = Mock()
    srv = _server(mock)
    yield mock, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base: str, *calls: tuple[str, dict], env: dict | None = None) -> list[dict]:
    """Run the bridge once, send initialize + tools/call messages, return the tools/call results in order."""
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}]
    for i, (name, args) in enumerate(calls, start=1):
        msgs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}})
    e = {**os.environ, "LMSTUDIO_BASE": base, "LMSTUDIO_MODEL": ""}
    e.update(env or {})
    # One message per line, sequentially: the bridge learns per-model paths across calls.
    proc = subprocess.Popen([NODE, str(BRIDGE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=e)
    out = []
    for m in msgs:
        proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()
        out.append(json.loads(proc.stdout.readline()))
    proc.stdin.close()
    proc.wait(timeout=20)
    assert out[0]["result"]["serverInfo"]["version"].startswith("2.")
    return [o["result"] for o in out[1:]]


def text(res: dict) -> str:
    return res["content"][0]["text"]


def posts(mock: Mock, path: str) -> list[dict]:
    return [b for p, b in mock.requests if p == "POST " + path]


Q = {"q1": {"type": "probability", "instructions": "Pump continues?"},
     "phase": {"type": "choice", "instructions": "Liquidity phase", "options": ["easing", "worsening", "stabilising", "weakening"]}}


def test_tool_descriptions_name_no_model(lm):
    _mock, base = lm
    proc = subprocess.run([NODE, str(BRIDGE)], input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
                          capture_output=True, text=True, env={**os.environ, "LMSTUDIO_BASE": base}, timeout=20)
    tools = json.loads(proc.stdout.splitlines()[0])["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"lmstudio_models", "lmstudio_judge", "lmstudio_chat", "lmstudio_analyze"} <= names
    blob = json.dumps(tools).lower()
    for stale in ("gemma", "qwen", "35b", "26b"):
        assert stale not in blob, f"tool descriptions must not name a model ({stale}) — v1 named one that was not loaded"


def test_refuses_to_guess_between_two_loaded_models(lm):
    mock, base = lm
    [res] = call(base, ("lmstudio_chat", {"prompt": "hi"}))
    assert res.get("isError") and "qwen/qwen3.5-9b" in text(res) and "qwen/qwen3.8-27b" in text(res)
    assert "other/model" not in text(res), "a downloaded but unloaded model is not a candidate"
    assert not posts(mock, "/api/v1/chat") and not posts(mock, "/v1/chat/completions")


def test_env_default_and_unloaded_model(lm):
    mock, base = lm
    ok, bad = call(base, ("lmstudio_chat", {"prompt": "hi"}), ("lmstudio_chat", {"prompt": "hi", "model": "other/model"}),
                   env={"LMSTUDIO_MODEL": "qwen/qwen3.8-27b"})
    assert not ok.get("isError") and "model=qwen/qwen3.8-27b" in text(ok)
    assert bad.get("isError") and "not loaded" in text(bad)
    req = posts(mock, "/api/v1/chat")[0]
    assert req["model"] == "qwen/qwen3.8-27b" and req["reasoning"] == "off" and req["store"] is False


def test_judge_schema_path_when_reasoning_is_really_off(lm):
    mock, base = lm
    [res] = call(base, ("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "z30=3.4; BTC above 200d", "questions": Q}))
    assert not res.get("isError"), text(res)
    out = json.loads(text(res))
    assert out["answers"] == {"q1": 0.25, "phase": "stabilising"}
    assert out["meta"]["path"] == "v1/chat/completions" and out["meta"]["reasoning_tokens"] == 0
    assert len(out["meta"]["prompt_sha256"]) == 64
    req = posts(mock, "/v1/chat/completions")[0]
    assert req["response_format"]["type"] == "json_schema" and req["response_format"]["json_schema"]["strict"] is True
    schema = req["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["q1"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert schema["properties"]["phase"]["enum"][0] == "easing" and schema["additionalProperties"] is False
    assert req["temperature"] == 0 and req["seed"] == 7
    assert "COMPLIANCE" not in json.dumps(req), "the judge returns numbers; no compliance block"


def test_judge_falls_back_when_the_schema_path_still_reasons_and_remembers(lm):
    mock, base = lm
    mock.completions = "thinks"
    first, second = call(base, *[("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "s", "questions": Q})] * 2)
    for res in (first, second):
        assert not res.get("isError"), text(res)
        assert json.loads(text(res))["meta"]["path"] == "api/v1/chat"
    assert "reasoned despite off" in json.dumps(json.loads(text(first))["meta"]["fallbacks"])
    assert len(posts(mock, "/v1/chat/completions")) == 1, "second call goes straight to the path that works"
    rest = posts(mock, "/api/v1/chat")
    assert len(rest) == 2 and all(r["reasoning"] == "off" for r in rest)
    assert '"additionalProperties":false' in rest[0]["system_prompt"], "schema travels in the prompt on this path"


def test_judge_falls_back_when_the_schema_path_rejects_the_request(lm):
    mock, base = lm
    mock.completions = "http400"
    [res] = call(base, ("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "s", "questions": Q}))
    assert not res.get("isError"), text(res)
    assert json.loads(text(res))["meta"]["path"] == "api/v1/chat"


def test_judge_refuses_when_both_paths_reason(lm):
    mock, base = lm
    mock.completions, mock.rest = "thinks", "thinks"
    [res] = call(base, ("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "s", "questions": Q}))
    assert res.get("isError") and "reasoned although" in text(res)


def test_judge_validates_instead_of_defaulting(lm):
    mock, base = lm
    mock.completions = "out_of_range"
    [res] = call(base, ("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "s", "questions": Q}))
    assert res.get("isError") and "not a probability" in text(res)
    mock.completions, mock.answer = "clean", {"q1": 0.4, "phase": "sideways"}
    [res] = call(base, ("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "s", "questions": Q}))
    assert res.get("isError") and "not one of" in text(res)
    mock.answer = {"q1": 0.4, "phase": "easing", "extra": 1}
    [res] = call(base, ("lmstudio_judge", {"model": "qwen/qwen3.5-9b", "state": "s", "questions": Q}))
    assert res.get("isError") and "unexpected key" in text(res)


def test_reasoning_level_the_model_does_not_allow_is_an_error(lm):
    mock, base = lm
    mock.models = [ON_ONLY]
    [res] = call(base, ("lmstudio_judge", {"state": "s", "questions": Q}))
    assert res.get("isError") and "does not allow" in text(res)
    assert not posts(mock, "/v1/chat/completions") and not posts(mock, "/api/v1/chat")


def test_compliance_only_where_text_can_reach_users(lm):
    mock, base = lm
    call(base,
         ("lmstudio_chat", {"prompt": "fact?", "model": "qwen/qwen3.5-9b", "compliance": False}),
         ("lmstudio_chat", {"prompt": "view?", "model": "qwen/qwen3.5-9b"}),
         ("lmstudio_cis_narrative", {"scorecard": "| BTC | 70 |", "model": "qwen/qwen3.5-9b"}),
         ("lmstudio_macro_brief", {"macro_data": {"fng": 50}, "model": "qwen/qwen3.5-9b"}))
    sys_prompts = [r.get("system_prompt", "") for r in posts(mock, "/api/v1/chat")]
    assert "COMPLIANCE" not in sys_prompts[0]
    assert all("COMPLIANCE" in s for s in sys_prompts[1:])


def test_default_base_is_ipv4():
    src = BRIDGE.read_text(encoding="utf-8")
    assert "LMSTUDIO_BASE || 'http://127.0.0.1:1234'" in src, "localhost can resolve to ::1, which LM Studio does not serve"
