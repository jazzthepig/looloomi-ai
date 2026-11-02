"""T-219: yfinance probe (public, no key) — can we get rail-ticker daily closes
for the risk profile while our own EODHD channel has not landed them yet?

Read-only. Prints coverage only.
"""
import sys, datetime as dt
import yfinance as yf

SYMS = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]

for s in SYMS:
    try:
        df = yf.Ticker(s).history(period="max", interval="1d", auto_adjust=False)
        if df is None or len(df) == 0:
            print("%-6s EMPTY" % s)
            continue
        cols = list(df.columns)
        print("%-6s n=%-6d %s..%s cols=%s" % (
            s, len(df), df.index[0].date(), df.index[-1].date(), cols[:8]))
    except Exception as e:
        print("%-6s ERR %s" % (s, str(e)[:140]))
    sys.stdout.flush()
