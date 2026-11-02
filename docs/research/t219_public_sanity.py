"""T-219: sanity read of the public-source series (last close vs the venue table prices,
and the shape of the pre-listing part of GLXY / new listings).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "t219_nasdaq_raw.json")))["series"]

VENUE = {"CRCL": 73.61, "COIN": 143.52, "HOOD": 86.581, "MSTR": 134.67}  # HL marks 11-02 from §2.3

for s in ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]:
    ser = raw[s]
    ds = sorted(ser)
    print("%-6s first %s close %.2f | last %s close %.2f | n=%d" % (
        s, ds[0], ser[ds[0]], ds[-1], ser[ds[-1]], len(ser)))
    if s in VENUE:
        print("        HL perp mark (11-02) %.2f -> ratio nq_last/HL %.4f" % (
            VENUE[s], ser[ds[-1]] / VENUE[s]))
    # first 6 monthly closes (shape check)
    seen, line = set(), []
    for d in ds:
        k = d[:7]
        if k not in seen:
            seen.add(k)
            line.append("%s:%.2f" % (k, ser[d]))
        if len(line) >= 6:
            break
    print("        monthly first-6: %s" % " ".join(line))
