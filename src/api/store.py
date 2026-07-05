"""
Shared state and utilities for all routers.
- Upstash Redis (CIS hot cache)
- Supabase (CIS score history)
- WebSocket ConnectionManager
- sanitize_floats helper
- Persistent httpx client pools (avoids reconnect overhead per request)
"""
import logging
import os, json, math, time
import httpx
from fastapi import WebSocket

_logger = logging.getLogger(__name__)

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
    return await redis_set_key(_REDIS_KEY, data, ttl=_REDIS_TTL)


async def redis_get() -> dict | None:
    """Read CIS payload from Upstash. Returns None on miss/error."""
    return await redis_get_key(_REDIS_KEY)


# ── Generic key-based Redis helpers ──────────────────────────────────────────

async def redis_set_key(key: str, data: dict, ttl: int = 7200) -> bool:
    """Write any JSON payload to Upstash with TTL."""
    if not _UPSTASH_URL:
        return False
    try:
        client = _get_redis_client()
        resp = await client.post(
            f"{_UPSTASH_URL}/set/{key}",
            content=json.dumps(data),
            headers={
                "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
            params={"EX": ttl},
        )
        return resp.status_code == 200
    except Exception as e:
        _logger.warning(f"[REDIS] SET {key} error: {e}")
        return False


async def redis_get_key(key: str) -> dict | None:
    """Read any JSON payload from Upstash. Returns None on miss/error."""
    if not _UPSTASH_URL:
        return None
    try:
        client = _get_redis_client()
        resp = await client.get(
            f"{_UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
        )
        if resp.status_code == 200:
            raw = resp.json().get("result")
            if raw:
                return json.loads(raw)
        return None
    except Exception as e:
        _logger.warning(f"[REDIS] GET {key} error: {e}")
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
                _logger.warning(f"[SUPABASE] Non-retryable error {resp.status_code}: {resp.text[:100]}")
                return resp
            last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)

        if attempt < _SB_MAX_RETRIES - 1:
            delay = _SB_BASE_DELAY * (2 ** attempt)  # exponential backoff
            _logger.warning(f"[SUPABASE] Retry {attempt + 1}/{_SB_MAX_RETRIES} after {delay}s: {last_error}")
            await asyncio.sleep(delay)

    _logger.warning(f"[SUPABASE] All retries exhausted: {last_error}")
    return None


async def supabase_insert_batch(rows: list) -> bool:
    """Bulk-insert CIS score rows into Supabase REST API with retry."""
    if not _SB_URL or not _SB_KEY or not rows:
        _logger.warning("[SUPABASE] Skipped: missing config or empty rows")
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
            _logger.info(f"[SUPABASE] Inserted {len(rows)} rows (attempt 1)")
            return True
        if resp:
            _logger.warning(f"[SUPABASE] Insert failed after retries: {resp.status_code}")
        return False
    except Exception as e:
        _logger.warning(f"[SUPABASE] Insert exception: {e}")
        return False


async def supabase_insert_table(table: str, rows: list) -> bool:
    """Generic bulk-insert into any Supabase table (REST) with retry."""
    if not _SB_URL or not _SB_KEY or not rows or not table:
        return False
    url = f"{_SB_URL}/rest/v1/{table}"
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }
    try:
        resp = await _supabase_request_with_retry("POST", url, content=json.dumps(rows), headers=headers)
        if resp and resp.status_code in (200, 201):
            _logger.info(f"[SUPABASE] Inserted {len(rows)} rows into {table}")
            return True
        if resp:
            _logger.warning(f"[SUPABASE] Insert into {table} failed: {resp.status_code} {resp.text[:120]}")
        return False
    except Exception as e:
        _logger.warning(f"[SUPABASE] Insert into {table} exception: {e}")
        return False


async def supabase_get_recent_scores(symbols: list, n: int = 30) -> dict:
    """Bulk-fetch last N CIS score rows per symbol from Supabase.

    Returns dict keyed by symbol (uppercase) → list of rows ordered newest-first.
    Each row contains at minimum {"score": float, "recorded_at": str}.
    Used by /internal/cis-scores to compute score_delta and score_zscore on push.
    Returns empty dict if Supabase is unconfigured or unreachable.
    """
    if not _SB_URL or not _SB_KEY or not symbols:
        return {}

    symbols_upper = [s.upper() for s in symbols if s]
    # Supabase PostgREST: filter on list via in.(A,B,C)
    in_filter = "in.(" + ",".join(symbols_upper) + ")"
    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    params = {
        "symbol": in_filter,
        "order":  "recorded_at.desc",
        "limit":  str(n * len(symbols_upper)),
        "select": "symbol,score,grade,signal,macro_regime,recorded_at",
    }
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
    }

    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            rows = resp.json()
            result: dict = {}
            for row in rows:
                sym_raw = row.get("symbol")
                # Supabase returns symbol=null when the column isn't in SELECT
                # scope (or table has it as computed). Coerce None/empty to ""
                # so .upper() never raises AttributeError, which the outer
                # try/except was silently swallowing.
                sym = (sym_raw or "").upper()
                if sym:
                    result.setdefault(sym, []).append(row)
            # Each symbol list is already ordered newest-first (Supabase returns in query order)
            return result
        if resp:
            _logger.warning(f"[SUPABASE] get_recent_scores error {resp.status_code}: {resp.text[:100]}")
        return {}
    except Exception as e:
        _logger.warning(f"[SUPABASE] get_recent_scores exception: {e}")
        return {}


async def supabase_get_history(symbol: str, days: int = 7) -> list:
    """Read CIS score history for one symbol from Supabase with retry."""
    if not _SB_URL or not _SB_KEY:
        _logger.warning("[SUPABASE] History read skipped: missing config")
        return []

    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    params = {
        "symbol":  f"eq.{symbol.upper()}",
        "order":   "recorded_at.desc",
        "limit":   str(days * 48),
        "select":  "score,raw_cis_score,grade,signal,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,score_delta,score_zscore,macro_regime,data_tier,las,confidence,asset_class,recorded_at",
    }
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
    }

    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            data = resp.json()
            _logger.warning(f"[SUPABASE] History {symbol}: {len(data)} records (last 7d)")
            return data
        if resp:
            _logger.warning(f"[SUPABASE] History error {resp.status_code}: {resp.text[:100]}")
        return []
    except Exception as e:
        _logger.warning(f"[SUPABASE] History exception: {e}")
        return []


# ── Track record read — cached, for the self-tuning conviction tilt ────────────
_TRACKREC_CACHE: dict = {"rows": None, "ts": 0.0}
_TRACKREC_TTL = 6 * 3600  # 6h — the refresh runs daily; this is fresh enough


_EDGEMAP_CACHE: dict = {"rows": None, "ts": 0.0}
_EDGEMAP_TTL = 6 * 3600


async def supabase_get_latest_edge_map() -> list:
    """Latest signal_edge_map batch: [{signal,risk_band,n,avg_alpha_pct,alpha_win_pct,...}].
    Cached 6h; best-effort ([] on miss)."""
    now = time.time()
    if _EDGEMAP_CACHE["rows"] is not None and (now - _EDGEMAP_CACHE["ts"]) < _EDGEMAP_TTL:
        return _EDGEMAP_CACHE["rows"]
    if not _SB_URL or not _SB_KEY:
        return []
    url = f"{_SB_URL}/rest/v1/signal_edge_map"
    params = {"order": "computed_at.desc", "limit": "60",
              "select": "signal,risk_band,n,avg_alpha_pct,alpha_win_pct,avg_abs_return_pct,computed_at"}
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            allrows = resp.json()
            latest = max((r.get("computed_at") for r in allrows), default=None)
            rows = [r for r in allrows if r.get("computed_at") == latest]
            _EDGEMAP_CACHE["rows"] = rows; _EDGEMAP_CACHE["ts"] = now
            return rows
        return []
    except Exception as e:
        _logger.warning(f"[SUPABASE] edge_map read exception: {e}")
        return []


async def supabase_rpc(fn_name: str, payload: dict | None = None):
    """Call a Postgres function via PostgREST RPC (uses the configured service key).
    Returns the JSON result or None. Used by the daily track-record refresh."""
    if not _SB_URL or not _SB_KEY:
        return None
    url = f"{_SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}",
               "Content-Type": "application/json"}
    try:
        resp = await _supabase_request_with_retry("POST", url, json=(payload or {}), headers=headers)
        if resp and resp.status_code in (200, 204):
            try:
                return resp.json()
            except Exception:
                return True
        if resp:
            _logger.warning(f"[SUPABASE] rpc {fn_name} error {resp.status_code}: {resp.text[:120]}")
        return None
    except Exception as e:
        _logger.warning(f"[SUPABASE] rpc {fn_name} exception: {e}")
        return None


async def supabase_get_latest_track_record() -> list:
    """Latest signal_track_record batch (list of {signal,grade,n,avg_alpha_pct,alpha_win_pct}).
    Cached 6h; best-effort ([] on any miss → conviction falls back to the hardcoded prior)."""
    now = time.time()
    if _TRACKREC_CACHE["rows"] is not None and (now - _TRACKREC_CACHE["ts"]) < _TRACKREC_TTL:
        return _TRACKREC_CACHE["rows"]
    if not _SB_URL or not _SB_KEY:
        return []
    url = f"{_SB_URL}/rest/v1/signal_track_record"
    params = {"order": "computed_at.desc", "limit": "40",
              "select": "signal,grade,n,avg_alpha_pct,alpha_win_pct,computed_at"}
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            allrows = resp.json()
            latest = max((r.get("computed_at") for r in allrows), default=None)
            rows = [r for r in allrows if r.get("computed_at") == latest]
            _TRACKREC_CACHE["rows"] = rows
            _TRACKREC_CACHE["ts"] = now
            return rows
        return []
    except Exception as e:
        _logger.warning(f"[SUPABASE] track_record read exception: {e}")
        return []


# ── D4 attention (trending_log) read — cached, for cause-proximity ─────────────
_TRENDING_CACHE: dict = {"map": None, "ts": 0.0}
_TRENDING_TTL = 1800  # 30 min — trending only refreshes daily, this is plenty fresh


async def supabase_get_latest_trending() -> dict:
    """Latest D4 attention snapshot as {SYMBOL_UPPER: row}. Cached 30 min; best-effort
    (returns {} on any miss so cause-proximity falls back to its market_proxy floor)."""
    now = time.time()
    if _TRENDING_CACHE["map"] is not None and (now - _TRENDING_CACHE["ts"]) < _TRENDING_TTL:
        return _TRENDING_CACHE["map"]
    if not _SB_URL or not _SB_KEY:
        return {}
    url = f"{_SB_URL}/rest/v1/trending_log"
    params = {
        "order": "recorded_at.desc",
        "limit": "60",   # ~4 daily snapshots of 15 coins — newest wins per symbol
        "select": "symbol,attention_score,sentiment_up,watchlist_users,market_cap_rank,trending_rank,recorded_at",
    }
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            out: dict = {}
            for row in resp.json():            # newest-first → first seen per symbol wins
                sym = (row.get("symbol") or "").upper()
                if sym and sym not in out:
                    out[sym] = row
            _TRENDING_CACHE["map"] = out
            _TRENDING_CACHE["ts"] = now
            return out
        return {}
    except Exception as e:
        _logger.warning(f"[SUPABASE] trending read exception: {e}")
        return {}


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
        except (ValueError, RuntimeError) as e:
            _logger.warning(f"[WS] disconnect error: {e}")

    async def broadcast(self, message: dict):
        # Remove dead connections before broadcasting
        self.cleanup_dead()

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
