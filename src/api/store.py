"""
Shared state and utilities for all routers.
- Upstash Redis (CIS hot cache)
- Supabase (CIS score history)
- WebSocket ConnectionManager
- sanitize_floats helper
- Persistent httpx client pools (avoids reconnect overhead per request)
"""
import os, json, math, time
import httpx
from fastapi import WebSocket

# ── Persistent HTTP clients (reused across all requests) ──────────────────────
# Initialized lazily on first use; kept alive for the process lifetime.
_redis_client: httpx.AsyncClient | None = None
_supabase_client: httpx.AsyncClient | None = None


def _get_redis_client() -> httpx.AsyncClient:
    global _redis_client
    if _redis_client is None or _redis_client.is_closed:
        _redis_client = httpx.AsyncClient(timeout=5, limits=httpx.Limits(max_connections=20))
    return _redis_client


def _get_supabase_client() -> httpx.AsyncClient:
    global _supabase_client
    if _supabase_client is None or _supabase_client.is_closed:
        _supabase_client = httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=20))
    return _supabase_client

# ── Upstash Redis ────────────────────────────────────────────────────────────
_UPSTASH_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_REDIS_KEY     = "cis:local_scores"
_REDIS_TTL     = 7200  # 2 hours


async def redis_set(data: dict) -> bool:
    """Write CIS payload to Upstash with 2 h TTL."""
    if not _UPSTASH_URL:
        return False
    try:
        client = _get_redis_client()
        resp = await client.post(
            f"{_UPSTASH_URL}/set/{_REDIS_KEY}",
            content=json.dumps(data),
            headers={
                "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
            params={"EX": _REDIS_TTL},
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[REDIS] SET error: {e}")
        return False


async def redis_get() -> dict | None:
    """Read CIS payload from Upstash. Returns None on miss/error."""
    if not _UPSTASH_URL:
        return None
    try:
        client = _get_redis_client()
        resp = await client.get(
            f"{_UPSTASH_URL}/get/{_REDIS_KEY}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
        )
        if resp.status_code == 200:
            raw = resp.json().get("result")
            if raw:
                return json.loads(raw)
        return None
    except Exception as e:
        print(f"[REDIS] GET error: {e}")
        return None


# ── Supabase ──────────────────────────────────────────────────────────────────
_SB_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY   = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE = "cis_scores"

# Retry config
_SB_MAX_RETRIES = 3
_SB_BASE_DELAY = 1.0  # seconds


async def _supabase_request_with_retry(
    method: str,
    url: str,
    **kwargs
) -> httpx.Response | None:
    """Execute HTTP request with exponential backoff retry."""
    import asyncio

    client = _get_supabase_client()
    last_error = None

    for attempt in range(_SB_MAX_RETRIES):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in (200, 201):
                return resp
            # Non-retryable error (4xx except 429)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                print(f"[SUPABASE] Non-retryable error {resp.status_code}: {resp.text[:100]}")
                return resp
            last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)

        if attempt < _SB_MAX_RETRIES - 1:
            delay = _SB_BASE_DELAY * (2 ** attempt)  # exponential backoff
            print(f"[SUPABASE] Retry {attempt + 1}/{_SB_MAX_RETRIES} after {delay}s: {last_error}")
            await asyncio.sleep(delay)

    print(f"[SUPABASE] All retries exhausted: {last_error}")
    return None


async def supabase_insert_batch(rows: list) -> bool:
    """Bulk-insert CIS score rows into Supabase REST API with retry."""
    if not _SB_URL or not _SB_KEY or not rows:
        print("[SUPABASE] Skipped: missing config or empty rows")
        return False

    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }

    try:
        resp = await _supabase_request_with_retry(
            "POST",
            url,
            content=json.dumps(rows),
            headers=headers,
        )
        if resp and resp.status_code in (200, 201):
            print(f"[SUPABASE] Inserted {len(rows)} rows (attempt 1)")
            return True
        if resp:
            print(f"[SUPABASE] Insert failed after retries: {resp.status_code}")
        return False
    except Exception as e:
        print(f"[SUPABASE] Insert exception: {e}")
        return False


async def supabase_get_history(symbol: str, days: int = 7) -> list:
    """Read CIS score history for one symbol from Supabase with retry."""
    if not _SB_URL or not _SB_KEY:
        print("[SUPABASE] History read skipped: missing config")
        return []

    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    params = {
        "symbol":  f"eq.{symbol.upper()}",
        "order":   "recorded_at.desc",
        "limit":   str(days * 48),
        "select":  "score,grade,signal,percentile,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,source,recorded_at",
    }
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
    }

    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            data = resp.json()
            print(f"[SUPABASE] History {symbol}: {len(data)} records (last 7d)")
            return data
        if resp:
            print(f"[SUPABASE] History error {resp.status_code}: {resp.text[:100]}")
        return []
    except Exception as e:
        print(f"[SUPABASE] History exception: {e}")
        return []


# ── Float sanitizer ───────────────────────────────────────────────────────────
def sanitize_floats(obj):
    """Recursively replace NaN/Inf numpy floats with None for JSON compliance."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if hasattr(obj, 'item'):  # numpy scalar
        try:
            val = obj.item()
            return None if isinstance(val, float) and not math.isfinite(val) else val
        except Exception:
            return None
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_floats(i) for i in obj]
    return obj


# ── WebSocket connection manager ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        except (ValueError, RuntimeError):
            pass

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    def cleanup_dead(self):
        """Remove dead connections that raised errors during send."""
        self.active_connections = [c for c in self.active_connections if self._is_alive(c)]

    def _is_alive(self, websocket: WebSocket) -> bool:
        """Check if WebSocket is still connected."""
        try:
            return websocket.client_state == 1  # State.CONNECTED
        except Exception:
            return False


# Singleton — shared across all routers
ws_manager = ConnectionManager()

# Last CIS broadcast payload — sent to new subscribers on connect
last_cis_broadcast: dict | None = None
