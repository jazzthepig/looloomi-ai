"""
VC funding rounds — a persistent record built from public news headlines.

Why this exists (2026-10-28, Jazz: "特别是 vc funding flows"):
  The VC Funding Flows panel showed ONE deal for a 180-day window. Structured
  funding-round APIs are gated (DeFiLlama /raises answers 402 since 2026-06;
  CryptoRank v2 funding rounds need a paid tier), and the fallback scanned the
  last ~20 RSS items per feed on every request and kept nothing — so a 180-day
  window could never hold more than a few hours of headlines.

  The facts themselves are public: "<Project> raises $8M seed led by <VC>" is
  printed by a dozen outlets for every round. This module turns those headlines
  into rows and KEEPS them (table `vc_funding_rounds`), so the window fills and
  stays filled.

What a row is — and is not:
  A round as REPORTED in headlines: project, amount as printed, stage, named
  investors, the earliest date it was reported, and every outlet that carried
  it. It is not a census (undisclosed and unreported rounds are missing) and
  amounts are as reported, not verified. The API says so on every response.

Sources (all public RSS; no scraping of pages, no bot-check workarounds):
  - Google News RSS search for funding phrasing ("crypto raises", "stablecoin
    raises", "crypto seed round", …). Each hit carries its publisher.
  - Direct RSS feeds of crypto outlets that serve RSS openly.

Pure functions (parse_headline, is_crypto, classify, merge_rounds, aggregate)
carry the logic and are unit-tested; the I/O wrappers are thin.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import re
import urllib.parse
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Optional

TABLE = "vc_funding_rounds"
WRITES_TABLES = (TABLE,)
WINDOW_DAYS = 180
MERGE_DAYS = 21          # the same project reported again within 21 days = the same round
UA = "CometCloud/1.0 vc-tracker (+https://looloomi.ai)"

# ── Queries / feeds ──────────────────────────────────────────────────────────
GN_QUERIES = (
    "crypto raises", "blockchain raises", "web3 raises", "stablecoin raises",
    "DeFi raises", "tokenization raises", "onchain raises", "crypto seed round",
    'crypto "series A"', "bitcoin startup raises",
)
DIRECT_FEEDS = (
    ("https://www.theblock.co/rss.xml", "The Block"),
    ("https://decrypt.co/feed", "Decrypt"),
    ("https://www.dlnews.com/arc/outboundfeeds/rss/", "DL News"),
    ("https://cointelegraph.com/rss", "Cointelegraph"),
    ("https://bitcoinmagazine.com/feed", "Bitcoin Magazine"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    ("https://blockworks.co/feed", "Blockworks"),
    ("https://thedefiant.io/feed", "The Defiant"),
)


def gn_url(query: str, *, when_days: Optional[int] = None,
           after: Optional[dt.date] = None, before: Optional[dt.date] = None) -> str:
    q = query
    if when_days:
        q += f" when:{when_days}d"
    if after:
        q += f" after:{after.isoformat()}"
    if before:
        q += f" before:{before.isoformat()}"
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
            + "&hl=en-US&gl=US&ceid=US:en")


# ── Vocabulary ───────────────────────────────────────────────────────────────
_CRYPTO_WORDS = re.compile(
    r"\b(crypto\w*|blockchain|web3|token\w*|on-?chain|defi|stablecoin\w*|bitcoin|btc|"
    r"ethereum|eth|solana|nft\w*|dao|layer[- ]?[12]|l2|rollup\w*|zk\w*|wallet\w*|rwa|perpetual\w*|"
    r"real[- ]world assets?|tether|usdc|usdt|circle|coinbase|binance|hyperliquid|"
    r"digital[- ]asset\w*|mining|miner\w*|validator\w*|staking|restaking|dex|perps?|"
    r"memecoin\w*|altcoin\w*|xrp|avalanche|polygon|arbitrum|base chain|sui|aptos|ton|"
    r"canton|cosmos|polkadot|cardano|near)\b", re.I)

# Investors whose presence makes a round crypto even when the headline does not say so.
CRYPTO_INVESTORS = (
    "paradigm", "a16z crypto", "polychain", "multicoin",
    "pantera", "dragonfly", "coinbase ventures", "yzi labs", "binance labs", "galaxy",
    "framework ventures", "electric capital", "hack vc", "variant fund", "1kx", "placeholder",
    "delphi", "spartan", "animoca", "okx ventures", "circle ventures", "tether",
    "blockchain capital", "dcg", "digital currency group", "cmt digital", "solana ventures",
    "dao5", "robot ventures", "arrington", "jump crypto", "wintermute", "castle island",
    "haun", "parafi", "standard crypto", "lightspeed faction", "nascent", "archetype",
    "maven11", "fabric ventures", "shima", "mechanism capital", "hashed", "hashkey",
    "amber group", "kenetic", "foresight ventures", "iosg", "sevenx", "arca", "bitkraft",
    "lemniscate", "selini", "fenbushi", "ngc ventures", "coinfund", "distributed global",
    "borderless capital", "symbolic capital", "ego death",
    "kraken ventures", "ripple", "ava labs", "consensys", "near foundation",
    "ethereum foundation", "sui foundation", "aptos labs", "gsr", "flowdesk", "cumberland",
)

# Publishers that only cover crypto. CryptoRank / TradingView / Yahoo are aggregators —
# they repost general business news, so their name alone says nothing.
CRYPTO_PUBLISHERS = {
    "the block", "coindesk", "decrypt", "the defiant", "blockworks", "dl news",
    "cointelegraph", "bitcoin magazine", "crypto briefing", "coingape", "coinmarketcap",
    "cryptonews", "cryptonews.net", "bloomingbit", "unchained", "beincrypto", "chainwire",
    "coinspeaker", "crypto.news", "the crypto times", "bitke", "cryptopolitan",
    "cryptoslate", "bitcoinist", "newsbtc", "u.today", "coinlive", "panews", "odaily",
    "wu blockchain", "chaincatcher", "foresight news", "the big whale", "protos",
}

_NOT_A_ROUND = re.compile(
    r"\b(price target|target to|targets?\b|dividend|stakes|risks?|questions?|concerns?|"
    r"alarm|eyebrows|odds|forecast|outlook|guidance|rates?|tariffs?|presale|pre-sale|"
    r"best crypto|100x|price prediction|ico\b|airdrop|before listing|listing price|launch price|"
    r"whitelist|stock jumps|shares (?:jump|rise|fall|slide|surge)|transfers?|inflows?|outflows?|withdraw\w*|"
    r"deposits?|hack\w*|exploit\w*|stolen|breach\w*|bailout|relief|in (?:eth|btc|usdc|usdt|sol)|"
    r"earnings|price hike|crypto buyers|new crypto(?! (?:venture )?funds?)|next crypto|meme ?coin presale)\b", re.I)
# Public-market capital (IPOs, offerings, warrants, PIPEs, treasury-company raises) is not venture flow.
_PUBLIC_MARKET = re.compile(
    r"\b(ipo|offering|warrants?|notes|convertible notes|pipe|at-the-market|atm program|preferred|"
    r"private placement|share sales?|shares|stock sales?|treasury company|treasury firm|to (?:its |the )?treasury|"
    r"(?:bitcoin|btc|eth|ether|sol|xrp) treasury|nasdaq|nyse|spac)\b", re.I)
_QUESTION = re.compile(r"^(what|how|why|when|where|who|is|are|can|will|should|does|do)\b", re.I)
_SPAM_PUBLISHERS = {"techbullion", "openpr.com", "openpr"}

_VERB = (r"raises?|raised|secures?|secured|closes?|closed|lands?|landed|nabs?|bags?|banks?|"
         r"snags?|gets?|receives?|completes?|announces?|pulls in|scores?|attracts?|draws?")
_AMOUNT = (r"(?P<ccy>US\$|USD\s?|\$|€|EUR\s?|£|GBP\s?)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
           r"(?P<unit>million|mln|mn|m|billion|bln|bn|b|thousand|k)?\b")
_MAIN = re.compile(rf"^(?P<pre>.+?)\s+(?P<verb>{_VERB})\s+(?:(?:a|an|another|an additional|additional|a fresh|fresh|"
                   rf"nearly|over|more than|about|around|almost|up to)\s+)?(?:(?P<undisc>undisclosed)|{_AMOUNT})",
                   re.I)
_POSSESSIVE_ROUND = re.compile(rf"^(?P<pre>.+?)[’']s\s+{_AMOUNT}\s+(?P<rnd>[\w -]{{0,25}}?)\s*(?:round|raise|funding)\b",
                               re.I)

_ROUND = re.compile(
    r"\b(pre-?seed|seed\+?|series\s*[a-f]\d?\+?|pre-series\s*[a-f]|strategic|private|growth|"
    r"token\s*(?:sale|round)|public\s*sale|extension|bridge|angel|convertible|debt|equity)\b"
    r"(?:\s+(?:round|funding|financing|raise))?", re.I)
# Intent, not a closed round ('plans to raise', 'in talks to raise'); relative clauses ('a startup that just raised').
_INTENT = re.compile(r"\b(plans?|planning|in talks|looking|seeks?|seeking|aims?|aiming|set|eyes|eyeing|"
                     r"considering|mulls?|weighs?|expected|reportedly)\s+(?:to\b|at\b)|\b(that|which|who|that's)\b|"
                     r"\b(backs|leads|joins|invests|bets|just|won|wins)\b|\s(and|&)$|\s(and|&)\s", re.I)
# Market statistics and multi-deal roundups are not a round.
_STATS = re.compile(r"\b(made up|% of|percent of|share of|quarterly total|weekly|this week|roundup|recap)\b", re.I)
# Listed digital-asset-treasury companies: their raises are public-market capital, not venture flow.
_LISTED_DAT = re.compile(r"^(strive|strategy|metaplanet|sharplink|bitmine|upexi|semler|twenty one|nakamoto|"
                         r"gamestop|defi development|sol strategies|ton strategy|cleanspark|iren|marathon|mara|"
                         r"riot|core scientific|hut 8|bitfarms|cipher|terawulf|hive)\b", re.I)
LARGE_UNSTAGED_USD = 500e6     # ≥ this with no stage named ⇒ listed, not in totals (likely notes / equity / debt)
_LED_BY = re.compile(r"\b(?:co-)?led\s+by\s+(?P<who>.+?)(?=\s+(?:to|for|at|as|in|amid|after|with|on|bringing|ahead|while)\b|[,;:(]|$)", re.I)
_FROM = re.compile(r"\b(?:from|backed\s+by|with\s+participation\s+from|joined\s+by)\s+(?P<who>.+?)"
                   r"(?=\s+(?:to|for|at|as|in|amid|after|on|bringing|ahead|while)\b|[;:(]|$)", re.I)
_VALUATION = re.compile(rf"\bat\s+(?:a\s+)?{_AMOUNT}\s*(?:token\s+)?(?:valuation|fdv|fully[- ]diluted)", re.I)
_TOTAL = re.compile(r"\b(total|cumulative|to date|bringing)\b", re.I)

_DESCRIPTOR = {
    "firm", "startup", "start-up", "platform", "protocol", "network", "company", "exchange",
    "provider", "developer", "project", "app", "wallet", "issuer", "lender", "marketplace",
    "bank", "neobank", "fintech", "insurer", "studio", "operator", "broker", "brokerage",
    "infrastructure", "custodian", "processor", "unicorn", "giant", "player", "maker",
    "builder", "solution", "service", "aggregator", "venue", "chain", "blockchain",
    "investor", "powerhouse", "vc", "heavyweight", "backer", "miner", "veteran", "darling", "pioneer",
    "upstart", "challenger", "newcomer", "darling",
    "layer", "rollup", "dex", "dapp", "tool", "trader", "manager", "outfit", "specialist",
}
_GENERIC_SUBJECT = re.compile(
    r"\b(startups|companies|firms|projects|sales|funds|vcs|investors|founders?|co-founders?|alumni|"
    r"veterans|executives|ceo|team|rounds|deals|sector|industry|market|ecosystem|this week|"
    r"bet|push|plan|move|arm|unit|division|subsidiary|campaign|community|coalition|users|holders)\b", re.I)
_PREFIX = re.compile(r"^(?:exclusive|breaking|crypto news|report|scoop|funding|update|news)\s*[:|–-]\s*", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def strip_publisher(title: str, publisher: str = "") -> str:
    """'X raises $8M - The Block' → 'X raises $8M'; CryptoRank reposts ': Decrypt - CryptoRank'."""
    t = _clean(title)
    if publisher and t.endswith(" - " + publisher):
        t = t[: -len(" - " + publisher)].rstrip()
    elif " - " in t and len(t.rsplit(" - ", 1)[1]) <= 40:
        t = t.rsplit(" - ", 1)[0].rstrip()
    t = re.sub(r":\s*(?:The Block|Decrypt|Fortune|CoinDesk|Bloomberg|Axios|The Defiant|DL News|"
               r"Blockworks|TechCrunch|Reuters|Cointelegraph|[A-Z][\w.]+)\s*$", "", t)
    return _PREFIX.sub("", t).strip()


def _amount_usd(m: re.Match) -> tuple[Optional[float], Optional[str], Optional[float]]:
    """(amount_usd or None, currency, amount_native). Non-USD → amount_usd None (no guessed FX)."""
    if not m or not m.group("num"):
        return None, None, None
    num = float(m.group("num").replace(",", ""))
    unit = (m.group("unit") or "").lower()
    mult = {"million": 1e6, "mln": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bln": 1e9,
            "bn": 1e9, "b": 1e9, "thousand": 1e3, "k": 1e3}.get(unit, 1.0)
    native = num * mult
    if native < 5e4:          # "$5" without a unit, or "$32,000", is not a venture round
        return None, None, None
    ccy = m.group("ccy").replace(" ", "").upper().replace("US$", "USD").replace("$", "USD")
    ccy = {"€": "EUR", "£": "GBP"}.get(ccy, ccy)
    return (native if ccy == "USD" else None), ccy, native


def _project_from_pre(pre: str) -> str:
    """Pull the project name out of the words before the verb.

    'Onchain credit firm Birch Hill' → 'Birch Hill'; 'Canton-Based Platform Cancore' → 'Cancore';
    'Y Combinator-backed Mochatrade' → 'Mochatrade'; 'South Africa’s CrissCross' → 'CrissCross'.
    """
    pre = re.split(r"\s+[–—]\s+|\s+-\s+", pre.strip())[0]
    words = pre.strip().strip(",").split()
    if not words:
        return ""
    cut = 0
    for i, w in enumerate(words[:-1]):
        lw = w.lower().strip(",")
        if lw.endswith(("’s", "'s")) or lw.endswith(("-backed", "-based", "-focused", "-native",
                                                    "-powered", "-led", "-founded", "-owned")):
            cut = i + 1
        elif lw in _DESCRIPTOR or lw.rstrip("s") in _DESCRIPTOR:
            cut = i + 1
    words = words[cut:]
    if "," in " ".join(words):
        return ""
    # Lower-case leading descriptors in sentence case ('compliance startup Predicate'):
    while (len(words) > 1 and words[0][:1].islower() and not any(c.isupper() for c in words[0][1:])
           and not any(c.isdigit() for c in words[0])):
        words = words[1:]
    name0 = " ".join(words)
    name0 = re.sub(r"\s+(token sale|ico|ido|public sale)$", "", name0, flags=re.I)
    words = name0.split()
    name = " ".join(words).strip(" ,:;-–")
    if not name or len(name) > 48 or _GENERIC_SUBJECT.search(name):
        return ""
    if re.search(r"\bstrategy$", name, re.I) or _LISTED_DAT.search(name):
        return ""          # 'TON Strategy', 'Strive' — listed treasury companies, not venture rounds
    if "$" in name or re.search(r"\d+(\.\d+)?\s*(%|million|billion)", name, re.I):
        return ""
    last = name.split()[-1].lower()
    if last in _DESCRIPTOR or last.rstrip("s") in _DESCRIPTOR:
        return ""          # 'Bitcoin mining company raises …' names no one
    if not (name[0].isupper() or name[0].isdigit() or any(c.isupper() for c in name)):
        return ""
    return name


def _split_investors(who: str) -> list[str]:
    who = re.sub(r"\s+(?:and|&)\s+others?\b.*$", "", who, flags=re.I)
    who = re.sub(r"\b(?:others|more|several|existing investors|angels?)\b.*$", "", who, flags=re.I)
    parts = re.split(r",\s*|\s+and\s+|\s+&\s+(?=[A-Z])", who)
    out = []
    for p in parts:
        p = p.strip(" .,'\"’")
        if 1 < len(p) <= 40 and (p[0].isupper() or p[0].isdigit() or p.lower().startswith("a16z")):
            out.append(p)
    return out[:6]


def is_crypto(title: str, publisher: str = "", investors: Iterable[str] = ()) -> Optional[str]:
    """Why this headline counts as crypto: 'keyword' | 'investor' | 'publisher' | None."""
    if _CRYPTO_WORDS.search(title):
        return "keyword"
    low = (title + " " + " ".join(investors)).lower()
    if any(re.search(rf"\b{re.escape(v)}\b", low) for v in CRYPTO_INVESTORS):
        return "investor"
    # A crypto-only publisher is NOT enough on its own: The Block and Decrypt also report AI
    # rounds (Manus, Nous, Bedrock Robotics). The publisher set is kept for the API's provenance only.
    return None


_CATS = (
    # A fund close: the money raised IS the fund ('raises $2.2B fund', '… $1B for new funds',
    # '… across flagship and new mid-market funds', 'Fund III'). Not '… for tokenized fund liquidity'.
    ("VC Fund", r"(?:\b(?:raises?|closes?|secures?)\s+(?:a\s+)?(?:US\$|\$|€)\s?[\d.,]+\s*"
                r"(?:million|billion|mln|bn|m|b)?\s+(?:for\s+|across\s+|in\s+)?(?:(?:its|a|new|fifth|fourth|"
                r"third|second|debut|flagship|crypto|growth|venture|early-stage|seed|ecosystem|mid-market|and|"
                r"two|three|blockchain|web3)\s+){0,4}funds?\b|\bfund\s+(?:i{1,3}|iv|v|vi)\b)"),
    ("RWA", r"\b(rwa|real[- ]world|tokeni[sz]\w*|treasur\w*|private credit|onchain credit|"
            r"securities|stock|equit(?:y|ies) onchain|tokenized)\b"),
    ("Payments", r"\b(stablecoin\w*|payments?|payroll|remittanc\w*|cross-border|card|neobank|"
                 r"onramp\w*|on-ramp\w*|off-ramp\w*|fx|banking)\b"),
    ("AI", r"\b(ai|artificial intelligence|agent\w*|llm|compute|gpu)\b"),
    ("Trading", r"\b(exchange|trading|perps?|perpetual\w*|derivatives?|broker\w*|market maker|"
                r"liquidity|dex|prediction market\w*)\b"),
    ("DeFi", r"\b(defi|lending|yield|amm|vault\w*|restaking|staking|borrow\w*)\b"),
    ("Infrastructure", r"\b(layer[- ]?[12]|l2|rollup\w*|zk\w*|infrastructure|infra|node\w*|"
                       r"validator\w*|data|oracle\w*|wallet\w*|custody|compliance|security|"
                       r"developer\w*|tooling|chain|protocol|privacy|interoperab\w*)\b"),
    ("Bitcoin", r"\b(bitcoin|btc|mining|miner\w*|lightning)\b"),
    ("Gaming", r"\b(gam\w+|metaverse|nft\w*|esports?)\b"),
)


def classify(text: str) -> str:
    for cat, pat in _CATS:
        if re.search(pat, text, re.I):
            return cat
    return "Other"


def parse_headline(title: str, publisher: str = "", pub_ts: Optional[float] = None,
                   link: str = "") -> Optional[dict[str, Any]]:
    """One headline → one reported round, or None. Deterministic; no network."""
    if publisher.strip().lower() in _SPAM_PUBLISHERS:
        return None
    t = strip_publisher(title, publisher)
    # 'Crypto VC funding: Tenstorrent…', 'TON News: …' — a short kicker before a colon is not the subject.
    while ": " in t:
        head, tail_ = t.split(": ", 1)
        if len(head) <= 40 and "$" not in head:
            t = tail_
        else:
            break
    if not t or _NOT_A_ROUND.search(t) or _QUESTION.search(t) or _PUBLIC_MARKET.search(t) or _STATS.search(t):
        return None
    if len(re.findall(rf"\b(?:{_VERB})\s+(?:\w+\s+)?(?:US\$|\$|€)\s?\d", t, re.I)) >= 2:
        return None        # 'ZeroStack secures $1B, Ripple raises $275M' — a roundup, not one round
    m = _MAIN.search(t)
    rnd_hint = None
    if m:
        pre = m.group("pre")
        amt = m if not m.group("undisc") else None
        tail = t[m.end():]
    else:
        m = _POSSESSIVE_ROUND.search(t)
        if not m:
            return None
        pre, amt, tail, rnd_hint = m.group("pre"), m, t[m.end():], (m.group("rnd") or "").strip()
        if "," in tail and re.search(r"(?:US\$|\$|€)\s?\d", tail):
            return None    # "Wonder's $650m raise, Crypto.com's $20b valuation, …" — a newsletter line
    if _INTENT.search(pre):
        return None
    project = _project_from_pre(pre)
    if not project:
        return None
    if amt is not None and re.match(r"\s*(?:token\s+)?(?:valuation|fdv)\b", t[amt.end():], re.I):
        vu = _amount_usd(amt)[0]       # 'Fasset lands $1 billion valuation' — a valuation, not a raise
        amt = None
        val_only = vu
    else:
        val_only = None
    usd, ccy, native = _amount_usd(amt) if amt is not None else (None, None, None)
    if amt is not None and native is None:
        return None
    rest = t[len(pre):]
    rm = _ROUND.search(rest) or (_ROUND.search(rnd_hint) if rnd_hint else None) or \
        re.search(r"\b(token\s*sale|public\s*sale)\b", t, re.I)
    rnd = _round_label(rm.group(1)) if rm else "Undisclosed stage"
    lead: list[str] = []
    lm = _LED_BY.search(tail)
    if lm:
        lead = _split_investors(lm.group("who"))
    investors = list(lead)
    fm = _FROM.search(tail)
    if fm:
        for v in _split_investors(fm.group("who")):
            if v not in investors:
                investors.append(v)
    vm = _VALUATION.search(t)
    valuation = (_amount_usd(vm)[0] if vm else None) or val_only
    basis = is_crypto(t, publisher, investors)
    if not basis:
        return None
    cat = classify(t)
    if cat == "VC Fund" and rm:      # a Seed / Series round is a company round, whatever else it mentions
        cat = classify(re.sub(r"\bfunds?\b", "", t, flags=re.I))
    if cat == "VC Fund":
        rnd = "Fund close"
    when = dt.datetime.fromtimestamp(pub_ts, dt.timezone.utc) if pub_ts else dt.datetime.now(dt.timezone.utc)
    return {
        "project": project,
        "project_norm": norm_project(project),
        "amount_usd": usd,
        "amount_native": native,
        "currency": ccy,
        "amount_kind": "cumulative" if _TOTAL.search(t) else "round",
        "round": rnd,
        "announced_date": when.date().isoformat(),
        "category": cat,
        "lead_investors": lead,
        "investors": investors,
        "valuation_usd": valuation,
        "headline": t[:300],
        "source_name": publisher or "",
        "source_url": link[:600],
        "sources": [publisher] if publisher else [],
        "crypto_basis": basis,
    }


def _round_label(raw: str) -> str:
    r = re.sub(r"\s+", " ", raw.strip()).lower()
    if r.startswith("pre") and "seed" in r:
        return "Pre-seed"
    if r.startswith("seed"):
        return "Seed"
    m = re.match(r"pre-series ([a-f])", r)
    if m:
        return f"Pre-Series {m.group(1).upper()}"
    m = re.match(r"series\s*([a-f]\d?\+?)", r)
    if m:
        return f"Series {m.group(1).upper()}"
    if r.startswith(("token", "public")):
        return "Token sale"
    return r.title()


_ALIASES = {
    r"^(a16z|andreessen horowitz)": "a16z",
    r"^(katie haun|haun)\b": "haun",
}


def norm_project(name: str) -> str:
    import unicodedata
    low = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    for alias, canon in _ALIASES.items():
        if re.search(alias, low):
            return canon
    n = re.sub(r"\b(inc|labs?|protocol|network|finance|fi|technolog(?:y|ies)|tech|ltd|llc|ag|corp|group|"
               r"ventures|capital|partners)\b\.?", "", re.sub(r"^0x", "", low))
    if len(re.sub(r"[^a-z0-9]", "", n)) < 3:      # 'Capital B' → 'b' is too short to identify anything
        n = low
    return re.sub(r"[^a-z0-9]", "", n) or re.sub(r"[^a-z0-9]", "", name.lower())


# ── Merge ────────────────────────────────────────────────────────────────────
_ROUND_RANK = {"Undisclosed stage": 0}


def _better_amount(a: dict, b: dict) -> dict:
    """Prefer a per-round USD amount over a cumulative one, then the most-reported value."""
    def key(x):
        return (x.get("amount_usd") is not None, x.get("amount_kind") == "round")
    return a if key(a) >= key(b) else b


def merge_rounds(existing: list[dict], new: list[dict]) -> list[dict]:
    """Fold new headline-rows into the stored rounds. Returns the rows to upsert (changed or new).

    Same project_norm with announced dates within MERGE_DAYS = the same round, reported again.
    The earliest date wins; amounts/stage/investors fill in; every outlet is listed once.
    """
    by_norm: dict[str, list[dict]] = {}
    for r in existing:
        by_norm.setdefault(r["project_norm"], []).append(dict(r))
    changed: dict[str, dict] = {}
    for n in sorted(new, key=lambda x: x["announced_date"]):
        bucket = by_norm.setdefault(n["project_norm"], [])
        d_new = dt.date.fromisoformat(n["announced_date"])
        hit = None
        for r in bucket:
            if abs((dt.date.fromisoformat(r["announced_date"]) - d_new).days) <= MERGE_DAYS:
                hit = r
                break
        if hit is None:
            row = dict(n)
            row["id"] = f'{n["project_norm"]}:{n["announced_date"]}'
            row["n_sources"] = len(row.get("sources") or []) or 1
            bucket.append(row)
            changed[row["id"]] = row
            continue
        before = repr(sorted(hit.items()))
        if n["announced_date"] < hit["announced_date"]:
            hit["announced_date"] = n["announced_date"]
        best = _better_amount(hit, n)
        if best is n:
            for k in ("amount_usd", "amount_native", "currency", "amount_kind"):
                hit[k] = n[k]
        if hit.get("round") in (None, "Undisclosed stage") and n.get("round") not in (None, "Undisclosed stage"):
            hit["round"] = n["round"]
        for k in ("lead_investors", "investors"):
            cur = list(hit.get(k) or [])
            low = {c.lower() for c in cur}
            for v in n.get(k) or []:
                if v.lower() not in low:
                    cur.append(v)
                    low.add(v.lower())
            hit[k] = cur[:8]
        if not hit.get("valuation_usd") and n.get("valuation_usd"):
            hit["valuation_usd"] = n["valuation_usd"]
        if hit.get("category") == "Other" and n.get("category") != "Other":
            hit["category"] = n["category"]
        srcs = list(hit.get("sources") or [])
        for s in n.get("sources") or []:
            if s and s not in srcs:
                srcs.append(s)
        hit["sources"] = srcs[:12]
        hit["n_sources"] = max(len(srcs), 1)
        if hit.get("crypto_basis") != "keyword" and n.get("crypto_basis") == "keyword":
            hit["crypto_basis"] = "keyword"
        if repr(sorted(hit.items())) != before:
            changed[hit["id"]] = hit
    return list(changed.values())


# ── Aggregate (what the panel shows) ─────────────────────────────────────────
def aggregate(rows: list[dict], today: dt.date, window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    start = today - dt.timedelta(days=window_days)
    inwin = [r for r in rows if r.get("announced_date") and dt.date.fromisoformat(str(r["announced_date"])[:10]) >= start]
    rounds = [r for r in inwin if r.get("category") != "VC Fund"]
    funds = [r for r in inwin if r.get("category") == "VC Fund"]
    held_out = [r for r in rounds if not in_totals(r)]
    disclosed = [r for r in rounds if r.get("amount_usd") and in_totals(r)]
    by_cat: dict[str, dict] = {}
    for r in rounds:
        c = by_cat.setdefault(r.get("category") or "Other", {"deals": 0, "usd": 0.0})
        c["deals"] += 1
        c["usd"] += float(r.get("amount_usd") or 0) if in_totals(r) else 0.0
    inv: dict[str, dict] = {}
    for r in rounds:
        leads = {x.lower() for x in r.get("lead_investors") or []}
        for v in r.get("investors") or []:
            k = v.strip()
            e = inv.setdefault(k.lower(), {"name": k, "deals": 0, "led": 0})
            e["deals"] += 1
            e["led"] += int(k.lower() in leads)
    top_inv = sorted(inv.values(), key=lambda e: (-e["deals"], -e["led"], e["name"]))[:10]
    weeks: dict[str, dict] = {}
    for r in rounds:
        d = dt.date.fromisoformat(str(r["announced_date"])[:10])
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
        w = weeks.setdefault(wk, {"week": wk, "deals": 0, "usd": 0.0})
        w["deals"] += 1
        w["usd"] += float(r.get("amount_usd") or 0) if in_totals(r) else 0.0
    earliest = min((str(r["announced_date"])[:10] for r in rows), default=None)
    return {
        "window_days": window_days,
        "deals": len(rounds),
        "disclosed_deals": len(disclosed),
        "total_usd": round(sum(float(r["amount_usd"]) for r in disclosed), 0),
        "median_usd": _median([float(r["amount_usd"]) for r in disclosed]),
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1]["usd"])),
        "top_investors": top_inv,
        "weekly": sorted(weeks.values(), key=lambda w: w["week"]),
        "held_out_of_totals": len(held_out),
        "held_out_rule": (f"rounds of ≥ ${LARGE_UNSTAGED_USD / 1e6:.0f}M with no stage named are listed but kept out "
                          "of totals — at that size an unnamed stage is usually notes, debt or listed equity"),
        "fund_closes": len(funds),
        "fund_closes_usd": round(sum(float(r.get("amount_usd") or 0) for r in funds), 0),
        "record_starts": earliest,
        "covers_window": bool(earliest and dt.date.fromisoformat(earliest) <= start + dt.timedelta(days=7)),
    }


def in_totals(r: dict) -> bool:
    amt = float(r.get("amount_usd") or 0)
    return not (amt >= LARGE_UNSTAGED_USD and (r.get("round") or "Undisclosed stage") == "Undisclosed stage")


def _median(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def to_api_row(r: dict) -> dict[str, Any]:
    """Stored row → the shape the panel already reads (name/amount/round/date/leadInvestors…)."""
    d = dt.date.fromisoformat(str(r["announced_date"])[:10])
    ts = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
    return {
        "name": r["project"], "project": r["project"],
        "amount": int(r["amount_usd"]) if r.get("amount_usd") else 0,
        "amount_disclosed": bool(r.get("amount_usd")),
        "amount_kind": r.get("amount_kind"),
        "amount_native": r.get("amount_native"), "currency": r.get("currency"),
        "round": r.get("round") or "Undisclosed stage",
        "date": ts, "date_str": d.isoformat(),
        "category": r.get("category") or "Other", "categoryGroup": r.get("category") or "Other",
        "sector": r.get("category") or "Other", "chains": [],
        "leadInvestors": r.get("lead_investors") or [],
        "lead_investor": (r.get("lead_investors") or [None])[0],
        "investors": r.get("investors") or [],
        "valuation_usd": r.get("valuation_usd"),
        "in_totals": in_totals(r),
        "description": r.get("headline") or "",
        "source": r.get("source_name") or "news",
        "sources": r.get("sources") or [], "n_sources": r.get("n_sources") or 1,
        "link": r.get("source_url") or "",
    }


# ── I/O ──────────────────────────────────────────────────────────────────────
def parse_rss(xml_text: str, default_publisher: str = "") -> list[dict]:
    """RSS 2.0 → [{title, publisher, pub_ts, link}]. Google News items carry <source>."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    ch = root.find("channel")
    if ch is None:
        return []
    out = []
    for it in ch.findall("item"):
        title = it.findtext("title") or ""
        src = it.find("source")
        pub = (src.text if src is not None and src.text else default_publisher) or ""
        ts = None
        pd = (it.findtext("pubDate") or "").strip()
        if pd:
            try:
                ts = parsedate_to_datetime(pd).timestamp()
            except Exception:
                ts = None
        out.append({"title": title, "publisher": _clean(pub), "pub_ts": ts, "link": it.findtext("link") or ""})
    return out


def extract(items: Iterable[dict], since: Optional[dt.date] = None) -> list[dict]:
    rows = []
    for it in items:
        r = parse_headline(it["title"], it.get("publisher", ""), it.get("pub_ts"), it.get("link", ""))
        if r and (since is None or r["announced_date"] >= since.isoformat()):
            rows.append(r)
    return rows


async def _get(client, url: str) -> Optional[str]:
    try:
        r = await client.get(url, follow_redirects=True)
        if r.status_code == 200 and "<rss" in r.text[:400]:
            return r.text
    except Exception:
        return None
    return None


async def fetch_headlines(urls: list[tuple[str, str]], pause_s: float = 3.0) -> tuple[list[dict], dict]:
    """Sequential, paced. Returns (items, {ok, failed})."""
    import httpx
    items: list[dict] = []
    ok, failed = 0, []
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=15) as client:
        for i, (url, publisher) in enumerate(urls):
            if i:
                await asyncio.sleep(pause_s)
            txt = await _get(client, url)
            if txt is None:
                failed.append(publisher or url[:60])
                continue
            ok += 1
            items.extend(parse_rss(txt, publisher))
    return items, {"ok": ok, "failed": failed}


async def load_rows(since: dt.date) -> list[dict]:
    """Stored rounds announced on/after `since`. Raises when the table cannot be read (≠ 0 rows)."""
    from src.data.style.header import _read_all
    rows = await _read_all(TABLE, {"select": "*", "announced_date": f"gte.{since.isoformat()}",
                                   "order": "announced_date.desc,id.asc"})
    for r in rows:
        r["announced_date"] = str(r["announced_date"])[:10]
    return rows


async def collect_once(*, backfill_weeks: int = 0, backfill_start: int = 0,
                       now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """One pass: live queries (+ optional weekly backfill windows) → parse → merge → upsert."""
    from src.api.store import supabase_upsert_table
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date()
    urls: list[tuple[str, str]] = [(gn_url(q, when_days=2), "") for q in GN_QUERIES]
    urls += list(DIRECT_FEEDS)
    for w in range(backfill_start, backfill_start + backfill_weeks):
        b = today - dt.timedelta(days=7 * w)
        a = b - dt.timedelta(days=7)
        urls += [(gn_url(q, after=a, before=b), "") for q in GN_QUERIES]
    items, fetch = await fetch_headlines(urls)
    since = today - dt.timedelta(days=WINDOW_DAYS + 7)
    parsed = extract(items, since)
    existing = await load_rows(today - dt.timedelta(days=WINDOW_DAYS + MERGE_DAYS + 7))
    upserts = merge_rounds(existing, parsed)
    stamp = now.isoformat()
    for r in upserts:
        r["updated_at"] = stamp
        r.setdefault("first_seen_at", stamp)
    w = None
    if upserts:
        w = await supabase_upsert_table(TABLE, upserts, on_conflict="id")
        if not getattr(w, "ok", False):
            return {"status": "error", "reason": f"upsert failed: {getattr(w, 'error', w)}"[:300],
                    "headlines": len(items), "parsed": len(parsed), "fetch": fetch}
    return {"status": "ok", "headlines": len(items), "parsed": len(parsed), "upserted": len(upserts),
            "stored_in_window": len(existing), "fetch": fetch}
