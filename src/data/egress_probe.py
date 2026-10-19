"""Where does THIS instance leave the network from, and does Binance let it in? (S-607 follow-up)

Railway deploys get a Binance 451 on some instances and not others, even with the preferred region
set to Singapore (10-13 → 10-19: the same day has ok and refused `_binance_hf_loop` rows, and one
build stayed refused for two days). Nothing in the store says which egress IP an instance has, so the
question "region preference or the IP range?" cannot be answered from the data. This records it:
one `loop_attempt` row per probe with the public IP, country and network the instance sees, and the
HTTP status Binance's futures and spot hosts return to a ping. Read-only; sends no secret, no user data.
"""
from __future__ import annotations

_FAPI_PING = "https://fapi.binance.com/fapi/v1/ping"
_SPOT_PING = "https://api.binance.com/api/v3/ping"
_IP_LOOKUP = "https://ipinfo.io/json"


def classify(fapi_status: int | None, spot_status: int | None) -> tuple[str, str]:
    """(outcome, verdict) from the two ping statuses. A Binance denial is an `error` - it is the
    fault the books keep tripping over - not a quiet `refused`."""
    if fapi_status == 200:
        return "ok", "fapi reachable"
    if fapi_status == 451 or spot_status == 451:
        return "error", "binance 451: egress IP is in a restricted range"
    if fapi_status is None:
        return "error", "fapi unreachable (network error / timeout)"
    return "error", f"fapi HTTP {fapi_status}"


def summarize(ip_info: dict | None, fapi_status: int | None, spot_status: int | None) -> dict:
    info = ip_info if isinstance(ip_info, dict) else {}
    return {
        "ip": info.get("ip"), "country": info.get("country"), "region": info.get("region"),
        "city": info.get("city"), "org": str(info.get("org") or "")[:60] or None,
        "fapi_status": fapi_status, "spot_status": spot_status,
    }


async def probe() -> tuple[str, str, dict]:
    """Run the three reads. Never raises: a failed read is a None, the verdict says so."""
    import httpx

    async def _status(c, url):
        try:
            return (await c.get(url)).status_code
        except Exception:                                       # noqa: BLE001
            return None

    ip_info = None
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "cometcloud-egress-probe"}) as c:
        try:
            r = await c.get(_IP_LOOKUP)
            ip_info = r.json() if r.status_code == 200 else None
        except Exception:                                       # noqa: BLE001
            ip_info = None
        fapi, spot = await _status(c, _FAPI_PING), await _status(c, _SPOT_PING)
    outcome, verdict = classify(fapi, spot)
    detail = summarize(ip_info, fapi, spot)
    return outcome, f"{verdict} | ip={detail['ip']} {detail['country']} {detail['org']}", detail
