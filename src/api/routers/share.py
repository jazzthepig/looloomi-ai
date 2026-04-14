"""
Share Router — og:image PNG for social link previews (Twitter, WeChat, Telegram)
================================================================================
GET /api/v1/share/og-image
  → 1200×630 PNG, in-memory cached 30 min
  → Shows live CIS top 5, macro regime, BTC dom, F&G index

Usage in HTML meta tags:
  <meta property="og:image" content="https://looloomi.ai/api/v1/share/og-image" />
  <meta name="twitter:image" content="https://looloomi.ai/api/v1/share/og-image" />
  <meta property="og:image:width"  content="1200" />
  <meta property="og:image:height" content="630"  />
  <meta name="twitter:card" content="summary_large_image" />

Cache-bust: GET /api/v1/share/og-image?bust=true
"""

import io
import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional

import logging
from fastapi import APIRouter, Query
from fastapi.responses import Response

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/share", tags=["share"])

# ── In-memory image cache (30 min TTL) ───────────────────────────────────────
_IMG_TTL = 1800
_img_cache: dict = {}


def _cache_get() -> Optional[bytes]:
    v  = _img_cache.get("data")
    ts = _img_cache.get("ts", 0)
    return v if (v and time.time() - ts < _IMG_TTL) else None


def _cache_set(data: bytes):
    _img_cache["data"] = data
    _img_cache["ts"]   = time.time()


# ── Font loader — tries system fonts, falls back to PIL default ───────────────
def _font(size: int, bold: bool = False, mono: bool = False):
    from PIL import ImageFont
    if mono:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf" if bold
                else "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/Hack-Bold.ttf" if bold else "/usr/share/fonts/truetype/Hack-Regular.ttf",
        ]
    elif bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


# ── Colour helpers ────────────────────────────────────────────────────────────
def _h(hex_str: str) -> tuple:
    s = hex_str.lstrip("#")
    return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))


BG   = (2, 2, 8)
T1   = _h("#F0F4FF")   # primary
T2   = _h("#C7D2FE")   # secondary
T3   = _h("#3E6680")   # muted
GOLD = _h("#C8A84B")   # accent

GRADE_CLR = {
    "A+": _h("#00D98A"), "A": _h("#00D98A"),
    "B+": _h("#4472FF"), "B": _h("#4472FF"),
    "C+": _h("#E8A000"), "C": _h("#E8A000"),
    "D":  _h("#FF6B35"), "F": _h("#888888"),
}
SIG_CLR = {
    "STRONG OUTPERFORM": _h("#00D98A"),
    "OUTPERFORM":        _h("#4472FF"),
    "NEUTRAL":           _h("#E8A000"),
    "UNDERPERFORM":      _h("#FF6B35"),
    "UNDERWEIGHT":       _h("#FF2D55"),
}
SIG_SHORT = {
    "STRONG OUTPERFORM": "STR ↑↑",
    "OUTPERFORM":        "↑ OUT",
    "NEUTRAL":           "NEUT",
    "UNDERPERFORM":      "↓ UND",
    "UNDERWEIGHT":       "↓↓",
}
CLASS_CLR = {
    "L1": _h("#00C8E0"), "L2": _h("#9945FF"), "DeFi": _h("#4472FF"),
    "RWA": GOLD,         "Infrastructure": _h("#00D98A"),
    "Memecoin": _h("#FF1060"), "AI": _h("#FF6B00"),
    "US Equity": _h("#4B9EFF"), "US Bond": _h("#F59E0B"),
    "Commodity": _h("#C8A84B"),
}
REGIME_CLR = {
    "RISK_ON": _h("#00D98A"), "Risk-On": _h("#00D98A"), "Goldilocks": _h("#00D98A"),
    "RISK_OFF": _h("#FF2D55"), "Risk-Off": _h("#FF2D55"),
    "TIGHTENING": _h("#FF6B35"), "Tightening": _h("#FF6B35"),
    "EASING": _h("#4472FF"),    "Easing": _h("#4472FF"),
    "STAGFLATION": _h("#E8A000"), "Stagflation": _h("#E8A000"),
}


# ── Image renderer (CPU-bound, runs in thread) ────────────────────────────────
def _render(cis_top5: list, macro: dict) -> bytes:
    from PIL import Image, ImageDraw

    W, H = 1200, 630
    PAD  = 54

    # ── Base layer + ambient orbs ─────────────────────────────────────────────
    base = Image.new("RGBA", (W, H), (*BG, 255))
    orbs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d_orb = ImageDraw.Draw(orbs)

    # Purple orb — top-left
    for r in range(420, 0, -7):
        t = r / 420
        a = max(0, int(48 * t * (1 - t) * 4))
        d_orb.ellipse([-100 - r, -120 - r, -100 + r * 2, -120 + r * 2],
                      fill=(107, 15, 204, a))
    # Navy-blue orb — bottom-right
    for r in range(360, 0, -7):
        t = r / 360
        a = max(0, int(38 * t * (1 - t) * 4))
        d_orb.ellipse([W + 40 - r * 2, H + 40 - r * 2, W + 40 + r, H + 40 + r],
                      fill=(45, 53, 212, a))

    img  = Image.alpha_composite(base, orbs).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Border + gold accent line ─────────────────────────────────────────────
    draw.rectangle([0, 0, W - 1, H - 1],
                   outline=(56, 148, 210, 30), width=1)
    draw.rectangle([0, 0, W, 3], fill=GOLD)

    # ── HEADER ───────────────────────────────────────────────────────────────
    draw.text((PAD, 22), "CometCloud AI",
              font=_font(30, bold=True), fill=T1)
    draw.text((PAD, 60), "AI Fund-of-Funds · Solana · Hong Kong",
              font=_font(13), fill=T3)

    # Date (top-right)
    today = datetime.now(timezone.utc).strftime("%b %d, %Y  UTC")
    draw.text((W - PAD, 24), today,
              font=_font(11, mono=True), fill=T3, anchor="ra")

    # Regime badge
    regime_raw   = macro.get("regime") or macro.get("macro_regime") or ""
    regime_label = regime_raw.replace("_", "-").title() if regime_raw else "—"
    rclr         = REGIME_CLR.get(regime_raw, T2)
    if regime_raw:
        bf   = _font(10, bold=True, mono=True)
        btext = regime_label.upper()
        bw   = draw.textlength(btext, font=bf) + 24
        bx   = W - PAD - bw
        by   = 52
        draw.rounded_rectangle([bx, by, bx + bw, by + 22],
                                radius=11, fill=(*rclr, 20), outline=(*rclr, 65))
        draw.ellipse([bx + 8, by + 8, bx + 15, by + 15], fill=rclr)
        draw.text((bx + 20, by + 4), btext, font=bf, fill=rclr)

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    draw.line([(PAD, 92), (W - PAD, 92)],
              fill=(255, 255, 255, 16), width=1)

    # ── MACRO STRIP (4 metrics) ───────────────────────────────────────────────
    fng    = macro.get("fear_greed_index") or macro.get("fng") or macro.get("fear_greed_value")
    btcdom = macro.get("btc_dominance")
    btcp   = macro.get("btc_price") or macro.get("btc")
    mcap   = macro.get("total_market_cap") or macro.get("total_mcap")

    def _fmt_price(v):
        if not v: return "—"
        return f"${float(v):,.0f}"

    def _fmt_mcap(v):
        if not v: return "—"
        v = float(v)
        if v >= 1e12: return f"${v / 1e12:.2f}T"
        if v >= 1e9:  return f"${v / 1e9:.0f}B"
        return f"${v:.0f}"

    fng_int  = round(float(fng)) if fng else None
    fng_clr  = _h("#00D98A") if (fng_int or 50) >= 60 else \
               _h("#FF2D55") if (fng_int or 50) < 35 else GOLD

    metrics = [
        ("BTC Price",   _fmt_price(btcp),                  None),
        ("Fear & Greed", str(fng_int) if fng_int else "—", fng_clr),
        ("BTC Dom.",    f"{float(btcdom):.1f}%" if btcdom else "—", None),
        ("Market Cap",  _fmt_mcap(mcap),                   None),
    ]

    cw      = (W - PAD * 2) // 4
    strip_y = 104
    f_mkey  = _font(9)
    f_mval  = _font(21, mono=True)
    for i, (label, val, clr) in enumerate(metrics):
        x = PAD + i * cw
        if i > 0:
            draw.line([(x, strip_y + 2), (x, strip_y + 50)],
                      fill=(255, 255, 255, 14), width=1)
        draw.text((x + 10, strip_y + 4), label.upper(), font=f_mkey, fill=T3)
        draw.text((x + 10, strip_y + 21), val, font=f_mval, fill=clr or T1)

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    draw.line([(PAD, 166), (W - PAD, 166)],
              fill=(255, 255, 255, 16), width=1)

    # ── CIS TOP ASSETS ────────────────────────────────────────────────────────
    f_sec_lbl = _font(9, bold=True)
    draw.text((PAD, 178), "CIS TOP ASSETS", font=f_sec_lbl, fill=T3)
    draw.text((W - PAD, 178), "LIVE · AI-SCORED · CIS v4.1",
              font=f_sec_lbl, fill=T3, anchor="ra")

    # Column layout: rank | class | symbol+name | score | grade | signal
    COL = {
        "rank":  PAD,
        "class": PAD + 38,
        "name":  PAD + 178,
        "score": PAD + 520,
        "grade": PAD + 620,
        "sig":   PAD + 700,
    }
    ROW_H   = 70
    TABLE_Y = 200

    # Column headers
    f_hdr = _font(8)
    for label, x in [("#", COL["rank"]), ("Class", COL["class"]),
                     ("Asset", COL["name"]), ("CIS", COL["score"] - 20),
                     ("Grade", COL["grade"] - 4), ("Signal", COL["sig"])]:
        draw.text((x, TABLE_Y), label, font=f_hdr, fill=T3)
    TABLE_Y += 17

    f_rank  = _font(13, mono=True)
    f_sym   = _font(20, bold=True)
    f_aname = _font(11)
    f_score = _font(22, mono=True)
    f_grade = _font(14, bold=True, mono=True)
    f_cls   = _font(9, bold=True)
    f_sig   = _font(9, bold=True)

    for i, asset in enumerate(cis_top5[:5]):
        y = TABLE_Y + i * ROW_H
        if i > 0:
            draw.line([(PAD, y), (W - PAD, y)],
                      fill=(255, 255, 255, 8), width=1)

        sym    = (asset.get("symbol") or asset.get("asset_id") or "???").upper()
        name   = (asset.get("name") or asset.get("asset_name") or sym)[:30]
        cls    = asset.get("asset_class") or "Crypto"
        score  = float(asset.get("cis_score") or asset.get("total_score") or 0)
        grade  = asset.get("grade") or "—"
        signal = asset.get("signal") or "NEUTRAL"
        gc     = GRADE_CLR.get(grade, T3)
        sc     = SIG_CLR.get(signal, T3)
        cc     = CLASS_CLR.get(cls, T3)

        y_mid  = y + ROW_H // 2

        # Rank
        draw.text((COL["rank"], y_mid - 7), str(i + 1), font=f_rank, fill=T3)

        # Class badge
        cls_short = (cls.replace("Infrastructure", "Infra")
                       .replace("US Equity", "Equity")
                       .replace("US Bond", "Bond"))
        bw = draw.textlength(cls_short, font=f_cls) + 14
        draw.rounded_rectangle(
            [COL["class"], y_mid - 11, COL["class"] + bw, y_mid + 11],
            radius=5, fill=(*cc, 20), outline=(*cc, 55),
        )
        draw.text((COL["class"] + 7, y_mid - 7), cls_short, font=f_cls, fill=cc)

        # Symbol + name
        draw.text((COL["name"], y_mid - 13), sym, font=f_sym, fill=T1)
        draw.text((COL["name"], y_mid + 12), name, font=f_aname, fill=T3)

        # CIS score
        score_clr = _h("#00D98A") if score >= 75 else \
                    _h("#4472FF") if score >= 55 else GOLD
        draw.text((COL["score"], y_mid - 11), f"{score:.1f}",
                  font=f_score, fill=score_clr, anchor="ra")

        # Grade circle
        gx = COL["grade"] + 22
        gy = y_mid
        draw.ellipse([gx - 20, gy - 20, gx + 20, gy + 20],
                     fill=(*gc, 22), outline=(*gc, 70))
        gl = grade
        tw = draw.textlength(gl, font=f_grade)
        draw.text((gx - tw / 2, gy - 10), gl, font=f_grade, fill=gc)

        # Signal
        draw.text((COL["sig"], y_mid - 6),
                  SIG_SHORT.get(signal, signal[:8]), font=f_sig, fill=sc)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    draw.line([(PAD, H - 52), (W - PAD, H - 52)],
              fill=(255, 255, 255, 14), width=1)
    draw.text((PAD, H - 40), "looloomi.ai/strategy",
              font=_font(13, bold=True), fill=GOLD)
    draw.text((W - PAD, H - 40),
              "AI-curated · 0% management fee · Solana · HK",
              font=_font(11), fill=T3, anchor="ra")
    draw.text((PAD, H - 20),
              "For qualified investors only · Not investment advice",
              font=_font(9), fill=T3)

    # ── Serialize ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


# ── API endpoint ──────────────────────────────────────────────────────────────

@router.get("/og-image", response_class=Response,
            summary="og:image PNG for social link previews (1200×630)")
async def og_image(
    bust: bool = Query(False, description="Set true to bypass 30-min cache"),
):
    """
    Generates a 1200×630 PNG card for og:image / twitter:image meta tags.
    Shows live CIS top-5 assets, macro regime, BTC price, Fear & Greed index.
    Cached 30 minutes in-memory. Pass ?bust=true to force regenerate.
    """
    if not bust:
        cached = _cache_get()
        if cached:
            return Response(
                content=cached,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=1800, stale-while-revalidate=300",
                    "X-Cache": "HIT",
                    "X-Image-Size": f"{len(cached)} bytes",
                },
            )

    # ── Fetch live data ───────────────────────────────────────────────────────
    cis_top5: list = []
    macro:    dict = {}

    # CIS top 5 — try Redis-cached local-engine scores first
    try:
        import src.api.store as store
        redis_data = await store.redis_get("cis:local_scores")
        if redis_data and isinstance(redis_data, dict):
            universe = redis_data.get("universe", [])
            if universe:
                cis_top5 = sorted(
                    [a for a in universe if float(a.get("cis_score") or 0) > 0],
                    key=lambda x: float(x.get("cis_score", 0)),
                    reverse=True,
                )[:5]
    except Exception:
        pass

    # Fallback: Railway T2 engine
    if not cis_top5:
        try:
            from src.data.cis.cis_provider import calculate_cis_universe
            result   = await asyncio.wait_for(calculate_cis_universe(), timeout=15)
            universe = result.get("universe", [])
            cis_top5 = sorted(
                [a for a in universe if float(a.get("cis_score") or 0) > 0],
                key=lambda x: float(x.get("cis_score", 0)),
                reverse=True,
            )[:5]
        except Exception as e:
            _logger.warning(f"og-image: CIS fetch error: {e}")

    # Macro pulse
    try:
        from src.api.data_layer import get_macro_pulse
        macro = await asyncio.wait_for(get_macro_pulse(), timeout=8) or {}
    except Exception:
        try:
            from src.api.routers.market import get_macro_pulse as _gmp
            macro = await asyncio.wait_for(_gmp(), timeout=8) or {}
        except Exception as e:
            _logger.warning(f"og-image: macro fetch error: {e}")

    # ── Render in thread (Pillow is CPU-bound) ────────────────────────────────
    png_bytes = await asyncio.to_thread(_render, cis_top5, macro)
    _cache_set(png_bytes)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=1800, stale-while-revalidate=300",
            "X-Cache": "MISS",
            "X-Image-Size": f"{len(png_bytes)} bytes",
            "X-Assets-Count": str(len(cis_top5)),
        },
    )
