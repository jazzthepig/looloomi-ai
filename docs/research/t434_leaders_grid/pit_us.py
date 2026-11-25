"""按时点的龙头 · 美国部分 v1(T-434 ⑤ / 台账 S-915):每年 × 每个行业,当年公众流通市值第一的美国公司。研究用,不进任何账。

用法(脚本自己不联网、不连库;两张表只有服务端 key 能读,所以分两步):
    python3 docs/research/t434_leaders_grid/pit_us.py sql   > /tmp/pit_us.sql     # 生成查询(行业对照写在查询里)
    (在库上跑这段 SQL,把结果原样存成 JSON 数组)
    python3 docs/research/t434_leaders_grid/pit_us.py build <结果.json>           # → 同目录 pit_us_v1.json

规则写在台账 S-915(写代码、取全量之前定的),查询照它做:
  ① 守卫:单点 > 4 万亿美元,或 > 同一 CIK 其它年份的中位数 20 倍(只有两个点时 = 另一个点),
     或 > 同年总资产(`sec_assets`,CY{Y}Q4I)的 60 倍 ⇒ 当录入错误,不参与(计数带回)。后一条是结果 1 之后加的(事后修正)。
  ② 只算美国:`loc` 以 `US-` 开头。注册在爱尔兰 / 瑞士等地的 10-K 申报公司不算 —— 那些地区这里覆盖不全。
  ③ 行业:今天还在榜上的(现用代码对上 `members_v2.json` 里的美国公司)用网格的主行业;对不上的(多半已退市 / 被并购)用下面的 SIC 对照;
     对照之外 ⇒ 不归任何行业(计数带回,不猜)。**今天还在的公司用的是今天的归属**(GE 2016 年算在「航空航天」,不是当年的「综合企业」)。
  ④ 口径偏差:公众流通市值不含关联方持股 —— 家族 / 创始人控股的公司会被低估。
  年份 = 截至日(各公司第二财季末)所在的日历年;四页(Q1I–Q4I)里同一家同一年有两个点取最晚的(结果 1 之后改的:只取 Q2I 会漏掉
  Apple / Microsoft / Visa / 宝洁 / 迪士尼这类财年不在日历年的公司)。换过申报主体的旧 CIK 用 `world50_data.PREDECESSOR_CIKS` 接到今天的代码。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_VAL = 4e12
SPIKE_X = 20
FIRST_YEAR, LAST_YEAR = 2011, 2025          # 2009 / 2010 是 XBRL 推行期(692 / 1,839 个点),2026 还没报完(23 个点)

#: SIC → 网格的行业(先查单个代码,再按顺序查区间;都不中 = 不归)。只给对不上今天榜单的公司用。
SIC_CODE = {
    "1311": "oil-gas", "1381": "oil-gas", "1382": "oil-gas", "1389": "oil-gas", "2911": "oil-gas", "4922": "oil-gas", "4923": "oil-gas",
    "2080": "beverages", "2082": "beverages", "2084": "beverages", "2085": "beverages", "2086": "beverages",
    "2833": "pharmaceuticals", "2834": "pharmaceuticals", "2835": "pharmaceuticals", "2836": "biotech", "3826": "biotech",
    "2840": "consumer-goods", "2842": "consumer-goods", "2844": "consumer-goods",
    "3570": "tech-hardware", "3571": "tech-hardware", "3572": "tech-hardware", "3575": "tech-hardware", "3576": "tech-hardware",
    "3577": "tech-hardware", "3578": "tech-hardware", "3579": "tech-hardware", "3674": "semiconductors",
    "3711": "automakers", "3713": "automakers", "3812": "aerospace", "4841": "telecommunication",
    "4832": "entertainment", "4833": "entertainment", "5812": "food", "5961": "retail",
    "7370": "internet", "7371": "internet", "7374": "internet", "7372": "software", "7373": "software",
    "3731": "aerospace", "8711": "construction", "8731": "biotech",
    "6770": None, "9995": None, "7389": None,
}
SIC_RANGE = [
    ("1000", "1099", "mining"), ("1200", "1299", "mining"), ("1400", "1499", "mining"), ("1500", "1799", "construction"),
    ("2000", "2099", "food"), ("2100", "2199", "tobacco"), ("2700", "2799", "entertainment"), ("2800", "2899", "chemicals"),
    ("2900", "2999", "oil-gas"), ("3310", "3317", "steel-industry"), ("3600", "3629", "manufacturing"),
    ("3660", "3679", "tech-hardware"), ("3720", "3729", "aerospace"), ("3760", "3769", "aerospace"), ("3840", "3851", "medical-devices"),
    ("3000", "3999", "manufacturing"), ("4000", "4799", "transportation"), ("4810", "4899", "telecommunication"),
    ("4900", "4999", "electricity"), ("5000", "5999", "retail"), ("6020", "6039", "banks"), ("6100", "6299", "financial-services"),
    ("6300", "6411", "insurance"), ("6500", "6599", "real-estate"), ("6798", "6798", "real-estate"),
    ("7800", "7999", "entertainment"),
]
ASSET_X = 60
#: 换过申报主体的公司(与 world50_data.PREDECESSOR_CIKS 同一张表,这里抄一份让脚本不依赖仓库代码;测试比对两边一致)
PREDECESSOR = {"XOM": [34088], "GOOGL": [1288776], "DIS": [1001039], "AVGO": [1441634, 1649338]}


def sic_category(sic):
    s = str(sic or "")
    if s in SIC_CODE:
        return SIC_CODE[s]
    for lo, hi, cat in SIC_RANGE:
        if len(s) == 4 and lo <= s <= hi:
            return cat
    return None


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def grid_tickers() -> list[tuple[str, str]]:
    ms = json.load(open(HERE / "members_v2.json", encoding="utf-8"))["members"]
    out, seen = [], set()
    for m in ms:
        t = str(m.get("ticker") or "").upper()
        if m["region"] == "美国" and t and "." not in t and t not in seen:
            seen.add(t)
            out.append((t, m["category"]))
    return out


def sql() -> str:
    codes = " ".join(f"when {_q(k)} then {('NULL' if v is None else _q(v))}" for k, v in SIC_CODE.items())
    ranges = " ".join(f"when sic between {_q(lo)} and {_q(hi)} then {_q(c)}" for lo, hi, c in SIC_RANGE)
    grid = ",".join(f"({_q(t)},{_q(c)})" for t, c in grid_tickers())
    pred = ",".join(f"({c}::bigint,{_q(t)})" for t, cs in PREDECESSOR.items() for c in cs)
    return f"""with g(ticker, category) as (values {grid}),
f0 as (select cik, ccp, val, entity_name, extract(year from period_end)::int y,
              row_number() over (partition by cik, extract(year from period_end) order by period_end desc) rn
       from sec_public_float where loc like 'US-%'),
f as (select cik, ccp, val, entity_name, y from f0 where rn = 1),
a as (select cik, substr(ccp, 3, 4)::int y, val from sec_assets),
pr(cik, ticker) as (values {pred}),
s as (select cik, count(*) n, sum(val) tot, percentile_cont(0.5) within group (order by val) med from f group by cik),
k as (select f.* from f join s on s.cik = f.cik
      left join a on a.cik = f.cik and a.y = f.y
      where f.val <= {MAX_VAL:.0f} and not (s.n = 2 and f.val > {SPIKE_X} * (s.tot - f.val)) and not (s.n >= 3 and f.val > {SPIKE_X} * s.med)
        and not (a.val is not null and f.val > {ASSET_X} * a.val)),
tk as (select c.cik, upper(trim(t)) ticker from sec_company c, unnest(string_to_array(coalesce(c.tickers, ''), ',')) t
       union select cik, ticker from pr),
gm as (select tk.cik, min(g.category) category from tk join g using (ticker) group by tk.cik),
cat as (select c.cik, c.name, coalesce(c.tickers, (select string_agg(ticker, ',') from pr where pr.cik = c.cik)) tickers, c.sic,
          coalesce(gm.category,
          case c.sic {codes} else case {ranges} else null end end) category,
          case when gm.category is not null then 'grid' else 'sic' end how
        from sec_company c left join gm using (cik)),
r as (select k.y, cat.category, k.cik, cat.name, cat.tickers, cat.how, k.val,
             row_number() over (partition by k.y, cat.category order by k.val desc) rk
      from k join cat using (cik) where cat.category is not null and k.y between {FIRST_YEAR} and {LAST_YEAR})
select category, cik, left(name, 40) name, tickers, how, string_agg(y || ':' || round(val / 1e9), ',' order by y) yrs from r where rk = 1
group by 1, 2, 3, 4, 5
union all select 'guard_dropped', (select count(*) from f) - (select count(*) from k), null, null, null, null
union all select 'unmapped_companies', count(*), null, null, null, null from cat where category is null
order by 1, 6"""


def build(rows: list[dict]) -> dict:
    """SQL 的结果(每个行业 × 每个当过龙头的公司一行,`yrs` = 「年:十亿美元」逗号串)→ 名单。"""
    grid = json.load(open(HERE / "grid_v2.json", encoding="utf-8"))
    today = {c["category"]: str(c["leader"]["ticker"]).upper() for c in grid["cells"] if c["region"] == "美国"}
    meta = {r["category"]: r["cik"] for r in rows if r.get("yrs") is None}
    leaders, former = [], []
    for r in rows:
        if r.get("yrs") is None:
            continue
        yrs = [(int(a), float(b)) for a, b in (x.split(":") for x in r["yrs"].split(","))]
        ticks = {t.strip().upper() for t in str(r.get("tickers") or "").split(",") if t.strip()}
        item = {"category": r["category"], "cik": int(r["cik"]), "name": r["name"], "tickers": r.get("tickers"),
                "category_from": r["how"], "years": [y for y, _ in yrs], "float_bn": dict((str(y), v) for y, v in yrs),
                "listed_today": bool(ticks), "is_today_leader": bool(today.get(r["category"]) and today[r["category"]] in ticks)}
        leaders.append(item)
        if not item["is_today_leader"] and any(y >= 2015 for y in item["years"]):
            former.append({**item, "years_led_since_2015": [y for y in item["years"] if y >= 2015], "today_leader": today.get(r["category"])})
    leaders.sort(key=lambda x: (x["category"], x["years"][0]))
    former.sort(key=lambda x: (x["category"], x["years_led_since_2015"][0]))
    return {"leaders": leaders, "former_leaders": former,
            "guard_dropped_points": meta.get("guard_dropped"), "unmapped_companies": meta.get("unmapped_companies")}


def main():
    if sys.argv[1:2] == ["sql"]:
        print(sql())
        return
    rows = json.load(open(sys.argv[2], encoding="utf-8"))
    out = build(rows)
    f = out["former_leaders"]
    print(f"{FIRST_YEAR}–{LAST_YEAR} · 当过某个行业龙头的(公司 × 行业){len(out['leaders'])} · 2015 起当过龙头、今天不是的 {len(f)}(今天已不上市 "
          f"{sum(1 for x in f if not x['listed_today'])})· 守卫丢掉 {out['guard_dropped_points']} 点 · 不归行业的公司 {out['unmapped_companies']}")
    (HERE / "pit_us_v1.json").write_text(json.dumps({"as_of": "2026-11-25", "ledger": "S-915",
                                                     "measure": "SEC dei:EntityPublicFloat(非关联方持股市值,美元,各公司第二财季末)", **out},
                                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("写了 pit_us_v1.json")


if __name__ == "__main__":
    main()
