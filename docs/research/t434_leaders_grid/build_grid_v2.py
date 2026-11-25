"""龙头网格 v2(T-434 ③ / 台账 S-913):在 v1 上清行业标签、补 7 个行业,并给每个新名字定价格线(②)。研究池,不是产品池。

用法:
    python3 docs/research/t434_leaders_grid/build_grid_v2.py <存放行业榜页面的目录>

- 输入 = companiesmarketcap.com 行业榜页面的文本(每个行业一页,第一页 100 家;公开、免费)。取数只走会话里的网页读取工具,
  存成文件再喂给这个脚本 —— 脚本自己不联网。v1 的 23 页 + 新取的 6 页;消费品 / 烟草 / 汽车 / 奢侈品四页不足 100 家,≥ 100 亿的行手录(见 RAW[...] = rows(...))。
- **一家公司只归一个主行业**(S-913 规则 1):站点给了几个行业的,取 ORDER 里最靠前的;OVERRIDE 逐行改判、写理由。只能在主行业里当龙头。
- 价格线(规则 3):本地交易所 EODHD 可用 ⇒ 本地;纽约 / 纳斯达克正式上市 ⇒ 美国线;东京 / 印度 / 沙特 / 新加坡 / 米兰 EODHD 404,
  只在能确认的场外 ADR 代码时用美国场外线,不猜代码;其余记「无免费价格源」。
- 产物:同目录 `grid_v2.json`(格子 + 名单 + 规则);`src/data/universe/leaders_grid.json`(只含不在 World50 候选池、有价格线的名字 —— 周度整段重取用)。
- 今天的快照,不是按时点的名单:拿它做任何历史检验之前,要另补「曾经的龙头」(T-434 ⑤)。
"""
from collections import Counter

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
RAW = out
def rows(lst): return [{"rank": i + 1, "name": n, "ticker": t, "slug": n.lower().replace(" ", "-"), "mcap_bn": m, "country": c} for i, (n, t, m, c) in enumerate(lst)]
RAW["tobacco"] = rows([("Philip Morris International","PM",284.45,"USA"),("British American Tobacco","BTI",122.99,"UK"),("Altria Group","MO",122.76,"USA"),("Japan Tobacco","2914.T",59.64,"Japan"),("ITC","ITC.NS",40.60,"India"),("Imperial Brands","IMB.L",27.36,"UK"),("KT&G (Korea Tobacco)","033780.KS",14.20,"S. Korea")])
RAW["automakers"] = rows([("Tesla","TSLA",1523.0,"USA"),("Toyota","TM",249.0,"Japan"),("BYD","002594.SZ",105.57,"China"),("Xiaomi","XIACF",91.32,"China"),("Ferrari","RACE",69.94,"Italy"),("General Motors","GM",68.86,"USA"),("Hyundai","005380.KS",54.26,"S. Korea"),("Maruti Suzuki India","MARUTI.NS",47.41,"India"),("Ford","F",46.52,"USA"),("Mahindra & Mahindra","M&M.NS",45.07,"India"),("Honda","HMC",43.16,"Japan"),("Porsche","P911.DE",42.64,"Germany"),("Mercedes-Benz","MBG.DE",38.97,"Germany"),("Volkswagen","VOW3.DE",34.99,"Germany"),("BMW","BMW.DE",34.50,"Germany"),("Kia","000270.KS",27.37,"S. Korea"),("Suzuki Motor","7269.T",26.69,"Japan"),("Geely","0175.HK",18.26,"China"),("Stellantis","STLA",10.19,"Netherlands")])
RAW["luxury-goods"] = rows([("LVMH","MC.PA",208.14,"France"),("Hermès","RMS.PA",141.91,"France"),("Compagnie Financière Richemont","CFR.SW",122.13,"Switzerland"),("EssilorLuxottica","EL.PA",87.04,"France"),("Dior","CDI.PA",83.15,"France"),("Titan Company","TITAN.NS",44.69,"India"),("Kering","KER.PA",23.53,"France"),("Chow Tai Fook","1929.HK",14.44,"Hong Kong"),("Prada","1913.HK",12.39,"Italy"),("Moncler","MONC.MI",12.03,"Italy"),("Pandora","PNDORA.CO",10.11,"Denmark")])
EU = {"UK","France","Germany","Switzerland","Netherlands","Spain","Italy","Sweden","Denmark","Finland","Norway","Belgium","Ireland","Austria","Portugal","Poland","Greece","Czech Republic","Hungary","Luxembourg","Romania","Iceland","Guernsey","Isle of Man"}
REG = {}
for c in EU: REG[c] = "欧洲"
REG.update({"USA": "美国", "Bermuda": "美国", "Canada": "加拿大", "Japan": "日本", "China": "中国 / 香港", "Hong Kong": "中国 / 香港", "S. Korea": "韩国 / 台湾", "Taiwan": "韩国 / 台湾", "India": "印度",
            "Australia": "澳新 / 东南亚", "New Zealand": "澳新 / 东南亚", "Singapore": "澳新 / 东南亚", "Indonesia": "澳新 / 东南亚", "Malaysia": "澳新 / 东南亚", "Thailand": "澳新 / 东南亚", "Philippines": "澳新 / 东南亚", "Vietnam": "澳新 / 东南亚",
            "Brazil": "拉美", "Mexico": "拉美", "Chile": "拉美", "Argentina": "拉美", "Colombia": "拉美", "Peru": "拉美", "Panama": "拉美", "Costa Rica": "拉美",
            "S. Arabia": "中东 / 非洲", "UAE": "中东 / 非洲", "Qatar": "中东 / 非洲", "Kuwait": "中东 / 非洲", "Israel": "中东 / 非洲", "Turkey": "中东 / 非洲", "South Africa": "中东 / 非洲", "Kazakhstan": "中东 / 非洲", "Pakistan": "中东 / 非洲"})
SKIP = {"Russia"}
# 消费品 / 日化(页面只有 50 家,取回时没有落成文件;≥ 100 亿的 19 行照页面手录,S-913 记为偏差)
RAW["consumer-goods"] = rows([("Procter & Gamble","PG",399.74,"USA"),("L'Oréal","OR.PA",257.60,"France"),("Unilever","UL",140.46,"UK"),
    ("Colgate-Palmolive","CL",78.88,"USA"),("Kimberly-Clark","KMB",66.70,"USA"),("Hindustan Unilever","HINDUNILVR.NS",51.81,"India"),
    ("Reckitt Benckiser","RKT.L",47.32,"UK"),("Haleon","HLN",40.58,"UK"),("Estee Lauder","EL",39.17,"USA"),("Henkel","HEN3.DE",38.53,"Germany"),
    ("Kenvue","KVUE",37.10,"USA"),("Church & Dwight","CHD",26.51,"USA"),("Kaō","4452.T",23.46,"Japan"),("Beiersdorf","BEI.DE",19.27,"Germany"),
    ("Clorox","CLX",12.94,"USA"),("Marico","MARICO.NS",12.92,"India"),("Tata Consumer Products","TATACONSUM.NS",12.54,"India"),
    ("Unicharm","8113.T",12.09,"Japan"),("Shiseido","4911.T",10.79,"Japan")])

# 主行业:站点把一家放进几个行业时,取下面顺序里最靠前的那个(更具体的优先);再由 OVERRIDE 逐行改判(写理由)
# 几处有意的先后:硬件 > 软件(Apple);零售 / 运输 / 房地产 / 娱乐 > 互联网(Amazon / Uber / Equinix / Netflix);互联网 > 软件(Alphabet);
# 银行 > 保险 > 金融服务;制药 > 生物科技;半导体 / 汽车 / 航空航天 / 钢铁 > 制造;综合企业垫底
ORDER = ["semiconductors", "automakers", "aerospace", "steel-industry", "medical-devices", "pharmaceuticals", "biotech",
         "tech-hardware", "banks", "insurance", "financial-services", "real-estate", "electricity",
         "luxury-goods", "tobacco", "beverages", "consumer-goods", "retail", "transportation", "telecommunication",
         "entertainment", "internet", "software", "oil-gas", "chemicals", "mining", "construction", "food", "manufacturing", "conglomerate"]
OVERRIDE = {
    # 多重归属、按顺序会归错的
    "2882.TW": ("insurance", "国泰金控的主体是国泰人寿;站点同时放在银行 / 金融服务 / 保险"),
    "SE": ("internet", "Sea 的收入主体是 Shopee 电商与金融;站点同时放在娱乐 / 互联网"),
    "NPSNY": ("internet", "Naspers 是腾讯 / Prosus 的控股公司;站点同时放在娱乐 / 互联网"),
    "9984.T": ("conglomerate", "软银集团是投资控股公司;站点同时放在综合 / 金融服务 / 电信"),
    "0001.HK": ("conglomerate", "长江和记 = 港口 + 零售 + 基建 + 电信的综合企业;站点同时放在综合 / 电信"),
    # 只有一个归属、但归错的
    "300750.SZ": ("manufacturing", "宁德时代造电池(电气设备),不发电;站点只放在「电力」"),
    "373220.KS": ("manufacturing", "LG 新能源造电池(电气设备),不发电;站点只放在「电力」"),
    "GEV": ("manufacturing", "GE Vernova 造燃气轮机 / 电网设备,不是电力公司;站点只放在「电力」"),
    "ETN": ("manufacturing", "Eaton 是电气设备制造商;站点只放在「综合」"),
    "DHR": ("biotech", "Danaher 是生命科学 / 诊断工具,与 Thermo Fisher 同类(站点把后者放在「生物科技」);站点只放在「综合」"),
    "2359.HK": ("biotech", "药明康德是医药研发外包(CRO / CDMO),与康龙化成同类;按顺序会落在「医疗器械」"),
}

# ── v2 网格:主行业 → 行业 × 地区,市值第一且 ≥ 100 亿 ──
import unicodedata, pathlib
from collections import defaultdict
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from src.data.universe import world50 as w
FLOOR = 10.0
REGS = ["美国", "欧洲", "日本", "中国 / 香港", "韩国 / 台湾", "印度", "加拿大", "澳新 / 东南亚", "拉美", "中东 / 非洲"]
CN = {"semiconductors": "半导体", "software": "软件", "tech-hardware": "科技硬件", "internet": "互联网", "telecommunication": "电信",
      "banks": "银行", "insurance": "保险", "financial-services": "金融服务", "pharmaceuticals": "制药", "biotech": "生物科技",
      "medical-devices": "医疗器械", "automakers": "汽车", "retail": "零售", "luxury-goods": "奢侈品", "food": "食品", "tobacco": "烟草",
      "oil-gas": "石油天然气", "mining": "矿业", "chemicals": "化工", "manufacturing": "制造", "electricity": "电力", "real-estate": "房地产",
      "transportation": "运输", "beverages": "饮料", "consumer-goods": "消费品 / 日化", "steel-industry": "钢铁", "aerospace": "航空航天与国防",
      "conglomerate": "综合企业", "construction": "建筑与工程", "entertainment": "娱乐 / 游戏"}
assert set(CN) == set(ORDER) == set(RAW), set(CN) ^ set(RAW)
def ckey(r): return r["ticker"] or r["slug"]
member, info = defaultdict(set), {}
for cat, rs in RAW.items():
    for r in rs:
        if r["mcap_bn"] >= FLOOR and r["country"] in REG and r["country"] not in SKIP:
            k = ckey(r); member[k].add(cat); info.setdefault(k, r)
unused = sorted(set(OVERRIDE) - set(member))
assert not unused, f"改判表里有不在页面上的代码:{unused}"
primary = {k: (OVERRIDE[k][0] if k in OVERRIDE else min(c, key=ORDER.index)) for k, c in member.items()}
by_cell = defaultdict(list)
for k, c in primary.items():
    by_cell[(c, REG[info[k]["country"]])].append(k)
for v in by_cell.values():
    v.sort(key=lambda k: -info[k]["mcap_bn"])
# 对现有候选池(v1 的同一套匹配)
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
ALIAS = {"alphabet google": "GOOGL", "meta platforms facebook": "META", "berkshire hathaway": "BRK-B", "tsmc": "TSM", "samsung": "005930.KO",
         "tencent": "TCEHY", "alibaba": "BABA", "toyota": "TM", "saudi aramco": "2222.SR", "icbc": "1398.HK", "jpmorgan chase": "JPM",
         "eli lilly": "LLY", "walmart": "WMT", "exxon mobil": "XOM", "nestle": "NESN.SW", "roche": "ROG.SW", "lvmh": "MC.PA", "hermes": "RMS.PA",
         "compagnie financiere richemont": "CFR.SW", "reliance industries": "RELIANCE.NSE", "bharti airtel": "BHARTIARTL.NSE", "sk hynix": "000660.KO",
         "petrobras": "PBR", "royal bank of canada": "RY", "commonwealth bank": "CBA.AU", "dbs": "D05.SG", "dbs group": "D05.SG", "novo nordisk": "NVO",
         "astrazeneca": "AZN", "novartis": "NVS", "hsbc": "HSBC", "shell": "SHEL", "mitsubishi ufj financial": "MUFG", "sony": "SONY",
         "china mobile": "0941.HK", "petrochina": "0857.HK", "kweichow moutai": "600519.SHG", "agricultural bank of china": "601288.SHG",
         "china construction bank": "601939.SHG", "bank of china": "601988.SHG", "ping an insurance": "601318.SHG", "china life insurance": "601628.SHG",
         "cnooc": "0883.HK", "bhp group": "BHP", "rio tinto": "RIO", "linde": "LIN", "sap": "SAP", "asml": "ASML", "siemens": "SIE.XETRA",
         "allianz": "ALV.XETRA", "allianz se": "ALV.XETRA", "deutsche telekom": "DTE.XETRA", "iberdrola": "IBE.MC", "shopify": "SHOP", "prosus": "PRX.AS",
         "mediatek": "2454.TW", "tokyo electron": "8035.TSE", "softbank": "9984.TSE", "softbank group corp": "9984.TSE", "fast retailing": "9983.TSE",
         "hitachi": "6501.TSE", "recruit": "6098.TSE", "anheuser busch inbev": "BUD", "coca cola": "KO", "procter gamble": "PG"}
def match(r):
    t = tk(r["ticker"])
    if t in ours: return t
    n = norm(r["name"])
    if n in ours_name: return ours_name[n]
    if n in ALIAS and ALIAS[n] in ours: return ALIAS[n]
    for on, k in ours_name.items():
        if len(on) >= 5 and (n.startswith(on) or on.startswith(n)): return k
    return None

# ── 价格线(T-434 ②;规则见台账 S-913 第 3 条)──
SITE2EODHD = {"T": "TSE", "KS": "KO", "KQ": "KQ", "SS": "SHG", "SZ": "SHE", "NS": "NSE", "BO": "BSE", "DE": "XETRA", "L": "LSE",
              "AX": "AU", "SI": "SG", "HK": "HK", "TW": "TW", "TWO": "TWO", "PA": "PA", "AS": "AS", "MC": "MC", "MI": "MI", "SW": "SW",
              "ST": "ST", "CO": "CO", "HE": "HE", "OL": "OL", "BR": "BR", "VI": "VI", "LS": "LS", "IR": "IR", "TO": "TO", "V": "V",
              "MX": "MX", "SA": "SA", "SN": "SN", "BK": "BK", "JK": "JK", "KL": "KLSE", "VN": "VN", "F": "F"}
#: 实测(11-21 那轮 prices 段):这几个交易所的代码 EODHD 一律 HTTP 404
EODHD_404 = {"TSE", "NSE", "SR", "SG", "MI"}
#: EODHD 公开的交易所清单里没有、我们也没量过能用的(阿联酋、卡塔尔、以色列本地、南非、新西兰、科威特、土耳其、孟买)
NOT_SERVED = {"AE", "QA", "TA", "JO", "NZ", "KW", "IS", "BSE", "PK"}
#: 本地取不到 / 站点给的是场外代码而本地取得到 —— 逐行写理由。只收我能确认的代码,不猜。
LINE = {
    # 东京 404 → 美国场外 ADR
    "8766.T": ("TKOMY.US", "us_otc", "东京海上,场外 ADR"), "9432.T": ("NTTYY.US", "us_otc", "NTT,场外 ADR"),
    "4519.T": ("CHGCY.US", "us_otc", "中外制药,场外 ADR"), "4063.T": ("SHECY.US", "us_otc", "信越化学,场外 ADR"),
    "2914.T": ("JAPAY.US", "us_otc", "日本烟草,场外 ADR"), "4661.T": ("OLCLY.US", "us_otc", "东方乐园,场外 ADR"),
    "8802.T": ("MITEY.US", "us_otc", "三菱地所,场外 ADR"), "9020.T": ("EJPRY.US", "us_otc", "JR 东日本,场外 ADR"),
    "4543.T": ("TRUMY.US", "us_otc", "泰尔茂,场外 ADR"), "4452.T": ("KAOOY.US", "us_otc", "花王,场外 ADR"),
    "1605.T": ("IPXHY.US", "us_otc", "国际石油开发帝石,场外 ADR"), "2802.T": ("AJINY.US", "us_otc", "味之素,场外 ADR"),
    "5401.T": ("NPSCY.US", "us_otc", "日本制铁,场外 ADR"), "1925.T": ("DWAHY.US", "us_otc", "大和房屋,场外 ADR"),
    "9503.T": ("KAEPY.US", "us_otc", "关西电力,场外 ADR"), "2502.T": ("ASBFY.US", "us_otc", "朝日集团,场外 ADR"),
    # 新加坡 404 → 场外 ADR;南非不在清单 → 场外 ADR;哈萨克斯坦 → 纳斯达克
    "Z74.SI": ("SGAPY.US", "us_otc", "新电信,场外 ADR"), "F34.SI": ("WLMIY.US", "us_otc", "丰益国际,场外 ADR"),
    "SHP.JO": ("SRGHY.US", "us_otc", "Shoprite,场外 ADR"), "KKS.F": ("KSPI.US", "us_listed", "Kaspi 在纳斯达克上市(站点给的是法兰克福代码)"),
    # 站点给的是美国场外代码,本地交易所 EODHD 有 → 用本地
    "GMBXF": ("GMEXICOB.MX", "local", "墨西哥集团,墨西哥交易所 B 股"), "WMMVF": ("WALMEX.MX", "local", "沃尔玛墨西哥,墨西哥交易所"),
    "TNABY": ("5347.KLSE", "local", "国家能源(马来西亚),吉隆坡交易所"),
    "NZYM.VI": ("NSIS-B.CO", "local", "Novonesis 的主上市在哥本哈根(站点给的是维也纳代码)"),
}
def price_line(t: str) -> tuple:
    """站点代码 → (EODHD 代码 | None, 层级, 理由)。纯函数。"""
    if t in LINE:
        return LINE[t]
    if "." not in t:
        otc = len(t) == 5 and t[-1] in "FY"
        return (f"{t}.US", "us_otc" if otc else "us_listed", "美国场外" if otc else "美国上市")
    tick, suf = t.rsplit(".", 1)
    ex = SITE2EODHD.get(suf)
    if suf in NOT_SERVED or ex is None:
        return (None, None, f"EODHD 不列这个交易所({suf}),没有已确认的美国线")
    if ex in EODHD_404:
        return (None, None, f"EODHD 对 {ex} 返回 404(11-21 实测),没有已确认的美国线")
    return (f"{tick}.{ex}", "local", "本地交易所")

# ── 产物 ──
cells = []
pool = {}
for (cat, g), ks in sorted(by_cell.items(), key=lambda x: (ORDER.index(x[0][0]), REGS.index(x[0][1]))):
    lead, run = info[ks[0]], (info[ks[1]] if len(ks) > 1 else None)
    cells.append({"industry": CN[cat], "category": cat, "region": g, "leader": lead, "runner_up": run})
    k = ks[0]
    code, tier, why = price_line(k)
    pk = match(lead)
    pool[k] = {**lead, "region": g, "industry": CN[cat], "category": cat, "site_categories": sorted(member[k]),
               "override": OVERRIDE[k][1] if k in OVERRIDE else None, "pool_key": pk,
               "price_code": (ours[pk].code if pk else code), "price_tier": ("world50" if pk else tier),
               "price_why": ("已在 World50 候选池,沿用那边的代码" if pk else why)}
def research_key(code: str) -> str:
    return code[:-3] if code.endswith(".US") else code
research = [{"key": research_key(p["price_code"]), "name": p["name"], "code": p["price_code"], "region": p["region"],
             "industry": p["industry"], "tier": p["price_tier"], "site_ticker": p["ticker"]}
            for p in sorted(pool.values(), key=lambda p: -p["mcap_bn"]) if not p["pool_key"] and p["price_code"]]
keys = [r["key"] for r in research]
assert len(keys) == len(set(keys)), "研究宇宙里有重复的代码"
taken = {c.key for c in w.CANDIDATES} | {c.key for c in w.BENCHMARKS} | {c.key for c in w.RAIL_EQUITIES}
clash = sorted(set(keys) & taken)
research = [r for r in research if r["key"] not in taken]
new = [p for p in pool.values() if not p["pool_key"]]
print(f"行业 {len(ORDER)} · 格子 {len(ORDER) * len(REGS)} · 有龙头 {len(cells)} · 龙头 {len(pool)} · 已在候选池 {len(pool) - len(new)} · 新 {len(new)}")
print(f"新名字有价格线 {sum(1 for p in new if p['price_code'])} / {len(new)} ·", dict(Counter(p['price_tier'] for p in new)))
print("与已有代码撞名(只留候选池那边):", clash)
print("没有免费价格源:", sorted((p["region"], p["ticker"]) for p in new if not p["price_code"]))
v1 = {(c["category"], c["region"]): c["leader"]["slug"] for c in json.load(open(pathlib.Path(__file__).with_name("grid_v1.json")))["cells"]}
v2 = {(c["category"], c["region"]): c["leader"]["slug"] for c in cells}
changed = sorted(k for k in v1 if k in v2 and v1[k] != v2[k]); gone = sorted(k for k in v1 if k not in v2)
print(f"v1 的 {len(v1)} 格:换人 {len(changed)} · 消失 {len(gone)} · v2 新增格 {len(set(v2) - set(v1))}")
for k in changed: print("  换人", CN[k[0]], k[1], v1[k], "→", v2[k])
for k in gone: print("  消失", CN[k[0]], k[1], v1[k])
here = pathlib.Path(__file__)
json.dump({"as_of": "2026-11-25", "version": 2, "ledger": "S-913",
           "source": "companiesmarketcap.com 行业榜第一页(前 100);消费品 / 烟草 / 汽车 / 奢侈品四页不足 100 家、≥ 100 亿的行手录",
           "floor_bn": FLOOR, "regions": REGS, "industries": {c: CN[c] for c in ORDER},
           "rules": {"primary_order": ORDER, "overrides": {k: {"to": v[0], "why": v[1]} for k, v in OVERRIDE.items()}},
           "cells": cells, "pool": sorted(pool.values(), key=lambda p: -p["mcap_bn"])},
          open(here.with_name("grid_v2.json"), "w"), ensure_ascii=False, indent=1)
uni = here.resolve().parents[3] / "src" / "data" / "universe" / "leaders_grid.json"
uni.write_text(json.dumps({"as_of": "2026-11-25", "ledger": "S-913", "built_by": "docs/research/t434_leaders_grid/build_grid_v2.py",
                           "names": research}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("写了", here.with_name("grid_v2.json").name, "与", uni.relative_to(here.resolve().parents[3]), f"({len(research)} 个研究宇宙代码)")
