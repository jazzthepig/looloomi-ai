"""
Social Router — OG image generation for link previews
======================================================
Generates a 1200×630 PNG card with live CIS data for Twitter/WeChat/Telegram.

Endpoints:
  GET /api/v1/social/og-image          — PNG response, live CIS top 5 + macro
  GET /api/v1/social/og-image?ref=nic  — personalised card with referral code

Caching: Redis 10min TTL (keyed by ref param). In-memory 60s fallback.
"""

import io, time, math, hashlib
from typing import Optional
from fastapi import APIRouter, Response
from fastapi.responses import Response as FastAPIResponse

router = APIRouter(prefix="/api/v1/social", tags=["social"])

# ── In-memory cache ─────────────────────────────────────────────────────────
_og_cache: dict = {}  # key → (bytes, timestamp)
_OG_CACHE_TTL = 120   # 2 min in-memory


def _cache_key(ref: str) -> str:
    return f"og:{ref or 'default'}"


# ── Color/design constants ──────────────────────────────────────────────────
BG_COLOR = (2, 2, 8)           # #020208
CARD_BG = (8, 12, 28)          # #080C1C
GOLD = (200, 168, 75)          # #C8A84B
WHITE = (241, 245, 249)        # #F1F5F9
DIM = (62, 102, 128)           # #3E6680
GREEN = (0, 217, 138)          # #00D98A
RED = (255, 45, 85)            # #FF2D55
BLUE = (68, 114, 255)          # #4472FF
ORANGE = (255, 107, 53)        # #FF6B35
AMBER = (232, 160, 0)          # #E8A000

GRADE_COLORS = {
    "A+": GREEN, "A": GREEN,
    "B+": GOLD, "B": GOLD,
    "C+": BLUE, "C": BLUE,
    "D": ORANGE, "F": RED,
}

SIGNAL_SHORT = {
    "STRONG OUTPERFORM": "STR OUT",
    "OUTPERFORM": "OUTPERF",
    "NEUTRAL": "NEUTRAL",
    "UNDERPERFORM": "UNDERP",
    "UNDERWEIGHT": "UNDERWT",
}

REGIME_COLORS = {
    "RISK_ON": GREEN, "RISK_OFF": RED,
    "TIGHTENING": ORANGE, "EASING": BLUE,
    "STAGFLATION": AMBER, "GOLDILOCKS": GOLD,
}

REGIME_LABELS = {
    "RISK_ON": "Risk On", "RISK_OFF": "Risk Off",
    "TIGHTENING": "Tightening", "EASING": "Easing",
    "STAGFLATION": "Stagflation", "GOLDILOCKS": "Goldilocks",
}


def _fmt_mcap(v):
    if not v:
        return "—"
    if v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"${v / 1e9:.0f}B"
    return f"${v:,.0f}"


# ── Data fetchers (reuse existing providers) ────────────────────────────────

async def _fetch_cis_top5() -> list:
    """Get top 5 CIS assets from the scoring engine."""
    try:
        from src.data.cis.cis_provider import calculate_cis_universe
        from src.api.store import redis_get

        # Try Redis first (Mac Mini T1 data)
        cached = await redis_get()
        if cached and cached.get("assets"):
            assets = cached["assets"]
            scored = [a for a in assets if (a.get("cis_score") or a.get("score", 0)) > 0]
            scored.sort(key=lambda a: a.get("cis_score") or a.get("score", 0), reverse=True)
            return scored[:5]

        # Fallback: Railway T2 scoring
        result = await calculate_cis_universe()
        if result and result.get("data"):
            assets = result["data"]
            scored = [a for a in assets if (a.get("cis_score", 0)) > 0 and a.get("grade")]
            scored.sort(key=lambda a: a.get("cis_score", 0), reverse=True)
            return scored[:5]
    except Exception as e:
        print(f"[OG] CIS fetch error: {e}")
    return []


async def _fetch_macro() -> dict:
    """Get macro pulse data."""
    try:
        from src.data.market.data_layer import get_macro_pulse
        return await get_macro_pulse()
    except Exception as e:
        print(f"[OG] Macro fetch error: {e}")
    return {}


# ── PIL image generator ─────────────────────────────────────────────────────

def _render_og_card(top5: list, macro: dict, ref: str = "") -> bytes:
    """Render a 1200×630 PNG card with CIS data."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Gradient overlay (simulate depth)
    for y in range(H):
        r = int(BG_COLOR[0] + (CARD_BG[0] - BG_COLOR[0]) * (y / H) * 0.6)
        g = int(BG_COLOR[1] + (CARD_BG[1] - BG_COLOR[1]) * (y / H) * 0.6)
        b = int(BG_COLOR[2] + (CARD_BG[2] - BG_COLOR[2]) * (y / H) * 0.6)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Ambient orb (subtle)
    _draw_orb(img, -100, -80, 500, (107, 15, 204), 0.08)
    _draw_orb(img, W - 200, H - 200, 350, (45, 53, 212), 0.06)
    draw = ImageDraw.Draw(img)  # refresh after orb compositing

    # Load fonts — try multiple paths for Railway (nixpacks) vs local (Ubuntu)
    def _try_font(paths, size):
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    _sans_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/nix/store/*/share/fonts/truetype/DejaVuSans-Bold.ttf",
    ]
    _sans = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    _mono_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
    ]
    _mono = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    ]

    font_lg      = _try_font(_sans_bold, 28)
    font_md      = _try_font(_sans_bold, 18)
    font_sm      = _try_font(_sans, 14)
    font_xs      = _try_font(_sans, 12)
    font_mono    = _try_font(_mono, 14)
    font_mono_lg = _try_font(_mono_bold, 20)
    font_mono_sm = _try_font(_mono, 11)

    # ── Header ──────────────────────────────────────────────────────────────
    x, y = 48, 36
    draw.text((x, y), "CometCloud AI", fill=GOLD, font=font_lg)
    draw.text((x, y + 36), "AI Fund-of-Funds  ·  Solana  ·  Hong Kong", fill=DIM, font=font_sm)

    # Date + regime (top right)
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%b %d, %Y")
    draw.text((W - 200, y + 4), date_str, fill=DIM, font=font_mono_sm)

    regime = macro.get("regime") or macro.get("macro_regime")
    if regime:
        rc = REGIME_COLORS.get(regime, BLUE)
        rl = REGIME_LABELS.get(regime, regime)
        # Regime pill
        rx = W - 200
        ry = y + 28
        draw.rounded_rectangle([rx, ry, rx + 140, ry + 26], radius=13, fill=(*rc, ), outline=None)
        draw.text((rx + 12, ry + 4), rl, fill=BG_COLOR, font=font_mono_sm)

    # ── Divider ─────────────────────────────────────────────────────────────
    draw.line([(48, 96), (W - 48, 96)], fill=(255, 255, 255, 15), width=1)

    # ── Macro strip ─────────────────────────────────────────────────────────
    fng = macro.get("fear_greed_index") or macro.get("fng")
    btc_dom = macro.get("btc_dominance")
    mcap = macro.get("total_market_cap")

    my = 112
    macro_items = []
    if mcap:
        macro_items.append(("MARKET CAP", _fmt_mcap(mcap)))
    if fng:
        macro_items.append(("FEAR & GREED", str(int(fng))))
    if btc_dom:
        macro_items.append(("BTC DOM.", f"{btc_dom:.1f}%"))

    if macro_items:
        col_w = 180
        for i, (label, val) in enumerate(macro_items):
            mx = 48 + i * col_w
            draw.text((mx, my), label, fill=DIM, font=font_mono_sm)
            val_color = WHITE
            if label == "FEAR & GREED" and fng:
                val_color = GREEN if fng >= 60 else (GOLD if fng >= 40 else RED)
            draw.text((mx, my + 20), val, fill=val_color, font=font_mono_lg)

    # ── CIS Top Assets header ───────────────────────────────────────────────
    ty = 172
    draw.text((48, ty), "CIS TOP ASSETS", fill=DIM, font=font_mono_sm)
    draw.text((W - 200, ty), "LIVE · AI-SCORED", fill=DIM, font=font_mono_sm)
    draw.line([(48, ty + 22), (W - 48, ty + 22)], fill=(255, 255, 255, 10), width=1)

    # ── Asset rows ──────────────────────────────────────────────────────────
    row_y = ty + 36
    row_h = 68

    if not top5:
        draw.text((48, row_y + 20), "Loading live data...", fill=DIM, font=font_sm)
    else:
        # Column headers
        draw.text((48, row_y - 4), "#", fill=DIM, font=font_mono_sm)
        draw.text((80, row_y - 4), "ASSET", fill=DIM, font=font_mono_sm)
        draw.text((500, row_y - 4), "CIS", fill=DIM, font=font_mono_sm)
        draw.text((600, row_y - 4), "GRADE", fill=DIM, font=font_mono_sm)
        draw.text((740, row_y - 4), "SIGNAL", fill=DIM, font=font_mono_sm)

        row_y += 18

        for i, asset in enumerate(top5):
            ay = row_y + i * row_h
            symbol = asset.get("symbol", "???")
            score = asset.get("cis_score") or asset.get("score", 0)
            grade = asset.get("grade", "—")
            signal = asset.get("signal", "NEUTRAL")
            asset_class = asset.get("asset_class", "")

            gc = GRADE_COLORS.get(grade, DIM)

            # Subtle row background
            if i % 2 == 0:
                draw.rectangle([44, ay - 4, W - 44, ay + row_h - 12], fill=(255, 255, 255, 3))

            # Rank
            draw.text((52, ay + 8), str(i + 1), fill=DIM, font=font_mono)

            # Symbol + class
            draw.text((80, ay + 2), symbol, fill=WHITE, font=font_md)
            draw.text((80, ay + 26), asset_class, fill=DIM, font=font_xs)

            # CIS score
            score_color = GREEN if score >= 65 else (GOLD if score >= 45 else DIM)
            draw.text((500, ay + 8), f"{score:.1f}", fill=score_color, font=font_mono_lg)

            # Grade badge
            _draw_grade_badge(draw, 600, ay + 2, grade, gc, font_md)

            # Signal
            sig_text = SIGNAL_SHORT.get(signal, signal)
            sig_color = GREEN if "OUTPERFORM" in signal else (GOLD if signal == "NEUTRAL" else RED)
            draw.text((740, ay + 8), sig_text, fill=sig_color, font=font_mono)

    # ── Bottom bar ──────────────────────────────────────────────────────────
    by = H - 52
    draw.line([(48, by - 12), (W - 48, by - 12)], fill=(255, 255, 255, 10), width=1)
    draw.text((48, by), "looloomi.ai/strategy", fill=DIM, font=font_mono_sm)

    if ref:
        draw.text((400, by), f"ref: {ref}", fill=GOLD, font=font_mono_sm)

    draw.text((W - 280, by), "For qualified investors only", fill=(30, 58, 95), font=font_mono_sm)

    # ── Export ──────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


def _draw_orb(img, cx, cy, radius, color, alpha):
    """Draw a soft ambient orb (Turrell-style glow)."""
    from PIL import Image, ImageDraw, ImageFilter
    orb = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(orb)
    r = radius
    a = int(alpha * 255)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, a))
    orb = orb.filter(ImageFilter.GaussianBlur(radius=radius // 3))
    # Composite
    bg = img.convert("RGBA")
    bg = Image.alpha_composite(bg, orb)
    img.paste(bg.convert("RGB"))


def _draw_grade_badge(draw, x, y, grade, color, font):
    """Draw a rounded grade badge."""
    bw, bh = 48, 34
    draw.rounded_rectangle([x, y, x + bw, y + bh], radius=8, fill=(*color[:3],), outline=None)
    # Center text in badge
    bbox = draw.textbbox((0, 0), grade, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x + (bw - tw) // 2, y + (bh - th) // 2 - 2), grade, fill=BG_COLOR, font=font)


# ── Endpoint ────────────────────────────────────────────────────────────────

@router.get("/og-image")
async def og_image(ref: Optional[str] = None):
    """
    Generate a 1200×630 OG image PNG with live CIS data.

    Query params:
      ref — referral code (shown on card)

    Returns: image/png (cached 2min in-memory)
    """
    cache_k = _cache_key(ref)

    # Check in-memory cache
    if cache_k in _og_cache:
        data, ts = _og_cache[cache_k]
        if time.time() - ts < _OG_CACHE_TTL:
            return Response(content=data, media_type="image/png",
                          headers={"Cache-Control": "public, max-age=600"})

    try:
        # Fetch live data
        top5 = await _fetch_cis_top5()
        macro = await _fetch_macro()

        # Render
        png_bytes = _render_og_card(top5, macro, ref=ref or "")

        # Cache
        _og_cache[cache_k] = (png_bytes, time.time())

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=600",
                "X-OG-Assets": str(len(top5)),
            },
        )
    except Exception as e:
        print(f"[OG] Render error: {e}")
        import traceback; traceback.print_exc()
        # Return a minimal fallback PNG (1x1 transparent) rather than 500
        import io
        try:
            from PIL import Image
            fb = Image.new("RGB", (1200, 630), BG_COLOR)
            buf = io.BytesIO()
            fb.save(buf, format="PNG")
            buf.seek(0)
            return Response(content=buf.getvalue(), media_type="image/png",
                          headers={"Cache-Control": "no-cache", "X-OG-Error": str(e)[:100]})
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail=f"OG image unavailable: {e}")


@router.get("/og-meta")
async def og_meta(ref: Optional[str] = None):
    """
    Return OG meta tag values for frontend SSR or edge injection.
    """
    base_url = "https://looloomi.ai"
    ref_param = f"?ref={ref}" if ref else ""

    return {
        "og:title": "CometCloud AI — AI Fund-of-Funds on Solana",
        "og:description": "AI-curated crypto intelligence. 70+ assets scored across 5 pillars. 0% management fee. Hong Kong regulated.",
        "og:image": f"{base_url}/api/v1/social/og-image{ref_param}",
        "og:url": f"{base_url}/strategy.html{ref_param}",
        "og:type": "website",
        "og:site_name": "CometCloud AI",
        "twitter:card": "summary_large_image",
        "twitter:title": "CometCloud AI — AI Fund-of-Funds",
        "twitter:description": "AI-curated crypto Fund-of-Funds. 70+ assets. 5-pillar scoring. Solana-native.",
        "twitter:image": f"{base_url}/api/v1/social/og-image{ref_param}",
    }
