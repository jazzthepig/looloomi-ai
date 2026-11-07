"""11-07:AI 简报循环 24 小时 37 次 refused,原因只有「model returned no compliant narrative」—— 三种成因要分开说。
推理模型先想再答:45 秒默认时限 / 4,000 token 不够,简报这一路给 180 秒 / 8,000。"""
import asyncio

from src.data.narrative import llm_narrator as ln

FACTS = {"regime": "Tightening", "items": [{"id": "a", "symbol": "BTC"}, {"id": "b", "symbol": "ETH"}]}


def _run(monkeypatch, reply, finish="stop"):
    seen = {}

    async def chat(messages, temperature=0.4, max_tokens=1400, timeout=None):
        seen.update(max_tokens=max_tokens, timeout=timeout)
        ln.LAST_CALL.update(finish_reason=finish, chars=len(reply or ""))
        return reply
    monkeypatch.setattr(ln, "_BASE", "https://x")
    monkeypatch.setattr(ln, "_chat", chat)
    return asyncio.run(ln.compose_ai_briefing(FACTS)), seen


def test_briefing_gets_a_reasoning_model_budget(monkeypatch):
    out, seen = _run(monkeypatch, '{"headline": "Breadth leads", "items": {"a": "BTC leads on breadth.", "b": "ETH lags."}}')
    assert out and out["coverage"] == "2/2" and seen["timeout"] >= 120 and seen["max_tokens"] >= 8000
    assert ln.LAST_COMPOSE_WHY["why"] is None


def test_truncated_reply_says_truncated(monkeypatch):
    out, _ = _run(monkeypatch, '<think>long</think>{"headline": "x", "items": {"a": "BTC le', finish="length")
    assert out is None and "finish_reason=length" in ln.LAST_COMPOSE_WHY["why"]


def test_no_response_and_all_rejected_are_told_apart(monkeypatch):
    ln.LAST_ERROR["why"] = "ReadTimeout: "
    out, _ = _run(monkeypatch, None)
    assert out is None and ln.LAST_COMPOSE_WHY["why"].startswith("no response: ReadTimeout")
    out, _ = _run(monkeypatch, '{"headline": "h", "items": {"a": "Investors should buy BTC.", "b": "Reduce ETH."}}')
    assert out is None and "compliance filter" in ln.LAST_COMPOSE_WHY["why"] and "buy" in ln.LAST_COMPOSE_WHY["why"]
