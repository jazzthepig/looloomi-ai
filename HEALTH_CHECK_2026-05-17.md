```
COMETCLOUD HEALTH CHECK — 2026-05-17T00:00Z (automated)
══════════════════════════════════════════════════════════

MACRO PULSE    ❌ DOWN — HTTP 502 "Application failed to respond"
CIS UNIVERSE   ❌ DOWN — HTTP 502 "Application failed to respond"
SIGNAL FEED    ❌ DOWN — HTTP 502 "Application failed to respond"
TOP ASSETS     ❌ DOWN — HTTP 502 "Application failed to respond"
HEALTH CHECK   ❌ DOWN — /health also returns 502

OVERALL: 🔴 CRITICAL — RAILWAY APPLICATION IS COMPLETELY DOWN

══════════════════════════════════════════════════════════
ACTION NEEDED:

1. Railway app (web-production-0cdf76.up.railway.app) is returning 502 on ALL
   endpoints including /health. The FastAPI process is not responding.

2. Possible causes:
   - Railway deployment crashed or ran out of memory
   - Application boot failure (missing env var, import error, dependency issue)
   - Railway service suspended (billing, usage limits)

3. Immediate actions:
   - Check Railway dashboard for deploy status and crash logs
   - Check Railway service logs for Python tracebacks or OOM kills
   - Verify billing/account status on Railway
   - If deploy crashed: trigger a redeploy from Railway dashboard
   - If env vars missing: check UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN,
     COINGECKO_API_KEY, INTERNAL_TOKEN are all set

4. TLS handshake succeeds (cert valid until Aug 2 2026), HTTP/2 connects,
   but app never responds → confirms Railway edge proxy is up but the
   backend Python process is dead or unresponsive.

══════════════════════════════════════════════════════════
Monitor: automated scheduled task
Next check: next scheduled interval
```
