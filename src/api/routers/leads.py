"""
Leads router — LP enquiry capture, referral attribution
Endpoints: /api/v1/leads/*

Email delivery: Resend API (RESEND_API_KEY env var)
Notification target: LEAD_NOTIFY_EMAIL env var
Storage: Supabase `leads` table → Redis fallback (30d TTL)
"""
import os
import json
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional

_logger = logging.getLogger(__name__)
router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    name: str
    email: EmailStr
    organization: Optional[str] = None
    investment_range: Optional[str] = None   # e.g. "$500K–$2M"
    message: Optional[str] = None
    ref: Optional[str] = None                # referral code from ?ref= URL param
    source_page: Optional[str] = "strategy"


# ── Investment range options (for validation / display) ───────────────────────
INVESTMENT_RANGES = [
    "Under $100K",
    "$100K – $500K",
    "$500K – $2M",
    "$2M – $10M",
    "Above $10M",
    "Prefer not to say",
]

# ── Known referral partners (for attribution display) ─────────────────────────
_REFERRAL_PARTNERS = {
    "nic":        "Nic — Senior Network Lead",
    "humblebee":  "HumbleBee Capital",
    "est":        "EST Alpha",
    "cometcloud": "CometCloud Direct",
}


# ── Email helper ──────────────────────────────────────────────────────────────

async def _send_lead_email(lead: dict) -> bool:
    """Send lead notification via Resend API. Returns True on success."""
    api_key   = os.getenv("RESEND_API_KEY")
    notify_to = os.getenv("LEAD_NOTIFY_EMAIL")
    if not api_key or not notify_to:
        _logger.warning("RESEND_API_KEY or LEAD_NOTIFY_EMAIL not set — skipping email")
        return False

    ref_label = _REFERRAL_PARTNERS.get(lead.get("ref", ""), lead.get("ref") or "Direct")
    amount    = lead.get("investment_range") or "—"
    org       = lead.get("organization") or "—"
    msg       = lead.get("message") or "—"
    ts        = lead.get("created_at", "")[:19].replace("T", " ")

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;
                background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
      <div style="background: #020208; padding: 20px 28px; border-bottom: 1px solid #1e293b;">
        <div style="font-size: 11px; letter-spacing: 0.14em; color: #6b7280; text-transform: uppercase;
                    font-weight: 700; margin-bottom: 6px;">CometCloud AI</div>
        <div style="font-size: 20px; font-weight: 700; color: #f1f5f9;">New LP Enquiry</div>
      </div>
      <div style="padding: 24px 28px;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px; width: 140px;">Name</td>
              <td style="padding: 8px 0; color: #111827; font-size: 14px; font-weight: 600;">{lead['name']}</td></tr>
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px;">Email</td>
              <td style="padding: 8px 0;"><a href="mailto:{lead['email']}" style="color: #4472ff;">{lead['email']}</a></td></tr>
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px;">Organization</td>
              <td style="padding: 8px 0; color: #111827; font-size: 14px;">{org}</td></tr>
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px;">Investment Range</td>
              <td style="padding: 8px 0; color: #c8a84b; font-size: 14px; font-weight: 700;">{amount}</td></tr>
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px;">Referral</td>
              <td style="padding: 8px 0; color: #111827; font-size: 14px;">{ref_label}</td></tr>
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px;">Message</td>
              <td style="padding: 8px 0; color: #374151; font-size: 13px; font-style: italic;">{msg}</td></tr>
          <tr><td style="padding: 8px 0; color: #6b7280; font-size: 12px;">Submitted</td>
              <td style="padding: 8px 0; color: #9ca3af; font-size: 12px;">{ts} UTC</td></tr>
        </table>
      </div>
      <div style="padding: 16px 28px; background: #f3f4f6; border-top: 1px solid #e5e7eb;
                  font-size: 11px; color: #9ca3af;">
        CometCloud AI · looloomi.ai · Automated lead notification
      </div>
    </div>
    """

    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "from":    "CometCloud Leads <leads@looloomi.ai>",
                    "to":      [notify_to],
                    "subject": f"[CometCloud] New LP — {lead['name']} · {amount} · via {ref_label}",
                    "html":    html,
                },
            )
            if r.status_code in (200, 201):
                return True
            _logger.warning(f"Resend returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        _logger.warning(f"Email send failed: {e}")
    return False


# ── Storage helper ────────────────────────────────────────────────────────────

async def _store_lead(record: dict) -> bool:
    """Persist lead to Supabase → Redis fallback."""
    stored = False

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if supabase_url and supabase_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(
                    f"{supabase_url}/rest/v1/leads",
                    headers={
                        "apikey":        supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type":  "application/json",
                        "Prefer":        "return=minimal",
                    },
                    json=record,
                )
                if r.status_code in (200, 201):
                    stored = True
        except Exception as e:
            _logger.warning(f"Supabase lead write failed: {e}")

    if not stored:
        try:
            try:
                from src.data.market.data_layer import _redis_get, _redis_set
            except ImportError:
                from data.market.data_layer import _redis_get, _redis_set
            existing_raw = await _redis_get("cometcloud:leads")
            existing = json.loads(existing_raw) if existing_raw else []
            existing.append(record)
            await _redis_set("cometcloud:leads", json.dumps(existing[-1000:]), ttl=86400 * 30)
            stored = True
        except Exception as e:
            _logger.warning(f"Redis lead write failed: {e}")

    return stored


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/v1/leads/capture")
async def capture_lead(req: LeadRequest):
    """
    Capture an LP enquiry from strategy.html.
    Stores to Supabase/Redis and fires email notification.
    """
    record = {
        "name":             req.name.strip(),
        "email":            req.email.lower().strip(),
        "organization":     (req.organization or "").strip() or None,
        "investment_range": req.investment_range,
        "message":          (req.message or "").strip() or None,
        "ref":              (req.ref or "").lower().strip() or None,
        "source_page":      req.source_page or "strategy",
        "created_at":       datetime.utcnow().isoformat(),
        "status":           "new",
    }

    # Fire-and-forget: store + email in parallel
    import asyncio
    stored, emailed = await asyncio.gather(
        _store_lead(record),
        _send_lead_email(record),
        return_exceptions=True,
    )

    _logger.info(
        f"Lead: {record['name']} <{record['email']}> "
        f"org={record['organization']} range={record['investment_range']} "
        f"ref={record['ref']} stored={stored} emailed={emailed}"
    )

    return {
        "ok":      True,
        "message": "Thank you — we'll be in touch within 24 hours.",
    }


@router.get("/api/v1/leads/summary")
async def leads_summary(token: str = ""):
    """
    Internal: referral attribution summary.
    Protected by INTERNAL_TOKEN query param.
    """
    internal_token = os.getenv("INTERNAL_TOKEN", "")
    if not internal_token or token != internal_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Try Supabase first
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    leads = []

    if supabase_url and supabase_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{supabase_url}/rest/v1/leads?select=*&order=created_at.desc&limit=500",
                    headers={
                        "apikey":        supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )
                if r.status_code == 200:
                    leads = r.json()
        except Exception:
            pass

    if not leads:
        try:
            try:
                from src.data.market.data_layer import _redis_get
            except ImportError:
                from data.market.data_layer import _redis_get
            raw = await _redis_get("cometcloud:leads")
            leads = json.loads(raw) if raw else []
        except Exception:
            leads = []

    # Attribution summary
    ref_counts: dict = {}
    range_counts: dict = {}
    total_intent = 0.0

    RANGE_MID = {
        "Under $100K":      50_000,
        "$100K – $500K":    300_000,
        "$500K – $2M":    1_250_000,
        "$2M – $10M":     6_000_000,
        "Above $10M":    10_000_000,
        "Prefer not to say": 0,
    }

    for lead in leads:
        ref = lead.get("ref") or "direct"
        ref_counts[ref] = ref_counts.get(ref, 0) + 1
        rng = lead.get("investment_range") or "—"
        range_counts[rng] = range_counts.get(rng, 0) + 1
        total_intent += RANGE_MID.get(rng, 0)

    return {
        "total":         len(leads),
        "by_referral":   ref_counts,
        "by_range":      range_counts,
        "intent_aum":    total_intent,
        "recent":        leads[:10],
        "partners":      _REFERRAL_PARTNERS,
        "timestamp":     datetime.utcnow().isoformat(),
    }
