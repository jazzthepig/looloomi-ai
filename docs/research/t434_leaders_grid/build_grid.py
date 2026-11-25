"""龙头网格 v1(T-434 / 台账 S-912):各行业 × 各地区市值第一的公司 —— 研究池,不是产品池。

用法:
    python3 docs/research/t434_leaders_grid/build_grid.py <存放行业榜页面的目录> [链上成交额文件]

- 输入 = companiesmarketcap.com 行业榜页面的文本(每个行业一页,第一页 100 家;公开、免费、每日更新)。
  取数只走会话里的网页读取工具,把结果存成文件再喂给这个脚本 —— 脚本自己不联网。
- 规则写在台账 S-912(取数之前写死):行业 × 地区,市值第一且 ≥ 100 亿美元 = 龙头;第二名记为备选。
- 三个不到 100 家的行业(烟草、汽车、奢侈品)取回时没有落成文件,≥ 100 亿的行是手录的(见 HAND)。
- 行业归类与国家归属是站点的口径(站点把 Apple 放在「软件」、把 CATL 放在「电力」):行业标签只当索引用,正式用要再清一遍。
- 今天的快照,不是按时点的名单:拿它做任何历史检验之前,要另补「曾经的龙头」。
"""
import json, re, glob, os, sys
D = sys.argv[1] if len(sys.argv) > 1 else "."
ROW = re.compile(r"\|\s*(\d+)\s*\|\s*!\[[^\]]*\]\([^)]*\)<br>\[(.+?)\]\(https://companiesmarketcap\.com/([^/]+)/marketcap/\)\s*\|\s*\$([\d.,]+)\s*([TBM])\s*\|[^|]*\|[^|]*\|[^|]*\|\s*([^|]+?)\s*\|")
CAN = re.compile(r"canonical: https://companiesmarketcap\.com/([a-z0-9-]+)/")
def text_of(p):
    raw = open(p, encoding="utf-8", errors="ignore").read()
    if p.endswith(".json"):
        try:
            return json.loads(raw)[0]["text"]
        except Exception:
            return raw
    return raw
out = {}
for p in sorted(glob.glob(D + "/*")):
    t = text_of(p)
    m = CAN.search(t)
    if not m or "by market cap" not in t.lower():
        continue
    cat = m.group(1)
    if cat in ("all-categories",):
        continue
    rows = []
    for r in ROW.finditer(t):
        rank, nm, slug, num, unit, country = r.groups()
        mcap = float(num.replace(",", "")) * {"T": 1000.0, "B": 1.0, "M": 0.001}[unit]
        parts = nm.rsplit(" ", 1)
        name, ticker = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (nm, "")
        country = re.sub(r"^[^\w]+", "", country).strip()
        rows.append({"rank": int(rank), "name": name, "ticker": ticker, "slug": slug, "mcap_bn": round(mcap, 3), "country": country})
    if rows:
        out[cat] = rows
print({k: (len(v), v[-1]["mcap_bn"]) for k, v in out.items()})
RAW = out
countries = sorted({r["country"] for v in out.values() for r in v})
print(len(countries), countries)

# ── 网格 ──
import unicodedata
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
from collections import defaultdict
from src.data.universe import world50 as w
raw = RAW
# 三个行内取回的行业(页面不到 100 家,取回时没落文件):只录 ≥ 100 亿的
def rows(lst): return [{"rank": i + 1, "name": n, "ticker": t, "slug": n.lower().replace(" ", "-"), "mcap_bn": m, "country": c} for i, (n, t, m, c) in enumerate(lst)]
raw["tobacco"] = rows([("Philip Morris International","PM",284.45,"USA"),("British American Tobacco","BTI",122.99,"UK"),("Altria Group","MO",122.76,"USA"),("Japan Tobacco","2914.T",59.64,"Japan"),("ITC","ITC.NS",40.60,"India"),("Imperial Brands","IMB.L",27.36,"UK"),("KT&G (Korea Tobacco)","033780.KS",14.20,"S. Korea")])
raw["automakers"] = rows([("Tesla","TSLA",1523.0,"USA"),("Toyota","TM",249.0,"Japan"),("BYD","002594.SZ",105.57,"China"),("Xiaomi","XIACF",91.32,"China"),("Ferrari","RACE",69.94,"Italy"),("General Motors","GM",68.86,"USA"),("Hyundai","005380.KS",54.26,"S. Korea"),("Maruti Suzuki India","MARUTI.NS",47.41,"India"),("Ford","F",46.52,"USA"),("Mahindra & Mahindra","M&M.NS",45.07,"India"),("Honda","HMC",43.16,"Japan"),("Porsche","P911.DE",42.64,"Germany"),("Mercedes-Benz","MBG.DE",38.97,"Germany"),("Volkswagen","VOW3.DE",34.99,"Germany"),("BMW","BMW.DE",34.50,"Germany"),("Kia","000270.KS",27.37,"S. Korea"),("Suzuki Motor","7269.T",26.69,"Japan"),("Geely","0175.HK",18.26,"China"),("Stellantis","STLA",10.19,"Netherlands")])
raw["luxury-goods"] = rows([("LVMH","MC.PA",208.14,"France"),("Hermès","RMS.PA",141.91,"France"),("Compagnie Financière Richemont","CFR.SW",122.13,"Switzerland"),("EssilorLuxottica","EL.PA",87.04,"France"),("Dior","CDI.PA",83.15,"France"),("Titan Company","TITAN.NS",44.69,"India"),("Kering","KER.PA",23.53,"France"),("Chow Tai Fook","1929.HK",14.44,"Hong Kong"),("Prada","1913.HK",12.39,"Italy"),("Moncler","MONC.MI",12.03,"Italy"),("Pandora","PNDORA.CO",10.11,"Denmark")])
CN = {"semiconductors": "半导体", "software": "软件", "tech-hardware": "科技硬件", "internet": "互联网", "telecommunication": "电信", "banks": "银行", "insurance": "保险",
      "financial-services": "金融服务", "pharmaceuticals": "制药", "biotech": "生物科技", "medical-devices": "医疗器械", "automakers": "汽车", "retail": "零售", "luxury-goods": "奢侈品",
      "food": "食品", "tobacco": "烟草", "oil-gas": "石油天然气", "mining": "矿业", "chemicals": "化工", "manufacturing": "制造", "electricity": "电力", "real-estate": "房地产", "transportation": "运输"}
EU = {"UK","France","Germany","Switzerland","Netherlands","Spain","Italy","Sweden","Denmark","Finland","Norway","Belgium","Ireland","Austria","Portugal","Poland","Greece","Czech Republic","Hungary","Luxembourg","Romania","Iceland","Guernsey","Isle of Man"}
REG = {}
for c in EU: REG[c] = "欧洲"
REG.update({"USA": "美国", "Bermuda": "美国", "Canada": "加拿大", "Japan": "日本", "China": "中国 / 香港", "Hong Kong": "中国 / 香港", "S. Korea": "韩国 / 台湾", "Taiwan": "韩国 / 台湾", "India": "印度",
            "Australia": "澳新 / 东南亚", "New Zealand": "澳新 / 东南亚", "Singapore": "澳新 / 东南亚", "Indonesia": "澳新 / 东南亚", "Malaysia": "澳新 / 东南亚", "Thailand": "澳新 / 东南亚", "Philippines": "澳新 / 东南亚", "Vietnam": "澳新 / 东南亚",
            "Brazil": "拉美", "Mexico": "拉美", "Chile": "拉美", "Argentina": "拉美", "Colombia": "拉美", "Peru": "拉美", "Panama": "拉美", "Costa Rica": "拉美",
            "S. Arabia": "中东 / 非洲", "UAE": "中东 / 非洲", "Qatar": "中东 / 非洲", "Kuwait": "中东 / 非洲", "Israel": "中东 / 非洲", "Turkey": "中东 / 非洲", "South Africa": "中东 / 非洲", "Kazakhstan": "中东 / 非洲", "Pakistan": "中东 / 非洲"})
SKIP = {"Russia"}
FLOOR = 10.0
regs = ["美国", "欧洲", "日本", "中国 / 香港", "韩国 / 台湾", "印度", "加拿大", "澳新 / 东南亚", "拉美", "中东 / 非洲"]
cells = {}
unmapped = set()
for cat, rs in raw.items():
    by = defaultdict(list)
    for r in rs:
        if r["country"] in SKIP: continue
        g = REG.get(r["country"])
        if g is None: unmapped.add(r["country"]); continue
        if r["mcap_bn"] >= FLOOR: by[g].append(r)
    for g, lst in by.items():
        lst.sort(key=lambda r: -r["mcap_bn"])
        cells[(cat, g)] = lst[:2]
print("unmapped countries:", unmapped)
# 池 = 所有格子的第一名,按 slug 去重
pool = {}
for (cat, g), lst in cells.items():
    r = lst[0]
    p = pool.setdefault(r["slug"], {**r, "region": g, "leads": []})
    p["leads"].append(CN[cat])
print("industries:", len(raw), "cells possible:", len(raw) * len(regs), "cells with a leader:", len(cells), "pool (unique leaders):", len(pool))
# 对现有候选池
def norm(s): 
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()
SUF = {".T": ".TSE", ".KS": ".KO", ".SS": ".SHG", ".NS": ".NSE", ".DE": ".XETRA", ".L": ".LSE", ".AX": ".AU", ".SI": ".SG", ".SZ": ".SHE"}
def tk(t):
    for a, b in SUF.items():
        if t.endswith(a): return t[: -len(a)] + b
    return t
ours = {c.key: c for c in w.EQUITIES}
ours_name = {norm(c.name): c.key for c in w.EQUITIES}
ALIAS = {"alphabet google": "GOOGL", "meta platforms facebook": "META", "berkshire hathaway": "BRK-B", "tsmc": "TSM", "samsung": "005930.KO", "tencent": "TCEHY", "alibaba": "BABA", "toyota": "TM",
         "saudi aramco": "2222.SR", "icbc": "1398.HK", "jpmorgan chase": "JPM", "eli lilly": "LLY", "walmart": "WMT", "exxon mobil": "XOM", "nestle": "NESN.SW", "roche": "ROG.SW", "lvmh": "MC.PA",
         "hermes": "RMS.PA", "compagnie financiere richemont": "CFR.SW", "reliance industries": "RELIANCE.NSE", "bharti airtel": "BHARTIARTL.NSE", "sk hynix": "000660.KO", "petrobras": "PBR",
         "royal bank of canada": "RY", "commonwealth bank": "CBA.AU", "dbs": "D05.SG", "dbs group": "D05.SG", "novo nordisk": "NVO", "astrazeneca": "AZN", "novartis": "NVS", "hsbc": "HSBC", "shell": "SHEL",
         "mitsubishi ufj financial": "MUFG", "sony": "SONY", "china mobile": "0941.HK", "petrochina": "0857.HK", "kweichow moutai": "600519.SHG", "agricultural bank of china": "601288.SHG",
         "china construction bank": "601939.SHG", "bank of china": "601988.SHG", "ping an insurance": "601318.SHG", "china life insurance": "601628.SHG", "cnooc": "0883.HK", "bhp group": "BHP",
         "rio tinto": "RIO", "linde": "LIN", "sap": "SAP", "asml": "ASML", "siemens": "SIE.XETRA", "allianz": "ALV.XETRA", "deutsche telekom": "DTE.XETRA", "iberdrola": "IBE.MC", "shopify": "SHOP",
         "prosus": "PRX.AS", "mediatek": "2454.TW", "tokyo electron": "8035.TSE", "softbank": "9984.TSE", "fast retailing": "9983.TSE", "hitachi": "6501.TSE", "recruit": "6098.TSE"}
def match(p):
    t = tk(p["ticker"])
    if t in ours: return t
    n = norm(p["name"])
    if n in ours_name: return ours_name[n]
    if n in ALIAS and ALIAS[n] in ours: return ALIAS[n]
    for on, k in ours_name.items():
        if len(on) >= 5 and (n.startswith(on) or on.startswith(n)) : return k
    return None
VOL = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
n_in = 0
for s, p in pool.items():
    k = match(p); p["pool_key"] = k
    p["onchain_vol_m"] = float(VOL[k]) if k and k in VOL else None
    n_in += bool(k)
print("leaders already in our 173 pool:", n_in, "new:", len(pool) - n_in)
byreg = defaultdict(lambda: [0, 0, 0])
for p in pool.values():
    b = byreg[p["region"]]; b[0] += 1; b[1] += bool(p["pool_key"]); b[2] += bool(p["onchain_vol_m"] and p["onchain_vol_m"] >= 0.1)
print("region | leaders | already in pool | on-chain ≥ $100k/day")
for g in regs: print(g, byreg[g])
print("total", [sum(byreg[g][i] for g in regs) for i in range(3)])
# 网格
print("\nindustry | " + " | ".join(regs))
for cat in CN:
    line = []
    for g in regs:
        lst = cells.get((cat, g))
        line.append(f"{lst[0]['name'][:22]} ({lst[0]['mcap_bn']:.0f})" if lst else "·")
    print(CN[cat] + " | " + " | ".join(line))
json.dump({"as_of": "2026-11-25", "source": "companiesmarketcap.com industry rankings, first page (top 100 by market cap)", "floor_bn": FLOOR,
           "cells": [{"industry": CN[c], "category": c, "region": g, "leader": l[0], "runner_up": (l[1] if len(l) > 1 else None)} for (c, g), l in sorted(cells.items())],
           "pool": sorted(pool.values(), key=lambda p: -p["mcap_bn"])}, open(str(__import__("pathlib").Path(__file__).with_name("grid_v1.json")), "w"), ensure_ascii=False, indent=1)
