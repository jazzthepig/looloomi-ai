"""VC funding rounds from headlines (src/data/vc/rounds_store.py) — parser, merge, aggregate.

Headlines below are written for the test (same shapes as real wires), not copied from any outlet.
"""
import datetime as dt

from src.data.vc.rounds_store import (
    aggregate, classify, gn_url, is_crypto, merge_rounds, norm_project, parse_headline,
    parse_rss, strip_publisher, to_api_row,
)

TS = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc).timestamp()


def p(title, pub="The Block", ts=TS):
    return parse_headline(title, pub, ts, "https://example.test/x")


def test_basic_round_with_lead():
    r = p("Onchain credit firm Gravel Hill raises $4M seed led by Multicoin Capital - The Block")
    assert r["project"] == "Gravel Hill"
    assert r["amount_usd"] == 4_000_000
    assert r["round"] == "Seed"
    assert r["lead_investors"] == ["Multicoin Capital"]
    assert r["announced_date"] == "2026-10-20"
    assert r["category"] == "RWA"


def test_descriptor_prefixes_are_cut():
    assert p("Canton-Based Platform Corecan Raises $7.2 Million Seed Round to Expand RWA Liquidity")["project"] == "Corecan"
    assert p("Y Combinator-backed Mochafin raises $5.5 million to offer stock perpetuals")["project"] == "Mochafin"
    assert p("South Africa’s CrossLine raises undisclosed Circle Ventures investment in stablecoin push")["project"] == "CrossLine"
    assert p("Bitcoin Life Insurer Meantime Raises $37.5M as Families Pass On Their BTC")["project"] == "Meantime"


def test_amount_forms():
    assert p("Plume Pay raises USD 15 mln Series A led by Tether")["amount_usd"] == 15_000_000
    assert p("Stackr raises $1.2 billion for stablecoin rails")["amount_usd"] == 1_200_000_000
    eur = p("Tokenhaus raises €7 million in Series A for tokenized bonds")
    assert eur["amount_usd"] is None and eur["currency"] == "EUR" and eur["amount_native"] == 7_000_000
    und = p("CrossLine raises undisclosed amount from Circle Ventures for stablecoin payments")
    assert und["amount_usd"] is None and und["amount_native"] is None


def test_investors_from_and_valuation():
    r = p("Zdev Lab Raises $25M From Paradigm and a16z crypto to build privacy tooling")
    assert r["investors"] == ["Paradigm", "a16z crypto"]
    v = p("Canton trading venue Corecan raises $7.2 million at $60 million token valuation")
    assert v["valuation_usd"] == 60_000_000


def test_not_rounds():
    assert p("Citigroup raises 12-month bitcoin target to $113,000") is None
    assert p("DeFi Dev Raises Preferred Dividend to 14% for November") is None
    assert p("Bitcoin rally failure raises the risk of a deeper crypto pullback") is None
    assert p("Treasury co Strive raises $630M in IPO, keeps bitcoin allocation open") is None
    assert p("Some Crypto Co raises $75,000 in private sale of 9,000,000 shares") is None
    assert p("Best crypto presale: Pepeta raises $11M before listing", "TechBullion") is None
    assert p("Crypto Payroll: What Mural’s $15M Raise Means Now") is None
    assert p("Bitcoin mining company raises $16M to push into AI compute") is None
    assert p("Public Token Sales Raise $40 Million, Lowest Quarterly Total in Four Years") is None


def test_crypto_filter_needs_keyword_or_crypto_investor():
    # Generalist AI round reported by a crypto outlet is NOT a crypto round.
    assert p("AI Startup Manuscript Raises $500 Million After Acquisition Blocked", "Decrypt") is None
    # Crypto investor makes it crypto even without a crypto word.
    assert p("Hylox raises $1M led by Solana Ventures to expand") is not None
    assert is_crypto("Acme raises $5M for stablecoin payroll") == "keyword"
    assert is_crypto("Acme raises $5M led by Polychain") == "investor"
    assert is_crypto("Acme raises $5M for invoices", "The Block") is None


def test_kicker_and_publisher_stripping():
    assert strip_publisher("Acme raises $5M - CryptoRank", "CryptoRank") == "Acme raises $5M"
    r = p("Exclusive: Predikat raises $8M for crypto compliance", "Axios")
    assert r["project"] == "Predikat"
    r2 = p("Crypto VC funding: Datalyne raises $10.6 million seed for onchain data")
    assert r2["project"] == "Datalyne"


def test_fund_close_vs_round():
    f = p("Crypto investor Hollow Ventures raises $1 billion for new funds")
    assert f["category"] == "VC Fund" and f["round"] == "Fund close"
    r = p("Fizzion Raises $10 Million Series A Led By Pantera Capital For Tokenized Fund Liquidity")
    assert r["category"] != "VC Fund" and r["round"] == "Series A"


def test_norm_project():
    assert norm_project("Luxor Technology") == norm_project("Luxor")
    assert norm_project("0xPredikat") == norm_project("Predikat")
    assert norm_project("Nectar Group") == norm_project("Nectar")


def _row(title, pub, day):
    ts = dt.datetime(2026, 10, day, 9, tzinfo=dt.timezone.utc).timestamp()
    return parse_headline(title, pub, ts, "")


def test_merge_same_round_across_outlets():
    a = _row("Spicenet raises $5M Series A led by dao5 for onchain brokerage", "The Block", 27)
    b = _row("On-chain brokerage Spicenet raises $5M led by dao5", "Dealroom", 26)
    c = _row("Spicenet raises $5 million, bringing total funding to $8 million for onchain trading", "citybiz", 28)
    out = merge_rounds([], [a, b, c])
    assert len(out) == 1
    m = out[0]
    assert m["announced_date"] == "2026-10-26"          # earliest report
    assert m["round"] == "Series A"                      # filled from a later headline
    assert m["amount_usd"] == 5_000_000 and m["amount_kind"] == "round"   # per-round beats cumulative
    assert set(m["sources"]) == {"The Block", "Dealroom", "citybiz"} and m["n_sources"] == 3


def test_merge_into_existing_returns_only_changes():
    a = _row("Spicenet raises $5M Series A led by dao5 for onchain brokerage", "The Block", 27)
    first = merge_rounds([], [a])
    again = merge_rounds(first, [a])
    assert again == []                                   # nothing new → nothing to write
    later = _row("Spicenet raises another $20M Series B for onchain trading", "The Block", 27 - 0)
    later["announced_date"] = "2026-12-15"
    assert len(merge_rounds(first, [later])) == 1        # > 21 days apart → a new round


def test_aggregate():
    rows = merge_rounds([], [
        _row("Gravel Hill raises $4M seed led by Multicoin Capital for onchain credit", "The Block", 20),
        _row("Plume Pay raises $15M Series A led by Tether for stablecoin payroll", "The Block", 21),
        _row("Polyfund raises $2.2 billion for new crypto fund", "The Block", 22),
        _row("CrossLine raises undisclosed amount from Tether for stablecoin payments", "The Block", 23),
    ])
    a = aggregate(rows, dt.date(2026, 10, 28))
    assert a["deals"] == 3 and a["disclosed_deals"] == 2
    assert a["total_usd"] == 19_000_000
    assert a["fund_closes"] == 1 and a["fund_closes_usd"] == 2_200_000_000
    assert a["top_investors"][0]["name"] == "Tether" and a["top_investors"][0]["deals"] == 2
    assert a["covers_window"] is False                   # record starts 10-20, window starts 05-01
    api = to_api_row(rows[0])
    assert {"name", "amount", "round", "date", "leadInvestors", "category", "sources"} <= set(api)


def test_classify_and_url():
    assert classify("raises $8M to build stablecoin payroll") == "Payments"
    assert classify("raises $8M for perpetuals exchange") == "Trading"
    assert "after%3A2026-05-01" in gn_url("crypto raises", after=dt.date(2026, 5, 1))


def test_parse_rss_google_news_shape():
    xml = ("<rss><channel><item><title>Acme raises $5M seed for stablecoin rails - The Block</title>"
           "<link>https://news.google.com/x</link><pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>"
           "<source url=\"https://www.theblock.co\">The Block</source></item></channel></rss>")
    items = parse_rss(xml)
    assert items[0]["publisher"] == "The Block"
    r = parse_headline(items[0]["title"], items[0]["publisher"], items[0]["pub_ts"], items[0]["link"])
    assert r["project"] == "Acme" and r["announced_date"] == "2026-10-27"
