"""World50 的两份输入:候选的历史市值(按时点排名)与链上可持有的形式(资格)—— T-098 第二部分。

## 历史市值 → `world50_mcap_weekly`

- 公司:**SEC EDGAR 报告的股本 × 原始收盘**(Jazz 10-14 定;EODHD 基本面与历史市值我们的套餐都没有,403)。
  不在 SEC 申报的公司:**各自交易所 / 法定披露平台原始文件里的股本 × 本币收盘 × 汇率**(Jazz 10-15,`EXCHANGE_SHARES`,
  每行带出处;后续由 T-100 补)。
  股本有四种口径:封面股数(`dei:EntityCommonStockSharesOutstanding`)、期末股数(`us-gaap:CommonStockSharesOutstanding`)、
  每季加权平均基本股数(`us-gaap:WeightedAverageNumberOfSharesOutstandingBasic`)、IFRS 年度加权平均(`ifrs-full:WeightedAverageShares`)。
  结构化数据里核实是录入错误的点按原文件更正(`SEC_FIX`);接口取不到的公司手工从 10-K 补(`MANUAL_SHARES`,每行带 accession)。多股类公司按类别报的不在这个接口里,
  有的公司某种口径只报到某一年 —— 所以**选最后一次报送最晚的口径**(差 120 天内按上面的顺序),
  最后一次报送比最新价格早 500 天以上 ⇒ 股数太旧,不写。换过申报主体的接上旧 CIK(`PREDECESSOR_CIKS`)。
  **按报送日(filed)才算已知**,同一期取最早报送的那一份(当时的原始报告,不用后来的重述)。
  拆股:报告里的股数是**报送日那天的口径**(拆股后报送的会按新口径重述),所以股数 × 报送日之后的拆股系数、
  价格 ÷ 当天之后的拆股系数,统一到今天的口径;拆股从「原始价 / 复权价」单日跳 > 20% 认。
  ADR:外国公司报的是普通股数,除以每份 ADR 对应的普通股数(`ADR_ORD_PER_ADS`,有生效日);换股比例没核实的不写。
  守卫:离中位数 100 倍以上的点当录入错误丢掉;单点错(离两边都 > 1.5 倍、两边彼此一致)丢那个点;
  相邻两点股数跳 50% 以上(并购、换股比例变了)⇒ 只用跳之后的段;跳之后只剩最新一个点 ⇒ 不写(口径待核)。
  周频(每周最后一个交易日),2015 起。
- 加密:不另存 —— `asset_mcap_daily`(CoinGecko Pro)已有。
- 贵金属:不存 —— 排名时用「价格 × 可投资存量」现算(`metal_mcap_usd`)。存量口径**待 Jazz 定**,
  这里给两档:`bars_coins_etfs`(私人投资:金条、金币、ETF)与 `bars_coins_etfs_cb`(再加央行)。
  黄金数字是世界黄金协会 2025 年底的地上存量分解(第三方转述,见 S-579);白银、铂金还没有可靠来源 ⇒ None(不可算)。

## 链上形式 → `world50_onchain_forms`

来源:CoinGecko Pro `/rwas/markets`(S-266 已在用的那一族;`asset_type` 是 CG 的封闭枚举 stock / etf / commodity,
市场数据在 `tokenized_market_data` 里)。发行方由 `/rwas/markets?issuer=<id>` 反查,一只资产可以有多家。
对到候选上的规则(`match_rwa`,纯函数,规则写进 `match_rule` 便于复查):
- 商品:名字里的 gold / silver / platinum。**只在 `asset_type = commodity` 里按名字对** —— 金矿公司的代币化股票名字里也有 Gold。
- ETF:只有追踪实物金属的 ETF(GLD、IAU、SLV、PPLT …)算金属的链上形式;其余 ETF 不是成分(方法 §2),记 `etf-not-a-member`。
- 股票:符号(或去掉发行方后缀 xStocks `x` / Ondo `on` 之后)等于候选代码;**1–2 个字母的代码还要名字对得上**
  (V、C、T、MA、GS …太容易撞)。本地上市、没有美国代码的公司按公司全名对,长名字先对(Bank of China ⊂ Agricultural Bank of China)。
- 对不上的也写进表(key 为空),方便查漏配。
**这只是「有没有链上形式、成交多少」;发行结构(追踪凭证还是 1:1 托管)、谁能买(地域限制)要另外核 —— 资格规则由 Jazz 定。**

## 一周一轮(`run_week`,由 `_world50_history_loop` 调)

复权日线(`tradfi_history.run_once`)→ 历史市值 → 链上形式。三段各自报结果;**任何一段没成,整轮就不是 ok**,
哪一段、为什么写在 reason 里 —— 不让一段静默地死在一个「ok」的循环里。
"""
from __future__ import annotations

import asyncio
import bisect
import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

WRITES_TABLES = ("world50_mcap_weekly", "world50_onchain_forms", "asset_mcap_daily", "world50_revenue")
WRITES_COLUMNS = {
    "world50_mcap_weekly": ("key", "d", "mcap_usd", "source"),
    "world50_revenue": ("key", "tag", "unit", "period_start", "period_end", "filed", "revenue", "accn"),
    "world50_onchain_forms": ("as_of", "token_id", "key", "symbol", "name", "category", "issuer", "match_rule",
                              "price_usd", "mcap_usd", "volume_24h_usd"),
}

START = "2015-01-01"
TROY_OZ_PER_TONNE = 32_150.7466
MCAP_MIN_SHARE_OK = 0.6       # 低于这个比例的公司取到市值,整段按故障报(和日线的 60/103 同一量级)

#: 世界黄金协会 2025 年底的地上黄金存量(吨)—— 第三方转述(EBC / WorldAtlas 引 WGC),官方表格待核。
GOLD_STOCK_T_2025 = {"total": 219_891, "jewellery": 97_645, "bars_coins_etfs": 50_978,
                     "central_banks": 38_666, "other": 32_602}
INVESTABLE_BASES = ("bars_coins_etfs", "bars_coins_etfs_cb")


def metal_mcap_usd(key: str, price_usd_per_oz: float, basis: str = "bars_coins_etfs") -> Optional[float]:
    """贵金属的可投资市值。没有可靠存量来源的金属返回 None(不可算,不是 0)。"""
    if basis not in INVESTABLE_BASES:
        raise ValueError(f"basis 只能是 {INVESTABLE_BASES}")
    if key != "XAUUSD" or not price_usd_per_oz or price_usd_per_oz <= 0:
        return None
    t = GOLD_STOCK_T_2025["bars_coins_etfs"] + (GOLD_STOCK_T_2025["central_banks"] if basis.endswith("_cb") else 0)
    return t * TROY_OZ_PER_TONNE * float(price_usd_per_oz)


# ── 历史市值 ────────────────────────────────────────────────────────────────

SPLIT_JUMP = 1.2              # 原始价 / 复权价 单日跳超过这个倍数 ⇒ 拆股
SHARE_JUMP = 1.5              # 相邻两点股数(今天口径)跳超过这个倍数 ⇒ 并购 / 换股比例变了,只用跳之后的段
OUTLIER_X = 100               # 离中位数这么多倍 ⇒ 录入错误(实测 BRK 有几期多乘了 100 万)
#: v2(10-15):v1 首跑里 MA / BRK-B / BABA 的行是错的,而拒写不会删掉旧行 —— 换 source 名,读者只认 v2,
#: v1 的行留着当记录(要清由 Jazz 定)。以后算法改到会改变已写的值,也照此升版本。
#: v3(10-15 晚):价格里的「拆股」要股数印证(分拆 / 特别分红不再当拆股)、合并类事件不截断、旧 CIK 补齐、
#: 本地上市公司按交易所申报的股数 × 本币收盘 × 汇率 —— 不再只是 SEC,名字去掉 sec_。
MCAP_SOURCE = "shares_x_close_v3"
#: 价格里的「拆股」(原始价 / 复权价跳 > 20%)也会来自分拆与特别分红 —— UTC 2020-04 分出 Carrier / Otis(×1.58)、
#: DELL 2021-11 派 VMware(×1.95)。那时股数不变,当成拆股就把之前的股数乘上去、再触发跳变截断(RTX 2020 前、DELL 2021 前整段丢了)。
#: 判据:事件前最后一次**报送**的股数 a、事件后第一个**期末**的股数 b(都已按 ADR 比例换算):
#: b / a 在 k 的 ±15% 内 ⇒ 拆股;在 1 的 ±15% 内 ⇒ 不是拆股(股数、价格两侧都不除);其余(同时有并购等)照旧当拆股。
SPLIT_CONFIRM_TOL = 1.15
SPIKE_NEIGHBORS = 1.1          # 一个点离两边都 > 1.5 倍、两边彼此在 1.1 倍内 ⇒ 单点错,丢这个点(不截断历史)
STALE_DAYS = 500              # 选中的口径最后一次报送早于最新价格这么多天 ⇒ 股数是旧的,不写(20-F 一年一报,400 天会误拒 BHP)
#: 四种口径,按优先级。封面股数(某天的实际股数)> 资产负债表期末股数 > 每季加权平均基本股数 > IFRS 年度加权平均股数
#: (用 IFRS 报的外国公司,如 Novo Nordisk 的 A + B 股合计只在这里)。
SEC_TAGS = {"dei": ("dei", "EntityCommonStockSharesOutstanding", False),
            "cso": ("us-gaap", "CommonStockSharesOutstanding", False),
            "wavg": ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", True),
            "ifrs_wavg": ("ifrs-full", "WeightedAverageShares", True)}
SOURCE_ORDER = ("dei", "cso", "wavg", "ifrs_wavg")
#: SEC 结构化数据里核实是录入错误的点 → 原文件封面上的数。{key: {期末: (正确股数, 出处)}}。
SEC_FIX: dict[str, dict[str, tuple[float, str]]] = {
    # 2026 年 20-F 封面写 18,580,374,278 股普通股,XBRL 标成 1,858,037,427(少一位)
    "BABA": {"2026-03-31": (18_580_374_278, "0001193125-26-231755")},
}
#: 换了申报主体(控股公司重组)的公司:旧 CIK 的历史接在前面。实测 2026 年 XOM 归到新的 ExxonMobil Holdings(CIK 2115436)。
#: GOOGL:2015-10 前是 Google Inc.(1288776,期末股数报到 2014-03、之后按类别报;一拆二后的总股数在那一点上);
#: DIS:2019-03 收购 Fox 时控股公司换成新 CIK,旧的 Walt Disney Co 是 1001039;
#: AVGO:Avago Technologies(1441634)→ 2016-02 Broadcom Ltd(1649338)→ 2018-04 Broadcom Inc(今天的 CIK)。
PREDECESSOR_CIKS: dict[str, list[int]] = {"XOM": [34088], "GOOGL": [1288776], "DIS": [1001039],
                                          "AVGO": [1441634, 1649338]}
#: 只有某一种口径能把旧主体与新主体接成一条的公司:不走「最新还在报」的自动选择。
#: AVGO:封面股数 Broadcom Ltd 只报了 2016 年两期,加权平均从 Avago 到今天一直在报;
#: SHEL:2022 年前 A / B 两类股,封面按类别报(接口里没有),IFRS 加权平均是两类合计。
SOURCE_OVERRIDE: dict[str, str] = {"AVGO": "wavg", "SHEL": "ifrs_wavg"}
#: 股数跳 > 1.5 倍、但前后两段都对的已知事件(按期末日落在事件两侧认):
#: "merger" = 换股合并,公司真的变大了,两段照写;"unify" = 双重上市合并成一家,之前的段乘以跳变倍数接成合并后的口径。
KNOWN_SHARE_EVENTS: dict[str, list[tuple[str, str, str]]] = {
    # 同一天 UTC 先分出 Carrier / Otis(价格跳 ×1.58)再与 Raytheon 合并(股数跳 ×1.76):两个倍数在 15% 以内,
    # 股数印证分不开 ⇒ 分拆写明,价格那一跳不当拆股。"spinoff" = 这一天前后 5 天内价格侧认出的拆股作废。
    "RTX": [("2020-04-03", "spinoff", "United Technologies 分出 Carrier 与 Otis"),
            ("2020-04-03", "merger", "United Technologies 与 Raytheon 换股合并")],
    # BHP Ltd + BHP Plc 双重上市 2022-01-31 统一:Plc 股 1:1 换 Ltd 股。之前 BHP 的 ADR 只对应 Ltd 那一半;
    # 乘上跳变倍数 = 按 Ltd 的价格算整个集团(Plc 在伦敦一般折价约一成,略高估,注明)。
    "BHP": [("2022-01-31", "unify", "BHP Ltd / BHP Plc 双重上市统一")],
}

#: 手工补的股数(Jazz 10-15「手工补」)—— 免费接口里取不到的:分股类申报的汇总数只在附注表或封面文字里(V / BRK-B),
#: 或 SEC 结构化接口对这家公司返回空(KO / ABT,原因未查;10-K 封面上有),或不在 SEC 申报(TCEHY,港交所月报表)。
#: 每行 = (截至日, 报送日 = 已知日, 股数, 出处 accession)。口径是 MANUAL_BASIS_DATE 那天的口径(之后若再拆股,照拆股系数换算)。
#: 一年一行:10-K 封面 / 附注。改动这张表 = 改了已写的值 ⇒ 记得把 PART_VERSIONS["mcap"] 加一。
MANUAL_BASIS_DATE = "2026-10-15"
MANUAL_SHARES: dict[str, dict[str, Any]] = {
    "BRK-B": {
        "what": "B 股当量 = A 股 × 1500 + B 股(10-K 封面「Number of shares outstanding」)",
        "rows": [(d, f, a * 1500 + b, acc) for d, f, a, b, acc in (
            ("2015-02-18", "2015-03-02", 825_522, 1_226_158_699, "0001193125-15-070966"),
            ("2016-02-17", "2016-02-29", 807_811, 1_253_479_359, "0001193125-16-483023"),
            ("2017-02-16", "2017-02-27", 774_680, 1_304_592_522, "0001193125-17-056969"),
            ("2018-02-13", "2018-02-26", 748_745, 1_344_332_039, "0001193125-18-057033"),
            ("2019-02-14", "2019-02-25", 725_807, 1_372_751_831, "0001193125-19-048926"),
            ("2020-02-13", "2020-02-24", 700_396, 1_385_994_959, "0001564590-20-005874"),
            ("2021-02-16", "2021-03-01", 640_586, 1_336_348_609, "0001564590-21-009611"),
            ("2022-02-14", "2022-02-28", 615_333, 1_291_212_661, "0001564590-22-007322"),
            ("2023-02-13", "2023-02-27", 590_835, 1_301_100_243, "0000950170-23-004451"),
            ("2024-02-12", "2024-02-26", 566_618, 1_310_805_008, "0000950170-24-019719"),
            ("2025-02-10", "2025-02-24", 546_189, 1_338_051_639, "0000950170-25-025210"),
            ("2026-01-31", "2026-03-02", 511_820, 1_389_605_139, "0001193125-26-083899"),
        )],
    },
    "V": {
        "what": "as-converted class A(A + B×换股比例 + C×4 + 欧洲优先股折算;10-K 股东权益附注,单位百万、四舍五入)",
        "rows": [(d, f, m * 1e6, acc) for d, f, m, acc in (
            # FY2014:2015 年 10-K 里按拆股后口径重列的分项现算 —— A 1,978 + B 245×1.6483 + C 22×4(分项是四舍五入的)
            ("2014-09-30", "2014-11-21", 2_470, "0001403161-15-000013"),
            ("2015-09-30", "2015-11-20", 2_434, "0001403161-15-000013"),
            ("2016-09-30", "2016-11-15", 2_422, "0001403161-16-000058"),
            ("2017-09-30", "2017-11-17", 2_350, "0001403161-17-000044"),
            ("2018-09-30", "2018-11-16", 2_291, "0001403161-19-000050"),   # 次年 10-K 的对比列
            ("2019-09-30", "2019-11-14", 2_237, "0001403161-19-000050"),
            ("2020-09-30", "2020-11-19", 2_197, "0001403161-21-000060"),   # 次年 10-K 的对比列
            ("2021-09-30", "2021-11-18", 2_161, "0001403161-21-000060"),
            ("2022-09-30", "2022-11-16", 2_103, "0001403161-23-000099"),   # 次年 10-K 的对比列
            ("2023-09-30", "2023-11-15", 2_047, "0001403161-23-000099"),
            ("2024-09-30", "2024-11-13", 1_983, "0001403161-25-000089"),   # 次年 10-K 的对比列
            ("2025-09-30", "2025-11-06", 1_930, "0001403161-25-000089"),
        )],
    },
    # 股数变化很慢(11 年 −1.5%),隔两三年取一份 10-K 封面足够
    "KO": {
        "what": "普通股(10-K 封面「number of shares outstanding of the Registrant's Common Stock」)",
        "rows": [
            ("2015-02-23", "2015-02-25", 4_366_243_616, "0000021344-15-000005"),
            ("2018-02-16", "2018-02-23", 4_265_906_533, "0000021344-18-000008"),
            ("2021-02-22", "2021-02-25", 4_309_311_676, "0000021344-21-000008"),
            ("2024-02-16", "2024-02-20", 4_312_456_168, "0000021344-24-000009"),
            ("2026-02-18", "2026-02-20", 4_300_723_069, "0001628280-26-010047"),
        ],
    },
    # 2017-01 并购 St. Jude 增发约 15% —— 那一年要有一行
    "ABT": {
        "what": "普通股(10-K 封面「Number of common shares outstanding」)",
        "rows": [
            ("2015-01-31", "2015-02-27", 1_508_977_828, "0001047469-15-001377"),
            ("2017-01-31", "2017-02-17", 1_727_997_596, "0001047469-17-000744"),
            ("2018-01-31", "2018-02-16", 1_746_333_892, "0001047469-18-000856"),
            ("2021-01-31", "2021-02-19", 1_771_529_358, "0001104659-21-025751"),
            ("2024-01-31", "2024-02-16", 1_735_184_289, "0001628280-24-005348"),
            ("2026-01-31", "2026-02-20", 1_737_682_887, "0001628280-26-010185"),
        ],
    },
    # 腾讯不在 SEC,在港交所申报(Jazz 10-15):每月「股份发行人的证券变动月报表」(FF301)的月末已发行股数;
    # 已知日 = 提交日。股数 11 年在 ±2% 内,取 6 份。TCEHY 一份 ADR = 1 股。出处是 hkexnews 上的文件路径。
    "TCEHY": {
        "what": "已发行普通股(港交所月报表 FF301「Balance at close of the month」)",
        "rows": [
            ("2014-12-31", "2015-01-07", 9_370_678_830, "hkex:/listedco/listconews/sehk/2015/0107/ltn20150107813.pdf"),
            ("2016-12-31", "2017-01-06", 9_477_083_480, "hkex:/listedco/listconews/sehk/2017/0106/ltn20170106878.pdf"),
            ("2019-12-31", "2020-01-07", 9_552_615_286, "hkex:/listedco/listconews/sehk/2020/0107/2020010701208.pdf"),
            ("2021-12-31", "2022-01-06", 9_608_378_469, "hkex:/listedco/listconews/sehk/2022/0106/2022010601615.pdf"),
            ("2024-05-31", "2024-06-06", 9_406_383_400, "hkex:/listedco/listconews/sehk/2024/0606/2024060600413.pdf"),
            ("2026-09-30", "2026-10-07", 9_092_605_595, "hkex:/listedco/listconews/sehk/2026/1007/2026100701204.pdf"),
        ],
    },
}

#: 外国 20-F 发行人在交 XBRL 之前(约 2018 年前)结构化接口里没有股数 —— 当时就公开了的 20-F 封面
#: 「Indicate the number of outstanding shares of each of the issuer's classes …」那一栏。按报告口径(普通股数,
#: 不除 ADR、不换算拆股),只接在 SEC 结构化数据之前;SEC 那边期末早于最后一行封面的(首份 XBRL 年报带的往年对比数)丢掉。
#: 口径要和接上的 SEC 口径一致:SHEL 是 A + B 两类合计;BHP / RIO 是 Ltd / plc 单边(美国挂牌的那一边,BHP 2022 统一时由
#: KNOWN_SHARE_EVENTS 接成集团口径;RIO 现在也是 plc 单边,低估集团约两成,注明)。每行 = (期末, 报送日, 股数, accession)。
SEC_PREFIX: dict[str, list[tuple[str, str, float, str]]] = {
    "SHEL": [("2014-12-31", "2015-03-12", 3_867_361_824 + 2_427_675_757, "0001193125-15-088212"),
             ("2015-12-31", "2016-03-10", 3_965_989_512 + 2_431_531_014, "0001193125-16-499117"),
             ("2016-12-31", "2017-03-09", 4_406_063_759 + 3_739_277_889, "0001564590-17-003822")],   # 2016-02 收购 BG
    "BHP": [("2014-06-30", "2014-09-25", 3_211_691_105, "0001193125-14-351924"),                      # BHP Billiton Limited
            ("2019-06-30", "2019-09-17", 2_945_851_394, "0001193125-19-245975")],                     # 2018-12 场外回购注销后
    "TSM": [("2014-12-31", "2015-04-13", 25_929_662_436, "0001193125-15-126836")],
    "NVS": [("2014-12-31", "2015-01-27", 2_398_626_257, "0001047469-15-000433"),
            ("2016-12-31", "2017-01-25", 2_374_059_013, "0001047469-17-000338")],
    "HSBC": [("2014-12-31", "2015-02-26", 19_217_874_260, "0001193125-15-065289"),
             ("2016-12-31", "2017-02-21", 20_191_586_214, "0001628280-17-001527")],
    "TTE": [("2014-12-31", "2015-03-26", 2_385_267_525, "0001193125-15-106292"),
            ("2016-12-31", "2017-03-17", 2_430_365_862, "0001193125-17-086269")],
    "SAP": [("2014-12-31", "2015-03-20", 1_228_504_232, "0001193125-15-099258")],
    "NVO": [("2014-12-31", "2015-02-05", 537_436_000 + 2_112_564_000, "0001171843-15-000625")],      # A + B 股
    "AZN": [("2014-12-31", "2015-03-10", 1_263_143_338, "0000950103-15-001933")],
    "RIO": [("2014-12-31", "2015-03-06", 1_425_377_388, "0001193125-15-079473")],                     # Rio Tinto plc
}

#: 不在 SEC 申报的公司:股本取**各自交易所 / 法定披露平台的原始文件**(Jazz 10-15:三星 → 韩国交易所,茅台 → 上交所)。
#: 和 SEC 一样按**当时报的口径**记(不换算),拆股 / 送股由价格侧认出、股数印证(confirm_splits)后统一到今天口径;
#: 已知日 = 文件公开日。价格是本币 ⇒ 市值 × 当周汇率(EODHD `USD{ccy}.FOREX`)。多类股按「哪几类相加」写在 what 里;
#: A + H 两地上市的按总股数 × 所用那条价格线(A / H 价差没有调,注明)。每行 = (期末, 公开日, 股数, 出处)。
#: 后续的行由 T-100(lane-a)按同一格式补,Seth 合并。改这张表 = 改已写的值 ⇒ PART_VERSIONS["mcap"] 加一。
EXCHANGE_SHARES: dict[str, dict[str, Any]] = {
    "1398.HK": {"ccy": "HKD", "what": "H + A 股合计(港交所月报表 FF301);价格线是 H 股",
                "rows": [("2014-12-31", "2015-01-06", 353_494_213_820, "hkex:/listedco/listconews/sehk/2015/0106/ltn20150106657.pdf"),
                         ("2016-12-31", "2017-01-06", 356_406_257_089, "hkex:/listedco/listconews/sehk/2017/0106/ltn20170106555.pdf"),
                         ("2026-09-30", "2026-09-30", 356_406_257_089, "hkex:/listedco/listconews/sehk/2026/0930/2026093000442.pdf")]},
    "601939.SHG": {"ccy": "CNY", "what": "H + A 股合计(FF301);价格线是 A 股",
                   "rows": [("2014-12-31", "2014-12-31", 250_010_977_486, "hkex:/listedco/listconews/sehk/2014/1231/ltn20141231455.pdf"),
                            ("2025-06-30", "2025-07-03", 261_600_381_459, "hkex:/listedco/listconews/sehk/2025/0703/2025070301475.pdf"),
                            ("2026-09-30", "2026-09-30", 261_600_381_459, "hkex:/listedco/listconews/sehk/2026/0930/2026093001192.pdf")]},
    "601288.SHG": {"ccy": "CNY", "what": "H + A 股合计(FF301);价格线是 A 股",
                   "rows": [("2014-12-31", "2015-01-06", 324_794_117_000, "hkex:/listedco/listconews/sehk/2015/0106/ltn20150106471.pdf"),
                            ("2018-07-31", "2018-08-01", 349_983_033_873, "hkex:/listedco/listconews/sehk/2018/0801/ltn201808011060.pdf"),
                            ("2026-09-30", "2026-09-30", 349_983_033_873, "hkex:/listedco/listconews/sehk/2026/0930/2026093001352.pdf")]},
    "601988.SHG": {"ccy": "CNY", "what": "H + A 股合计(FF301);价格线是 A 股",
                   "rows": [("2014-12-31", "2015-01-05", 288_731_148_000, "hkex:/listedco/listconews/sehk/2015/0105/ltn20150105769.pdf"),
                            ("2016-12-31", "2017-01-03", 294_387_791_241, "hkex:/listedco/listconews/sehk/2017/0103/ltn201701031200.pdf"),
                            ("2025-06-30", "2025-07-02", 322_212_411_814, "hkex:/listedco/listconews/sehk/2025/0702/2025070203248.pdf"),
                            ("2026-09-30", "2026-09-30", 322_212_411_814, "hkex:/listedco/listconews/sehk/2026/0930/2026093000500.pdf")]},
    "0857.HK": {"ccy": "HKD", "what": "H + A 股合计(FF301);价格线是 H 股",
                "rows": [("2014-12-31", "2015-01-04", 183_020_977_818, "hkex:/listedco/listconews/sehk/2015/0104/ltn20150104021.pdf"),
                         ("2026-09-30", "2026-10-05", 183_020_977_818, "hkex:/listedco/listconews/sehk/2026/1005/2026100500962.pdf")]},
    "0941.HK": {"ccy": "HKD", "what": "香港股 + 2022 年起的人民币股(上交所)合计(FF301);价格线是香港股",
                "rows": [("2014-12-31", "2015-01-07", 20_438_426_514, "hkex:/listedco/listconews/sehk/2015/0107/ltn20150107238.pdf"),
                         ("2022-02-28", "2022-03-01", 21_362_826_764, "hkex:/listedco/listconews/sehk/2022/0301/2022030103054.pdf"),
                         ("2026-09-30", "2026-10-07", 21_695_890_446, "hkex:/listedco/listconews/sehk/2026/1007/2026100700796.pdf")]},
    "601318.SHG": {"ccy": "CNY", "what": "H + A 股合计(FF301);价格线是 A 股。2015-07 每 10 股转增 10 股 —— 2014 那一行是转增前口径,价格侧认拆股",
                   "rows": [("2014-12-31", "2015-01-05", 8_892_169_892, "hkex:/listedco/listconews/sehk/2015/0105/ltn201501051505.pdf"),
                            ("2018-12-31", "2019-01-02", 18_280_241_410, "hkex:/listedco/listconews/sehk/2019/0102/ltn201901021361.pdf"),
                            ("2026-09-30", "2026-09-30", 18_107_641_995, "hkex:/listedco/listconews/sehk/2026/0930/2026093001040.pdf")]},
    "600519.SHG": {"ccy": "CNY", "what": "A 股总股本(上交所法定披露,巨潮存档;注销回购按公告)。2015-07 每 10 股送 1 股(10%,价格侧认不出,"
                                         "2015-07 → 2016-03 用送股前股数 × 送股后价格,低估约 9%,注明)",
                   "rows": [("2014-06-30", "2014-08-29", 1_141_998_000, "cninfo:finalpage/2014-08-29/1200185637.PDF"),
                            ("2015-12-31", "2016-03-24", 1_256_197_800, "cninfo:finalpage/2016-03-24/1202072288.PDF"),
                            ("2025-08-29", "2025-08-30", 1_252_270_215, "sse:600519 临2025-032(中国证券报 2025-08-30 A10)注销 3,927,585"),
                            ("2026-05-28", "2026-05-28", 1_250_081_601, "sse:600519 临2026-021 注销 2,188,614")]},
    "005930.KO": {"ccy": "KRW", "what": "普通股发行数(含库存股;优先股另一条线,不加)。公司 IR 上市现状表(原股在韩国交易所)。"
                                        "2018 前(拆股前、库存股分批注销)待 T-100 从 KRX / DART 补",
                  "rows": [("2018-05-04", "2018-05-04", 6_419_324_700, "samsung.com/sec/ir/stock-information/listing-info(2018-05-04 50:1 拆股后上市)"),
                           ("2018-12-04", "2018-12-04", 5_969_782_550, "samsung.com/sec/ir/stock-information/listing-info(库存股全部注销)"),
                           ("2025-02-20", "2025-02-20", 5_919_637_922, "samsung.com/sec/ir/stock-information/listing-info(2025-02-18 决议注销)"),
                           ("2026-04-02", "2026-04-02", 5_846_278_608, "samsung.com/sec/ir/stock-information/listing-info(注销 73,359,314 股)")]},
    "000660.KO": {"ccy": "KRW", "what": "普通股发行数(含库存股),与三星同口径。2026-02-09 注销库存股 15,300,000;2026-07 在纽交所发 ADS"
                                        "(1 份 = 1/10 股)新增 17,790,000 股。2026-08 起的回购(24,070,000 股、注销日未定)注销落地再加行",
                  "rows": [("2014-12-31", "2015-04-30", 728_002_365, "sec:SK Telecom 20-F FY2014 0001193125-15-158586"
                                                                    "(EDGAR 全文检索命中;FY2016–FY2018 同数)"),
                           ("2026-06-24", "2026-07-06", 712_702_365, "sec:SK hynix F-1/A 0001193125-26-295501"
                                                                    "「total issued common shares of 712,702,365 shares」"),
                           ("2026-07-14", "2026-07-14", 730_492_365, "sec:SK hynix 424B4 0001193125-26-299963"
                                                                    "(发行后流通 728,865,500 + 库存 1,626,865)")]},
    "2454.TW": {"ccy": "TWD", "what": "普通股发行数(台湾证交所);2014 年报「资本及股份」截至 2015-04-30。2015–2026 的变化(员工限制股)"
                                      "由 T-104 补近一行",
                "rows": [("2015-04-30", "2015-06-30", 1_571_577_147, "mediatek:Annual Reports/2014-English-Annual-Report.pdf p.43"
                                                                   "「Common Stock 1,571,577,147 428,422,853 2,000,000,000 Listed on TSE」")]},
    "ROG.SW": {"ccy": "CHF", "what": "无记名股 + 非投票权益证券(2026-03 换成参与证)合计;价格线是无记名股 RO.SW"
                                     "(world50.LOCAL_PRICE_CODE:ROG.SW 停在 2026-03-25);公司章程 §3–§4、IR 问答「股本自 2000 年的变化」",
               "rows": [("2011-03-01", "2011-03-01", 862_562_700, "roche:archiv-statuten-2011-en.pdf(160,000,000 + 702,562,700)"),
                        ("2019-03-05", "2019-03-05", 862_562_700, "roche:archiv_statuten_2019_en.pdf(160,000,000 + 702,562,700)"),
                        # 2021-11-26 临时股东会批准注销 53,309,000 无记名股(回购诺华持股);2022-02-03 入商业登记、02-08 刊登 SOGC
                        ("2022-02-03", "2022-02-08", 809_253_700, "roche.com/investors/faq_investors(106,691,000 + 702,562,700)"),
                        ("2026-03-11", "2026-03-11", 809_253_700, "roche.com/investors/faq_investors(参与证 702,562,700 + 无记名股 106,691,000)")]},
}

#: 每份 ADR(或在美国挂牌的那一单位)对应几股普通股,[(生效日, 比例)],旧 → 新。按**报送日**查表 ——
#: 生效日只要落在「最后一份旧比例的年报」与「第一份新比例的年报」之间就不影响结果;核不到确切日期的,用第一份新比例年报的报送日。
#: 美国挂牌单位的比例变化若被 EODHD 当成拆股处理(复权价无跳变),价格那一侧由拆股系数接住,股数这一侧由这张表接住。
#: 只收核过的;外国公司没在表里也不在 UNVERIFIED_ADR 里 ⇒ 按 1:1。
ADR_ORD_PER_ADS: dict[str, list[tuple[str, float]]] = {
    "TSM": [("1997-01-01", 5.0)],
    "BABA": [("2014-01-01", 1.0), ("2019-07-30", 8.0)],   # 2019-06 年报仍 1:1,2020-07 年报起 1 份 = 8 股
    "HSBC": [("1999-01-01", 5.0)],
    "BHP": [("2001-01-01", 2.0)],
    "SHEL": [("2005-01-01", 2.0)],
    # AZN:FY2014 20-F「each representing one Ordinary Share」;FY2015–FY2024「one half of an Ordinary Share」;
    # FY2025 20-F(2026-02-24)起普通股直接在纽交所挂牌
    "AZN": [("1993-01-01", 1.0), ("2016-03-08", 0.5), ("2026-02-24", 1.0)],
    # TM:FY2021 20-F(2021-06-24)「each … representing two shares」;FY2022 20-F(2022-06-23)起「ten shares」(2021 年一拆五,ADR 价不动)
    "TM": [("1999-01-01", 2.0), ("2022-06-23", 10.0)],
}
#: 换股比例我没核实 / 中途改过而我不确定生效日的 —— 不写,不猜。(TCEHY 1 份 = 1 股,股数手工从港交所补,不在这里)
UNVERIFIED_ADR: set[str] = {"BP", "VOD", "BUD", "UL", "BTI", "SAN"}   # T-101 补进池子的;比例由 T-105 从 20-F 封面核


def _closes(raw: Iterable[dict]) -> list[tuple[str, float, float]]:
    """EODHD 日线 → [(日期, 原始收盘, 复权收盘)],旧 → 新,只收两个都 > 0 的。"""
    out = []
    for x in raw or []:
        d, c = str(x.get("date") or "")[:10], _num(x.get("close"))
        a = _num(x.get("adjusted_close"))
        if len(d) == 10 and c and c > 0:
            out.append((d, c, a if a and a > 0 else c))
    return sorted(out)


def split_events(raw: Iterable[dict]) -> list[tuple[str, float]]:
    """[(拆股后第一个交易日, 比例 k)]。k > 1 = 一拆 k;k < 1 = 合股。纯函数。"""
    cl = _closes(raw)
    out = []
    for (d0, c0, a0), (d1, c1, a1) in zip(cl, cl[1:]):
        jump = (c0 / a0) / (c1 / a1)
        if jump > SPLIT_JUMP or jump < 1 / SPLIT_JUMP:
            out.append((d1, jump))
    return out


def _factor_after(x: str, splits: list[tuple[str, float]]) -> float:
    f = 1.0
    for d, k in splits:
        if d > x:
            f *= k
    return f


def sec_points(concept: Any, duration: bool) -> list[tuple[str, str, float]]:
    """SEC companyconcept → [(期末 / 封面日, 报送日, 股数)],按期末排序。纯函数。
    同一期多份报送取**最早**的(原始报告);`duration=True`(加权平均)只收一季(80–100 天)或一年(350–380 天),
    同一期末季度优先于年度。"""
    concepts = concept if isinstance(concept, list) else [concept]
    facts = []
    for c in concepts:
        sh = (((c or {}).get("units") or {}).get("shares")) or []
        facts.extend(sh if isinstance(sh, list) else [])
    best: dict[str, tuple[str, float, int]] = {}
    for f in facts:
        end, filed, v = str(f.get("end") or "")[:10], str(f.get("filed") or "")[:10], _num(f.get("val"))
        if len(end) != 10 or len(filed) != 10 or not v or v <= 0:
            continue
        rank = 0
        if duration:
            try:
                days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(str(f.get("start"))[:10], "%Y-%m-%d")).days
            except ValueError:
                continue
            if 80 <= days <= 100:
                rank = 0
            elif 350 <= days <= 380:
                rank = 1
            else:
                continue
        cur = best.get(end)
        if cur is None or (rank, filed) < (cur[2], cur[0]):
            best[end] = (filed, v, rank)
    return [(e, best[e][0], best[e][1]) for e in sorted(best)]


def _adr_ratio(key: str, d: str) -> float:
    r = 1.0
    for eff, x in ADR_ORD_PER_ADS.get(key, []):
        if eff <= d:
            r = x
    return r


def clean_shares(key: str, pts: list[tuple[str, str, float]], splits: list[tuple[str, float]],
                 basis_date: Optional[str] = None) -> tuple[list[tuple[str, float]], list[str], Optional[str]]:
    """[(已知日 = 报送日, 今天口径的股数)]、备注、拒绝原因。纯函数。
    今天口径 = 报告股数 ÷ 当时 ADR 比例 × 报送日(或 `basis_date`:手工表记录时的口径)之后的拆股系数。依次:去掉离中位数 100 倍以上的录入错误;
    去掉单点错(离两边都 > 1.5 倍、两边彼此在 1.1 倍内);相邻跳 50% 以上 ⇒ 只留最后一跳之后的段 ——
    **但如果留下的只有最新一个点,就不写**:没法分辨是公司真变了还是最新一期换了口径(实测 BABA 2026 年报)。"""
    notes: list[str] = []
    if not pts:
        return [], notes, None
    vals = sorted(v for _, _, v in pts)
    med = vals[len(vals) // 2]
    kept = [(e, f, v) for e, f, v in pts if med / OUTLIER_X <= v <= med * OUTLIER_X]
    if len(kept) < len(pts):
        notes.append(f"丢掉 {len(pts) - len(kept)} 个录入错误点")
    # (报送日, 期末, 今天口径股数);同一天报送的几期按期末排(首份 XBRL 年报会带前几年的对比数,最后一期才是当时最新)
    adj = sorted((f, e, v / _adr_ratio(key, f) * _factor_after(basis_date or f, splits)) for e, f, v in kept)
    i = 1
    while 0 < i < len(adj) - 1:
        a, b, c = adj[i - 1][2], adj[i][2], adj[i + 1][2]
        if max(b / a, a / b) > SHARE_JUMP and max(b / c, c / b) > SHARE_JUMP and max(a / c, c / a) <= SPIKE_NEIGHBORS:
            notes.append(f"{adj[i][0]} 单点错 ×{b / a:.2f},丢掉")
            adj.pop(i)
            continue
        i += 1
    start = 0
    for i in range(1, len(adj)):
        r = adj[i][2] / adj[i - 1][2]
        if not (r > SHARE_JUMP or r < 1 / SHARE_JUMP):
            continue
        ev = [x for x in KNOWN_SHARE_EVENTS.get(key, []) if x[1] in ("merger", "unify") and adj[i - 1][1] < x[0] <= adj[i][1]]
        if ev and ev[0][1] == "merger":
            notes.append(f"{adj[i][0]} 股数跳 ×{r:.2f} = {ev[0][2]},两段都留")
            continue
        if ev and ev[0][1] == "unify":
            adj[:i] = [(f, e, v * r) for f, e, v in adj[:i]]
            notes.append(f"{adj[i][0]} 股数跳 ×{r:.2f} = {ev[0][2]},之前的段 × {r:.2f} 接成合并后口径")
            continue
        start = i
        notes.append(f"{adj[i][0]} 股数跳 ×{r:.2f},只用之后的段")
    if start and len(adj) - start < 2:
        return [], notes, f"最新一期股数跳 ×{adj[start][2] / adj[start - 1][2]:.2f},口径待核,不写"
    return [(f, v) for f, _, v in adj[start:]], notes, None


def confirm_splits(key: str, pts: list[tuple[str, str, float]],
                   splits: list[tuple[str, float]]) -> tuple[list[tuple[str, float]], list[str]]:
    """价格里认出的拆股,拿股数印证(见 SPLIT_CONFIRM_TOL)。返回 (留下的拆股, 备注)。纯函数。"""
    keep, notes = [], []
    tol = math.log(SPLIT_CONFIRM_TOL)
    for d, k in splits:
        spun = [x for x in KNOWN_SHARE_EVENTS.get(key, []) if x[1] == "spinoff"
                and abs((datetime.strptime(x[0], "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days) <= 5]
        if spun:
            notes.append(f"{d} 价格跳 ×{k:.2f} = {spun[0][2]}(已知分拆),不当拆股")
            continue
        before = sorted((f, e, v / _adr_ratio(key, f)) for e, f, v in pts if f < d)    # 拆股当天报的口径说不准,不算「之前」
        after = sorted((e, f, v / _adr_ratio(key, f)) for e, f, v in pts if e > d)
        if before and after:
            r = after[0][2] / before[-1][2]
            if abs(math.log(r / k)) > tol and abs(math.log(r)) <= tol:
                notes.append(f"{d} 价格跳 ×{k:.2f} 但股数没变(×{r:.2f})= 分拆 / 特别分红,不当拆股")
                continue
        keep.append((d, k))
    return keep, notes


def _iso_week_last(cl: list[tuple[str, float, float]], start: str) -> list[tuple[str, float]]:
    """每个 ISO 周的最后一个交易日 [(日期, 原始收盘)]。"""
    last: dict[tuple[int, int], tuple[str, float]] = {}
    for d, c, _ in cl:
        if d < start:
            continue
        y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        last[(y, w)] = (d, c)
    return [last[k] for k in sorted(last)]


def choose_source(sources: dict[str, Any]) -> tuple[Optional[str], list[tuple[str, str, float]]]:
    """几种口径里选**最新还在报**的那一个:最后一次报送最晚者胜;相差 120 天内按 SOURCE_ORDER。
    实测 MA 的封面股数只到 2010(之后按类别报),只按优先级选会用 16 年前的股数。纯函数。"""
    cand = {}
    for name in SOURCE_ORDER:
        pts = sec_points(sources.get(name), duration=SEC_TAGS[name][2])
        if len(pts) >= 2:
            cand[name] = pts
    if not cand:
        return None, []
    latest = {n: max(f for _, f, _ in p) for n, p in cand.items()}
    top = max(latest.values())
    for name in SOURCE_ORDER:
        if name in cand and (datetime.strptime(top, "%Y-%m-%d") - datetime.strptime(latest[name], "%Y-%m-%d")).days <= 120:
            return name, cand[name]
    return None, []


def fx_series(raw: Iterable[dict]) -> list[tuple[str, float]]:
    """EODHD `USD{ccy}.FOREX` 日线 → [(日期, 每 1 美元多少本币)],旧 → 新。纯函数。"""
    return [(d, c) for d, c, _ in _closes(raw)]


def _usd_per_local(fx: list[tuple[str, float]], d: str) -> Optional[float]:
    """d 当天或之前最近一个汇率(7 天内),换成「每 1 本币多少美元」;没有就 None。"""
    i = bisect.bisect_right([x for x, _ in fx], d) - 1
    if i < 0 or (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(fx[i][0], "%Y-%m-%d")).days > 7:
        return None
    return 1.0 / fx[i][1]


def build_mcap(key: str, raw: list[dict], sources: dict[str, Any], start: str = START,
               fx: Optional[list[tuple[str, float]]] = None) -> dict[str, Any]:
    """一家公司的周频美元市值。美国上市:价格本来就是美元,sources = {dei / cso / wavg: SEC 概念(或多个 CIK 的列表)};
    交易所股本表里的公司(EXCHANGE_SHARES):本币价格 × `fx`(fx_series 的输出)换美元。
    返回 {rows, src, notes, why}:why 非空 = 不写。纯函数。"""
    if key in UNVERIFIED_ADR:
        return {"rows": [], "why": "ADR 换股比例未核实,不写"}
    cl = _closes(raw)
    if not cl:
        return {"rows": [], "why": "没有日线"}
    if key in EXCHANGE_SHARES and not fx:
        return {"rows": [], "why": f"没有 USD{EXCHANGE_SHARES[key]['ccy']} 汇率,本币市值换不成美元"}
    basis_date = None
    if key in MANUAL_SHARES:
        src, pts, basis_date = "manual", [(d, f, v) for d, f, v, _ in MANUAL_SHARES[key]["rows"]], MANUAL_BASIS_DATE
    elif key in EXCHANGE_SHARES:
        src, pts = "exchange", [(d, f, v) for d, f, v, _ in EXCHANGE_SHARES[key]["rows"]]
    elif key in SOURCE_OVERRIDE:
        src = SOURCE_OVERRIDE[key]
        pts = sec_points(sources.get(src), duration=SEC_TAGS[src][2])
    else:
        src, pts = choose_source(sources)
    if src not in ("manual", "exchange"):
        fix = SEC_FIX.get(key, {})
        pts = [(e, f, fix[e][0] if e in fix else v) for e, f, v in pts]
        if key in SEC_PREFIX and pts:
            first_f, last_pre_end = min(f for _, f, _ in pts), max(e for e, _, _, _ in SEC_PREFIX[key])
            pts = [(e, f, v) for e, f, v, _ in SEC_PREFIX[key] if f < first_f] + [p for p in pts if p[0] > last_pre_end]
    if not pts:
        return {"rows": [], "why": "SEC 里没有可用的股数(几种口径都没有)"}
    last_filed = max(f for _, f, _ in pts)
    if (datetime.strptime(cl[-1][0], "%Y-%m-%d") - datetime.strptime(last_filed, "%Y-%m-%d")).days > STALE_DAYS:
        return {"rows": [], "src": src, "why": f"股数停在 {last_filed}({src}),太旧,不写"}
    splits, split_notes = split_events(raw), []
    if src != "manual":       # 手工表已是今天口径,没有「报送时的口径」可对
        splits, split_notes = confirm_splits(key, pts, splits)
    shares, notes, refuse = clean_shares(key, pts, splits, basis_date)
    notes = split_notes + notes
    if refuse:
        return {"rows": [], "src": src, "notes": notes, "why": refuse}
    known_dates = [f for f, _ in shares]
    rows = []
    for d, c in _iso_week_last(cl, start):
        i = bisect.bisect_right(known_dates, d) - 1
        if i < 0:
            continue
        usd = 1.0 if fx is None else _usd_per_local(fx, d)
        if usd is None:
            continue
        rows.append({"key": key, "d": d, "mcap_usd": shares[i][1] * (c / _factor_after(d, splits)) * usd,
                     "source": MCAP_SOURCE})
    if not rows:
        return {"rows": [], "src": src, "notes": notes, "why": "没有一周同时有已知股数与价格"}
    return {"rows": rows, "src": src, "notes": notes, "latest_usd": rows[-1]["mcap_usd"], "why": None}


CRYPTO_COIN_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "BNB": "binancecoin", "SOL": "solana"}
CRYPTO_BACKFILL_END = "2020-01-05"   # asset_mcap_daily 原本从 2019-12-31 起(风格表头的 HISTORY_START)


async def backfill_crypto_mcap(start: str = START) -> dict[str, Any]:
    """加密候选 2015–2019 的市值(T-099 按时点排名要用;2017 年底 BTC 已进全球前 50)。
    **同一张表、同一个来源标签、同一个解析函数**(风格表头 `backfill_mcap` 那条路,规则 3b:一个量只有一条摄取路径)。
    已有 2019-12 之前的行就跳过。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_cg_market_chart_range
    from src.data.signals.hl_book_daily import _supabase_get
    from src.data.style.header import SOURCE, parse_market_chart

    def _ts(d: str) -> int:
        return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    out: dict[str, Any] = {}
    for sym, cid in CRYPTO_COIN_IDS.items():
        try:
            have = await _supabase_get(f"asset_mcap_daily?select=d&symbol=eq.{sym}&source=eq.{SOURCE}&d=lt.2019-12-01&limit=1")
            if have:
                out[sym] = "已有"
                continue
            raw = await get_cg_market_chart_range(cid, _ts(start), _ts(CRYPTO_BACKFILL_END), interval="daily")
            if not raw.get("available"):
                out[sym] = f"读不到:{str(raw.get('error') or raw.get('reason'))[:80]}"
                continue
            pts = parse_market_chart(raw.get("prices"), raw.get("market_caps"), raw.get("volumes"))
            rows = [{"symbol": sym, "coin_id": cid, "source": SOURCE, **p} for p in pts]
            for i in range(0, len(rows), 2000):
                res = await supabase_upsert_table("asset_mcap_daily", rows[i:i + 2000], on_conflict="symbol,d,source")
                if not res.ok:
                    raise RuntimeError(f"写入失败:{res.why[:80]}")
            out[sym] = len(rows)
        except Exception as e:  # noqa: BLE001 — 一个币补不上不连坐,原因带回去
            out[sym] = f"{type(e).__name__}: {str(e)[:80]}"
        await asyncio.sleep(0.2)
    return out


async def refresh_mcap(candidates: Optional[list] = None, start: str = START, concurrency: int = 4) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.market.tradfi_history import split_code
    from src.data.universe.world50 import CANDIDATES
    crypto = await backfill_crypto_mcap(start) if candidates is None else {}
    pool = candidates if candidates is not None else [c for c in CANDIDATES if c.cls == "equity"]
    todo = [c for c in pool if c.code.endswith(".US") or c.key in EXCHANGE_SHARES]
    skipped = [c.key for c in pool if c not in todo]
    sec_why = None
    try:
        ciks = await dl.get_sec_ticker_ciks()
    except Exception as e:  # noqa: BLE001 — 手工表里的公司不需要 SEC,照算;其余报 SEC 读不到
        ciks, sec_why = {}, f"SEC 代码表读不到:{type(e).__name__}: {str(e)[:160]}"
    sem = asyncio.Semaphore(concurrency)
    fx_cache: dict[str, Any] = {}

    async def fx_for(ccy: str):
        """一轮里每种货币只取一次;取不到记下原因,该币种的公司都报这个原因。"""
        if ccy not in fx_cache:
            try:
                fx_cache[ccy] = fx_series(await dl.get_eodhd_eod_range(f"USD{ccy}", "FOREX", start))
            except Exception as e:  # noqa: BLE001
                fx_cache[ccy] = f"USD{ccy} 汇率取不到:{type(e).__name__}: {str(e)[:100]}"
        return fx_cache[ccy]

    async def one(c):
        manual = c.key in MANUAL_SHARES or c.key in EXCHANGE_SHARES
        cik = ciks.get(c.key.upper())
        if cik is None and not manual:
            return {"key": c.key, "ok": False, "why": sec_why or "不在 SEC 申报公司表里"}
        async with sem:
            try:
                t, ex = split_code(c.code)
                sources: dict[str, list] = {}
                for k_cik in ([] if manual else PREDECESSOR_CIKS.get(c.key, []) + [cik]):
                    for name, (tax, tag, _) in SEC_TAGS.items():
                        got = await dl.get_sec_concept(k_cik, tax, tag)
                        await asyncio.sleep(0.15)   # SEC 限速 10 次 / 秒,4 路并发留足余量
                        if got:
                            sources.setdefault(name, []).append(got)
                raw = await dl.get_eodhd_eod_range(t, ex, start)
                fx = await fx_for(EXCHANGE_SHARES[c.key]["ccy"]) if c.key in EXCHANGE_SHARES else None
            except Exception as e:  # noqa: BLE001 — 一家取不到不连坐整轮,原因带回去
                return {"key": c.key, "ok": False, "why": f"{type(e).__name__}: {str(e)[:140]}"}
        if isinstance(fx, str):
            return {"key": c.key, "ok": False, "why": fx}
        b = build_mcap(c.key, raw, sources, start, fx=fx)
        if b["why"]:
            return {"key": c.key, "ok": False, "why": b["why"], "notes": b.get("notes")}
        w = await supabase_upsert_table("world50_mcap_weekly", b["rows"], on_conflict="key,d,source")
        return {"key": c.key, "ok": w.ok, "rows": len(b["rows"]), "first": b["rows"][0]["d"], "src": b["src"],
                "latest_bn": round(b["latest_usd"] / 1e9, 1), "notes": b["notes"],
                **({} if w.ok else {"why": w.why[:140]})}

    res = await asyncio.gather(*[one(c) for c in todo])
    ok = [r for r in res if r.get("ok")]
    enough = len(ok) >= max(1, math.ceil(MCAP_MIN_SHARE_OK * len(todo)))
    return {"ok": enough, "companies": len(todo), "companies_ok": len(ok), "not_sec_listed": skipped,
            "crypto_backfill": crypto,
            **({"why": sec_why} if sec_why else {}),
            "manual": sorted(k for k in MANUAL_SHARES if any(r.get("key") == k and r.get("ok") for r in res)),
            "exchange": sorted(k for k in EXCHANGE_SHARES if any(r.get("key") == k and r.get("ok") for r in res)),
            "rows": sum(int(r.get("rows") or 0) for r in ok),
            "earliest": min((r["first"] for r in ok), default=None),
            "src": {n: sorted(r["key"] for r in ok if r.get("src") == n) for n in ("cso", "wavg", "ifrs_wavg")},
            "latest_bn": {r["key"]: r["latest_bn"] for r in ok},
            "notes": {r["key"]: r["notes"] for r in res if r.get("notes")},
            "failed": [{"key": r["key"], "why": r.get("why")} for r in res if not r.get("ok")][:40]}


# ── 营收(增长分的输入,S-578 / S-581 预注册的 EW×(Mom+Growth) 臂)─────────────────────────────

#: 营收的几种标签:不同公司、不同年份用的不一样(2018 年 ASC 606 之后多数换成 RevenueFromContract…;银行用净利息后的营收;
#: IFRS 发行人用 ifrs-full:Revenue)。原样存每个标签、每种单位(外国公司报本币;增长是同币种同比,不需要换汇)。
REVENUE_TAGS = (("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "SalesRevenueNet"), ("us-gaap", "RevenuesNetOfInterestExpense"), ("ifrs-full", "Revenue"))


def revenue_rows(key: str, tag: str, concept: Any) -> list[dict]:
    """SEC companyconcept(可以是多个 CIK 的列表)→ world50_revenue 行。只收一季(80–100 天)与一年(350–380 天)的期间;
    同一期间多份报送取**最早**的(当时的原始报告),已知日 = 报送日。纯函数。"""
    concepts = concept if isinstance(concept, list) else [concept]
    best: dict[tuple, dict] = {}
    for c in concepts:
        for unit, facts in (((c or {}).get("units")) or {}).items():
            for f in facts if isinstance(facts, list) else []:
                st, en, fi = (str(f.get(k) or "")[:10] for k in ("start", "end", "filed"))
                v = _num(f.get("val"))
                if len(st) != 10 or len(en) != 10 or len(fi) != 10 or v is None or v <= 0:
                    continue
                try:
                    days = (datetime.strptime(en, "%Y-%m-%d") - datetime.strptime(st, "%Y-%m-%d")).days
                except ValueError:
                    continue
                if not (80 <= days <= 100 or 350 <= days <= 380):
                    continue
                k = (unit, st, en)
                if k not in best or fi < best[k]["filed"]:
                    best[k] = {"key": key, "tag": tag, "unit": unit, "period_start": st, "period_end": en,
                               "filed": fi, "revenue": v, "accn": str(f.get("accn") or "")}
    return [best[k] for k in sorted(best)]


async def refresh_revenue(candidates: Optional[list] = None, concurrency: int = 4) -> dict[str, Any]:
    """在 SEC 申报的候选(含旧 CIK)的营收原始事实 → world50_revenue。增长分在研究侧按时点现算(只用报送日之前的)。"""
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.universe.world50 import CANDIDATES
    pool = candidates if candidates is not None else [c for c in CANDIDATES if c.cls == "equity"]
    todo = [c for c in pool if c.code.endswith(".US")]
    try:
        ciks = await dl.get_sec_ticker_ciks()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"SEC 代码表读不到:{type(e).__name__}: {str(e)[:160]}"}
    sem = asyncio.Semaphore(concurrency)

    async def one(c):
        cik = ciks.get(c.key.upper())
        if cik is None:
            return {"key": c.key, "ok": False, "why": "不在 SEC 申报公司表里"}
        rows: list[dict] = []
        async with sem:
            try:
                for tax, tag in REVENUE_TAGS:
                    got = []
                    for k_cik in PREDECESSOR_CIKS.get(c.key, []) + [cik]:
                        g = await dl.get_sec_concept(k_cik, tax, tag)
                        await asyncio.sleep(0.15)
                        if g:
                            got.append(g)
                    if got:
                        rows += revenue_rows(c.key, f"{tax}:{tag}", got)
            except Exception as e:  # noqa: BLE001
                return {"key": c.key, "ok": False, "why": f"{type(e).__name__}: {str(e)[:140]}"}
        if not rows:
            return {"key": c.key, "ok": False, "why": "几种营收标签都没有"}
        for i in range(0, len(rows), 2000):
            w = await supabase_upsert_table("world50_revenue", rows[i:i + 2000],
                                            on_conflict="key,tag,unit,period_start,period_end")
            if not w.ok:
                return {"key": c.key, "ok": False, "why": f"写入失败:{w.why[:120]}"}
        return {"key": c.key, "ok": True, "rows": len(rows), "first": min(r["period_end"] for r in rows)}

    res = await asyncio.gather(*[one(c) for c in todo])
    ok = [r for r in res if r.get("ok")]
    return {"ok": len(ok) >= max(1, math.ceil(MCAP_MIN_SHARE_OK * len(todo))), "companies": len(todo),
            "companies_ok": len(ok), "rows": sum(r["rows"] for r in ok),
            "earliest": min((r["first"] for r in ok), default=None),
            "failed": [{"key": r["key"], "why": r.get("why")} for r in res if not r.get("ok")][:40]}


# ── 链上形式 ────────────────────────────────────────────────────────────────

METAL_WORDS = (("gold", "XAUUSD"), ("silver", "XAGUSD"), ("platinum", "XPTUSD"))
METAL_ETFS = {"GLD": "XAUUSD", "IAU": "XAUUSD", "SGOL": "XAUUSD", "GLDM": "XAUUSD", "AAAU": "XAUUSD", "PHYS": "XAUUSD",
              "SLV": "XAGUSD", "SIVR": "XAGUSD", "PSLV": "XAGUSD", "PPLT": "XPTUSD"}
ISSUER_SUFFIXES = ("ON", "X")          # Ondo: NVDAon;xStocks: NVDAx


def _norm(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def _plain(s: str) -> str:
    """小写、去重音(Nestlé → nestle,L'Oréal → l'oreal)。"""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _bases(sym: str) -> list[str]:
    """符号本身在前,再是去掉发行方后缀的版本。"""
    out = [sym]
    for suf in ISSUER_SUFFIXES:
        if sym.endswith(suf) and len(sym) > len(suf):
            out.append(sym[: -len(suf)])
    return out


def _first_word(name: str) -> str:
    w = re.split(r"[\s&\-,.]+", _plain(name).strip())
    return w[0] if w else ""


def match_rwa(symbol: str, name: str, asset_type: str, candidates: Iterable[Any]) -> tuple[Optional[str], str]:
    """一个代币化 RWA → (候选 key 或 None, 规则)。纯函数。"""
    sym, at, lname = _norm(symbol), (asset_type or "").strip().lower(), _plain(name)
    if at == "commodity":
        for w, k in METAL_WORDS:
            if w in lname:
                return k, f"commodity:{w}"
        return None, "commodity-not-a-candidate"
    if at == "etf":
        for b in _bases(sym):
            if b in METAL_ETFS:
                return METAL_ETFS[b], f"metal-etf:{b}"
        return None, "etf-not-a-member"
    cands = [c for c in candidates if c.cls == "equity"]
    by_ticker = {_norm(c.key): c for c in cands if "." not in c.key}
    for i, b in enumerate(_bases(sym)):
        c = by_ticker.get(b)
        if c is None:
            continue
        if len(b) <= 2 and _first_word(c.name) not in lname:
            continue                     # 短代码必须名字也对得上
        return c.key, ("ticker" if i == 0 else f"ticker-strip:{b}")
    for c in sorted((c for c in cands if "." in c.key), key=lambda c: -len(c.name)):
        if len(c.name) >= 4 and _plain(c.name) in lname:
            return c.key, f"name:{c.name}"
    return None, "unmatched"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def form_rows(raw: Iterable[dict], issuers: dict[str, set[str]], candidates: Iterable[Any], as_of: str) -> list[dict]:
    """`/rwas/markets` 的行 → world50_onchain_forms 行。市场数据在 `tokenized_market_data` 里(S-266);
    **没测的是 None,不是 0**。纯函数。"""
    cands = list(candidates)
    out, seen = [], set()
    for r in raw or []:
        rid = str(r.get("id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        tmd = r.get("tokenized_market_data") if isinstance(r.get("tokenized_market_data"), dict) else {}
        at = str(r.get("asset_type") or "").strip().lower()
        key, rule = match_rwa(r.get("symbol") or "", r.get("name") or "", at, cands)
        out.append({"as_of": as_of, "token_id": rid, "key": key, "symbol": r.get("symbol"), "name": r.get("name"),
                    "category": f"rwa:{at or 'unknown'}", "issuer": "|".join(sorted(issuers.get(rid, ()))) or None,
                    "match_rule": rule,
                    "price_usd": _num(tmd.get("current_price", r.get("current_price"))),
                    "mcap_usd": _num(tmd.get("market_cap")), "volume_24h_usd": _num(tmd.get("total_volume"))})
    return out


async def discover_onchain_forms(as_of: Optional[str] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.universe.world50 import CANDIDATES
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        raw = await dl.get_cg_rwa_markets()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"/rwas/markets 读不到:{type(e).__name__}: {str(e)[:160]}"}
    issuers: dict[str, set[str]] = {}
    issuer_failed = []
    try:
        issuer_list = await dl.get_cg_rwa_issuers()
    except Exception as e:  # noqa: BLE001 — 发行方是附加信息,读不到照写,只是 issuer 为空并报出来
        issuer_list, issuer_failed = [], [f"issuers/list: {type(e).__name__}: {str(e)[:100]}"]
    for it in issuer_list:
        try:
            for r in await dl.get_cg_rwa_markets(issuer=it["id"]):
                if r.get("id"):
                    issuers.setdefault(str(r["id"]), set()).add(str(it["id"]))
        except Exception as e:  # noqa: BLE001
            issuer_failed.append(f"{it['id']}: {type(e).__name__}")
    rows = form_rows(raw, issuers, CANDIDATES, as_of)
    if not rows:
        return {"ok": False, "why": f"/rwas/markets 返回 {len(raw)} 条,0 条有 id —— 形状变了?"}
    res = await supabase_upsert_table("world50_onchain_forms", rows, on_conflict="as_of,token_id")
    matched = [r for r in rows if r["key"]]
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["category"]] = by_type.get(r["category"], 0) + 1
    return {"ok": res.ok, "tokens": len(rows), "by_type": by_type, "matched": len(matched),
            "candidates_with_form": len({r["key"] for r in matched}),
            "issuers": len(issuer_list), "with_issuer": sum(1 for r in rows if r["issuer"]),
            "issuer_failed": issuer_failed[:10], **({} if res.ok else {"why": res.why[:160]})}


# ── 一周一轮 ────────────────────────────────────────────────────────────────

RERUN_AFTER_DAYS = 6
LOOP_NAME = "_world50_history_loop"
#: 某一段的算法改了就把它的版本加一:旧版本跑成的不算「已成」,下次部署会重跑这一段(没写版本的旧记录算 1)。
PART_VERSIONS = {"prices": 3, "mcap": 11, "onchain_forms": 1, "revenue": 1, "book": 1}


async def _recent_ok_parts(now: Optional[datetime] = None) -> set[str]:
    """6 天内已经真跑成了的段。每次部署都会重启循环 —— 不拦的话,一天几次部署就是一天几次整段重写 29 万行日线。
    **只认真跑成的,不认「跳过」**:否则跳过会一轮轮续期,永远不再真跑。读不到 ⇒ 空集(全跑)。"""
    from src.data.signals.hl_book_daily import _supabase_get
    now = now or datetime.now(timezone.utc)
    try:
        rows = await _supabase_get(f"loop_attempt?select=at,detail&loop_name=eq.{LOOP_NAME}&order=at.desc&limit=20")
    except Exception:  # noqa: BLE001
        return set()
    done: set[str] = set()
    for r in rows or []:
        try:
            at = datetime.fromisoformat(str(r.get("at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - at).total_seconds() > RERUN_AFTER_DAYS * 86400:
            break
        for name, p in (r.get("detail") or {}).items():
            if (isinstance(p, dict) and p.get("ok") and not p.get("skipped")
                    and p.get("v", 1) == PART_VERSIONS.get(name)):
                done.add(name)
    return done


def _brief(name: str, r: dict) -> dict:
    keep = {"prices": ("symbols", "symbols_ok", "written", "elapsed_s"),
            "mcap": ("companies", "companies_ok", "rows", "earliest", "src", "manual", "exchange", "crypto_backfill", "not_sec_listed",
                     "notes"),
            "onchain_forms": ("tokens", "by_type", "matched", "candidates_with_form", "with_issuer"),
            "revenue": ("companies", "companies_ok", "rows", "earliest"),
            "book": ("waiting", "preview", "holdings_written", "nav_written", "last", "notes")}[name]
    out = {"ok": bool(r.get("ok")), "v": PART_VERSIONS[name], **{k: r.get(k) for k in keep if k in r}}
    if r.get("skipped"):
        out["skipped"] = r["skipped"]
    fails = r.get("failed") or r.get("issuer_failed")
    if fails:
        out["failed"] = fails[:10]
    if r.get("why") or (not r.get("ok") and r.get("reason")):
        out["why"] = str(r.get("why") or r.get("reason"))[:200]
    return out


def _say(name: str, r: dict) -> str:
    label = {"prices": "日线", "mcap": "市值", "onchain_forms": "链上形式", "revenue": "营收", "book": "前向账本"}[name]
    if r.get("skipped"):
        return label + " 跳过(6 天内已成)"
    if not r.get("ok") and r.get("why") and not any(k in r for k in ("symbols_ok", "companies_ok", "tokens")):
        return f"{label} 没跑起来:{str(r['why'])[:80]}"
    if name == "prices":
        return f"日线 {r.get('symbols_ok')}/{r.get('symbols')}"
    if name in ("mcap", "revenue"):
        return f"{label} {r.get('companies_ok')}/{r.get('companies')}"
    if name == "book":
        if r.get("waiting"):
            pv = r.get("preview") or {}
            return f"前向账本 {r['waiting']}(预演 {pv.get('as_of')}:{pv.get('members')} 个成分)"
        return f"前向账本 新调仓行 {r.get('holdings_written', 0)} · 新净值行 {r.get('nav_written', 0)}"
    return f"链上形式 {r.get('tokens')} 条、对上 {r.get('candidates_with_form')} 个候选"


async def run_week(force: bool = False) -> dict[str, Any]:
    from src.data.market.tradfi_history import run_once
    from src.data.universe.world50_book import run_book
    steps = (("prices", run_once), ("mcap", refresh_mcap), ("onchain_forms", discover_onchain_forms),
             ("revenue", refresh_revenue), ("book", run_book))
    done = set() if force else await _recent_ok_parts()
    parts: dict[str, dict] = {}
    for name, fn in steps:
        if name in done:
            parts[name] = {"ok": True, "skipped": f"{RERUN_AFTER_DAYS} 天内已成"}
            continue
        try:
            parts[name] = await fn()
        except Exception as e:  # noqa: BLE001 — 一段炸了,后面的照跑,炸的原因带回去
            parts[name] = {"ok": False, "why": f"{type(e).__name__}: {str(e)[:160]}"}
    bad = [n for n, r in parts.items() if not r.get("ok")]
    reason = " · ".join(_say(n, r) for n, r in parts.items())
    if bad:
        reason = "没成的段:" + "、".join(bad) + " —— " + reason
    return {"ok": not bad, "refused": bool(parts["prices"].get("refused")), "reason": reason,
            "parts": {n: _brief(n, r) for n, r in parts.items()}}
