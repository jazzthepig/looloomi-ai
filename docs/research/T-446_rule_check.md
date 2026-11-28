# T-446 复核:S-931 的设计 —— 只对规则与算式(不重算)

**范围声明**:本文件只做「规则 / 算式 / 口径」对照。**没有重跑 S-931、没有改脚本、没有评价结果、没有登记情景**
(卡 T-446 验收 ②)。凡涉及「数」的,一律引用台账 S-931 结果段已写下的数,或直接读生产代码与库里序列。

## 复核对象与版本锚

| 项 | 值 |
|---|---|
| 脚本 | `docs/research/s931_x1v_zero_veto.py` |
| 复核时该文件在 origin/main 里的状态 | **不存在**(S-931 的提交还没落地);复核用的是 Seth 工作区里那份未入库的文件 |
| 复核版本的指纹 | sha256 `906c7181fb6101317c409689651bf9b4f64c20f996a1b95a99c08345c9bac9de`,12,939 字节,263 行 |
| 预注册 | 台账 `REFUTATION_LEDGER.md` 第 36563–36584 行(S-931 预注册);结果段 36587–36604 行 |
| 现行规则 | `docs/RULEBOOK.md`(82 行,origin/main);`src/data/evaluation/house_rules.py`(36 行) |
| 生产代码 | `src/data/universe/forward_books.py`、`src/data/universe/state_book.py`、`src/data/signals/tom.py`、`src/data/execution/executor.py`、`src/data/evaluation/setup_watch.py` |
| 上下游研究脚本 | `docs/research/s928_bear_playbook.py`(⓪ 与崩塌/上涨/水下)、`docs/research/s929_t370_short.py`(票) |

> ⚠️ 脚本没进 origin/main 这件事本身要记一笔:卡上写「脚本以 origin/main 为准」,但复核时 origin/main 上没有这个文件
> (`git ls-tree -r origin/main | grep s931` 为空)。下面所有行号指向的是上面那个 sha256 的版本;
> 落地版若与此不同,本复核的行号需重核。

---

## (a) BASE 是不是生产 `CORE_X1V` 的原样调用 —— △ **规则逐字一致,输入不是生产那一版**

**调用本身 ✓ 一字不差**:

- 脚本 55–56 行:`def x1v(core): return trade_path(core, "rally", 0.0, "l20", True)`
- 生产臂定义 `src/data/universe/forward_books.py:43`:`"CORE_X1V": ("CORE", "rally", 0.0, "l20", True)`
- 生产三个调用点用的都是同一组参数、没有第二份写法:
  - `forward_books.py:340` 解包 `key, bear, size, exit_mode, vol = TOM_ARMS["CORE_X1V"]` → `:345` `trade_returns(c, trade_path(c, bear, size, exit_mode, vol), fund.get(key))`
  - `state_book.py:300–301` 同样解包同一常量
  - `executor.py:49` `g = trade_path(close, "rally", 0.0, exit_mode="l20", vol=True)`(现货目标敞口,同一组参数)
- 脚本 166 行 `trade_returns(core, g0)` = 生产同一函数、同一入口,没有重写、没有近似实现。

**但两处输入与生产不是同一条(预注册都写了,`HOUSE_RULES` 没写 —— 见 (e))**:

1. **资金费**:生产 `forward_books.py:345` 传 `fund.get("CORE")`,而 `:225` `fund["CORE"] = fund.get("BTC")`(币安永续实测资金费按天求和 × 365,`:210` 注明);脚本 166 行不传资金费 ⇒ 走 `tom.py:131` 的默认 `0.10`(年化 10%)。
   预注册 36571 行原文:「收益 = `trade_returns(core, g)`(多于 1 倍的部分按**年化 10%** 付资金费,|Δg| × 10 bp)」
   ⇒ **脚本与预注册一致,与生产的 P&L 路径不一致**。
2. **① 的 NAV 序列**:生产 tom_trader 的核是 `multiplier_daily.core_u_replay`(`forward_books.py:209/214`、`state_book.py:85`「X1V 的核」);脚本与预注册 36570 行用的是 `core_variants_daily.cap_pit24`。
   两条序列**不是同一条**(实测,只读库):

   | 序列 | 2023-01-03 | 2026-11-19 | 区间涨幅 |
   |---|---|---|---|
   | `core_variants_daily.cap_pit24` | 4.24901 | 9.78974135 | **+130.4%** |
   | `multiplier_daily.core_u_replay` | 1.00026418 | 2.75498415 | **+175.4%** |

   同一段窗口差 ~45pp。`cap_pit24` 是 RULEBOOK 里 ① 的「历史锚」(S-700 按时点前 24 大、含死币),生产臂用的是 ① 的回放臂 —— 两者构造规则不同。

**结论**:「参数原样调用」✓;「BASE = 生产那一行的 P&L」✗(规则同、输入两处不同)。要说「在生产 X1V 之上加两层」,BASE 得换成 `core_u_replay` + 实测资金费;现在的 BASE 是「同一条规则 × RULEBOOK 的 ① 历史锚 × 固定 10% 资金费」。

---

## (b) 否决的时点 —— ✓ **没有错一天**

- 生产语义(`tom.py:74` 文档 + `:129`):`g[d]` 是 **d 收盘定下、作用于 d+1**;`trade_returns` 里 `gp = g.reindex(s.index).shift(1)`,收益 `r[d] = g[d−1] × px[d]`。
- 脚本 59–67 行:

  ```
  def veto(g, defend):
      """g[d] 作用于 d+1;d+1 在 ⓪ 防守 ⇒ 清零。"""
      out = g.copy(); idx = list(g.index)
      for i, ts in enumerate(idx[:-1]):
          nxt = idx[i + 1].date()
          if defend.get(nxt):
              out.iloc[i] = 0.0
  ```

  ⇒ `g_V1[d] = 0 if defend[d+1] else g[d]`,与预注册 36572 行的算式**逐字一致**。
- 落到收益上(脚本 172–176):`g1 = veto(g0, defend_all)` → `r1 = trade_returns(core, g1)` ⇒ `r1[d] = g1[d−1] × px[d]`,而 `g1[d−1] = 0 ⇔ defend[d]` ⇒ **防守日当天敞口为 0**,即预注册说的「否决与它作用于同一天」✓。
- ⓪ 的日/周边界:`s928_bear_playbook.py:81–88` `daily_defend` 定义「第 t 天 = t 之前最近一个周日(**不含 t 当天**)的判定」⇒ 防守从周一 00:00 起、当天周日的判定当天不生效。与预注册 36572「defend[t] = t 之前最近一个周日 D1 的判定」**一致** ✓。
- 尾部边界:`veto` 只走到 `idx[:-1]`,最后一天没有次日、不清零 ✓(窗口末日,无影响)。

**一处不对称但不影响任何比较**:账户循环 `for i in range(1, len(days))`(脚本 80 行)⇒ **首日 `days[0]` 的收益被跳过**。BASE / V1 / V2 三者共用同一个循环与同一份 `base_ret`,「持有 ①」又以 `days[0]` 为基期重算(脚本 183)⇒ 三条臂同时少了同一天的收益,比较不受影响。

**一处边界条件(在本窗口内不会触发,但写法上脆)**:⓪ 退出时的全平检查写作 `if d in weekly and not weekly[d]["defend"]`(脚本 104 行),`weekly` 的键是**周日日期**,只有该周日也落在账户的 `days` 里才检查得到;漏掉一周 ⇒ 那一周的全平被跳过,票一直挂到下一个周日或 28 天到期。
实测 `cap_pit24` 是**日历日齐全**的(2020-02-01 → 2026-11-19 共 2,484 天,缺 0 天;355 个周日全在)⇒ 只要私有导出的 `px`(BTC/ETH 日线)也是日历日齐全,`days` 就含每个周日 ⇒ 不会跳过。(私有数据 `research_data/s931_data.json` 不在仓库侧,这一条只能核到这里。)

---

## (c) c1 – c5 的实现 vs 预注册算式 —— ✓ **五条逐条对得上**(两处小数级差别列在末尾)

预注册 36582 行原文:
「(c1) 留出段 LUW_V2 < LUW_BASE,且发现段 LUW_V2 ≤ LUW_BASE;(c2) 每一段可评的崩塌 loss_V2 ≥ loss_BASE(不比生产更差),且各段削减的平均 > 0;(c3) 每一段上涨 capture_V2 ≥ capture_BASE − 0.10;(c4) 平移分位 ≥ 0.90;(c5) 票两段的均值 > 0、盈亏比 ≥ 2。」

| 判据 | 脚本行号 | 实现 | 对照 |
|---|---|---|---|
| 段切分 | 49 `START, SPLIT = 2020-02-01, 2023-01-01`;131 `m = [d < SPLIT]` | 发现段 = d < 2023-01-01、留出段 = d ≥ | 预注册 36575「发现段 [2020-02-01, 2022-12-31],留出段 [2023-01-01, 2026-11-19]」✓ 同值(与 `s928:28-29` 也同值) |
| LUW | 132 `B.underwater(days, nav, m)` → `s928:190-202` | 段内「距上一次段内新高的天数」的最大值,含段末未回去的一段;段内以自身新高为基准 ⇒ 等价于「每段净值从段首重新起算」 | 预注册 36576 逐字一致 ✓ |
| c1 | 189–190 `V2.hold.LUW < BASE.hold.LUW and V2.disc.LUW <= BASE.disc.LUW` | 留出段严格小于、发现段小于等于 | 预注册 (c1) ✓ 逐字一致 |
| c2 | 192–193 `all(c["V2"] >= c["BASE"] for c in ev)`;`cuts = [1 - c["V2"]/c["BASE"] for c in ev if c["BASE"] < 0]`;`np.mean(cuts) > 0` | 崩塌段取自 `s928:205-227`(① 相邻两次新高之间的最低点、峰谷 ≥ 30%);`c[k] = NAV(谷)/NAV(峰) − 1` 就是有符号的 loss ⇒ `1 − cV/cB` 与预注册的 `1 − loss_V/loss_BASE` 同式 | 预注册 36577 + (c2) ✓ 逐字一致 |
| 「可评」 | 140 `evaluable = p >= first_ready`;184 `first_ready = min(周中 v["ready"] 的周日)` | 峰早于 ⓪ 第一次能判的周日 ⇒ 不可评 | 预注册 36577「峰早于 ⓪ 第一次能判的周日 ⇒ 标「不可评」」✓ 一致 |
| 上涨段 | 144–149;`s928:222-227` | 谷 → 下一崩塌的峰(末段到窗口末)、涨幅 ≥ 80%;`capture = ln(NAV_x(峰)/NAV_x(谷)) ÷ ln(①(峰)/①(谷))` | 预注册 36578 ✓ 逐字一致 |
| c3 | 194 `all(r["V2"] >= r["BASE"] - 0.10 for r in rt)` | 每一段上涨(c3 不设「不可评」过滤,预注册也没要求) | 预注册 (c3) ✓ 逐字一致 |
| c4 平移零分布 | 208–217:`rng = default_rng(931)`;`o = int(rng.integers(8, len(suns) - 8))`;`np.roll(flags, o)`;500 次;`pct = (null > 实测 LUW).mean()` | 周度 ⓪ 序列循环平移 o 周,o ∈ [8, 周数 − 8)、500 次、种子 931,分位 = 零分布里 LUW 大于实测的比例 | 预注册 36579 逐字一致 ✓(平移的序列取「可判周」;前 9 个未就绪周日 defend 恒 False,丢掉不改变结果) |
| c4 判定 | 195 `c4 = pct >= 0.90` | — | 预注册 (c4) ✓ |
| c5 | 196 `all(tk[s].get("n") and tk[s]["mean_pct"] > 0 and (tk[s]["payoff"] or 0) >= 2 for s in ("disc","hold"))`;207 `tk = P.split(...)` → `s929:142-151` | `mean_pct` = 占名义 % 的均值;`payoff` = 赢的票均值 ÷ 亏的票均值绝对值;段按 `entry_d < 2023-01-01` 切(`s929:154-155`) | 预注册 36580「每张占名义 % = (进场 − 出场)/进场 + 期间资金费合计 − 2 × 10 bp;盈亏比 = 赚的票均值 ÷ 亏的票均值的绝对值」+ (c5) ✓ 逐字一致 |

**两处小数级别的差别(不改变判定方向,但原文与实现不同,列出来)**:

1. **未平票的成本口径**。预注册 36580:「… − **2 × 10 bp**」;脚本 126 行:
   `t["pct"] = (t["entry"] - t["exit"]) / t["entry"] + t["fund"] - (2 if t["why"] != "open" else 1) * COST`
   ⇒ 窗口末还没平的票只扣 **1 × 10 bp**(进场的已扣,出场的还没发生)。台账结果段写「今天开着 BTC(11-12)、ETH(11-13)两张」⇒ 这两张正落在这个口径上,留出段的均值比预注册字面式高约 10 bp/张。
2. **崩塌削减的可用性**。预注册字面式 `1 − loss_V/loss_BASE` 在 `loss_BASE ≥ 0` 时无意义;脚本 192 行用 `if c["BASE"] < 0` 过滤掉 BASE 没亏的崩塌段(只从「削减」里剔,不从 c2 的第一条「不比生产更差」里剔)。台账结果段「削减平均 20.9%」与 4 段可评崩塌(其中两段削减 = 0)对得上 ⇒ 过滤的是「有定义的削减」,不是把不利的段藏掉。

---

## (d) 票是不是 T-370 v1 原样 —— ✓ **`house_rules` 的值一个都没改写;管理动作与 S-929 A 组逐条同形**

**house_rules 的值没有被改写**:脚本 24 行 `from src.data.evaluation.house_rules import T370`,50 行 `NOTIONAL = T370["tiers"][1] / 2`,91 行 `T370["horizon_d"]` —— 全是**只读**;脚本里没有任何一处对 `T370` 赋值/改键(grep `T370` 只有 5 处命中:注释 5 行、import 24、uses 43、50、91)。触发那条更是直接调生产:`25 行 from src.data.evaluation.setup_watch import trigger_1`,115 行 `hit = trigger_1(bars, d, B.asof(d200, d, 3), B.asof(stable, d, 3), P.funding7(fund[sym], d))`
⇒ 这正是 T-445 复核 S-929 时指出「触发被重写」后、S-931 改掉的地方(台账 36604 行)。

| T-370 v1 规则(RULEBOOK 29–38 行) | 脚本实现 | 行号 |
|---|---|---|
| 触发:收盘 < 此前 20 根日线最低价(不含当天);线下 + 稳定币抽;7 日资金费 > 0 | 生产 `setup_watch.trigger_1`(`setup_watch.py:44-56`,其 29 行直接取 `T370["stop_above"] / ["stop_cap"]`) | 115 |
| 认错:被破那一档 × 1.01,且离进场 ≤ 8% | `trigger_1` 返回 `stop = min(lo20×1.01, entry×1.08)` | `setup_watch.py:56` |
| 进场 = D 收盘 | `"entry": hit["entry"]`(trigger_1 里 `entry = close(D)`) | 120 |
| 拿满 28 天 | `(d - t["entry_d"]).days >= T370["horizon_d"]` ⇒ 收盘平 | 91–92 |
| 不提前止盈 | 代码里没有 target 分支 | — |
| 不移保本 | 代码里没有保本分支(`stop0` 存下来只作记录) | 120 |
| 一次进满、不自动加仓 | 每币一次开仓、满额;`sym in open_t` 就跳过 | 111–121 |
| 尺寸:档位 2 = 总名义占账户 20%,均分到各币 | `NOTIONAL = T370["tiers"][1]/2 = 0.10` 每币(资产 = `P.ASSETS` = BTC / ETH)⇒ 合计 20% | 50, 111 |
| ⓪ 结束当天收盘全平 | `if d in weekly and not weekly[d]["defend"]` ⇒ 用当天的收盘 mark 平仓 | 104–109 |
| 进出各 10 bp | 进 119 行 `eq -= COST * n`、出 99/107 行 `pnl -= COST * t["n"]`(`COST = 0.001`) | 99, 107, 119 |
| 资金费按天 | 每天 `pnl += t["n"] * fd` 并累加进 `t["fund"]`(空头在费率为正时收取 ✓) | 94–96 |
| 空头只在 ⓪ 里用 | 只在 `defend[days[i+1]]` 为真时开票 | 110 |

**与 S-929 A 组同形**:S-929 的 `simulate(mode="t370")`(`s929:76-139`)与 S-931 的 `account()`(脚本 76–127)在止损判定(`o ≥ stop` 走开盘价、否则 `h ≥ stop` 走认错线)、28 天到期平收盘、无 target、无保本、⓪ 退出全平、10 bp 进出、逐日资金费、`n = NOTIONAL × eq` 上,逐条一致;差别只在 S-931 把触发换成了生产 `trigger_1`(S-929 是自己写的 `trigger`,`s929:51-59`,数值同式)。
⇒ 预注册 36573「S-929 的 A 组原样」在**行为上成立**;只有触发那一段是换实现(T-445 的整改,数值同)。

---

## (e) `HOUSE_RULES` 的 uses / varies 如实吗 —— △ **varies 少写了三处;uses 里有一项是「口径成立」而非「按值使用」**

脚本 40–46 行:

```python
HOUSE_RULES = {
    "layer": "③ 加密腿(生产 X1V)+ ⓪ 否决 + 空头票",
    "ruler": "账户口径:回本时间、每段崩塌的损失、每段上涨拿到几成;票:占名义 % 的均值与盈亏比(DECISIONS 11-11 / 11-15)",
    "uses": ["T370", "EXPOSURE"],
    "varies": {"⓪ 否决": "S-931:新加的一层 —— ⓪ 确认转向后,X1V 的多头(含反弹单、回补)清零,直到 ⓪ 退出",
               "⓪ 签名": "S-931:回测里没有 Jazz 的签名,用 S-928 的 D1 防守代理(同 S-929)"},
}
```

**如实 ✓ 的部分**:
- 变的那两条都写了,而且与代码/预注册一致:① 「⓪ 否决」= 脚本 172 行 `g1 = veto(g0, defend_all)`,预注册 36572 同式 ✓;② 「⓪ 签名」= 脚本 170 行 `B.weekly_states(bdays, bclose, stable, taker, y2, "D1")`,预注册 36567「⓪ 的代理 = S-928 的 D1 原样」✓。预注册三问 #3「条件 = 盯不是单」也照实标了 ✓。
- 「只持现货」不碰 ✓:加密腿就是 ① 的现货 NAV(生产 `core_u_replay` / `cap_pit24` 都是现货持仓的回放),没有碰永续腿。

**△ 该写没写(按 RULEBOOK「用了哪些现行规则(原样)?改了哪一条?没写的就必须是现行值」的标准)**:
1. **资金费:固定年化 10%**,生产路径用的是实测 BTC 永续资金费(`forward_books.py:225/345`)。预注册 36571 写了,但 `varies` 没写 ⇒ 按 RULEBOOK 的标准,这属于「改了却没写」。
2. **① 的 NAV 序列:用的是 `cap_pit24`,生产的 tom_trader 核是 `core_u_replay`**(差 ~45pp,见 (a) 表)。预注册 36570 写了,但 `varies` 没写。
3. **加密腿在账户里的权重**:生产 T25 里这条腿占 30%(预注册 36566 也是这么写的),S-931 的账户里它占 **100%**;`varies` 没写。这一条同时决定下面 EXPOSURE 怎么读。

**△ `uses` 里 "EXPOSURE" 的写法**:脚本里 `EXPOSURE` 只出现 1 次 —— 就是 43 行这个列表本身,**没有任何一行读它的值**(grep 命中:43 行一处)。所以它是「口径上成立」而不是「按值使用」:
- 账户净敞口 = 加密腿 `g1 ∈ [0, 1.3]`(生产臂的上限 CAP = 1.3,`tom.py:20`)+ 空头 −0.2 ⇒ 净 ∈ [−0.2, 1.3],**落在** `EXPOSURE.allowed = (−0.3, 1.3)` 内(`house_rules.py:33`)⇒ 声明成立;
- 但生产那条「截在 [0, 1]」(`house_rules.py:33` `production`)在这个账户里**不适用**(加密腿占满 100%,不再被 30% 权重稀释),脚本也没有做任何截断 —— 属于「靠口径成立,不是按值使用」。
- `uses` 里没有 `PORTFOLIO`(杠杆 ≤ 5):账户总毛敞口 ≤ 1.5 < 5 ⇒ 不必写,不算漏。
- `uses` 里没有 `RV2`(多头票):脚本没有多头票 ✓ 不写是对的。

---

## 给 Seth 的待办(不在本卡动手)

1. **脚本还没进 origin/main** —— 本复核锚的是 sha256 `906c7181…c9de` 那份;落地版若不同,行号要重核。
2. **BASE 与生产 X1V 的两处输入差**((a) 1、2):要么把 BASE 换成生产的 `core_u_replay` + 实测资金费重跑,要么在 S-931 的结论句里写明「BASE 是同一条规则 × ① 历史锚 × 固定 10% 资金费」。**这两条都会改变 c1/c4 的数**(资金费进 g>1 的部分;① 序列决定崩塌/上涨的分母),不是措辞问题。
3. **`varies` 补三行**((e) 1、2、3):资金费、① 序列、加权口径。
4. **未平票成本口径**(c 末尾 1):脚本 126 行的 `1 × COST` 分支要不要改成字面的 `2 × COST`(会影响留出段票的均值与 payoff)。
5. **⓪ 周日全平检查的写法**(b 末尾):`if d in weekly` 依赖「周日也在 `days` 里」;本窗口成立(cap_pit24 日历齐全 2,484/2,484、355/355 周日),但写法上脆,建议改成「按最近的周日键」而不是「按当天是否在 weekly 里」。
6. `docs/research/s931_x1v_zero_veto.py` 里 `house_rules` 与 `RULEBOOK` 的一致性由 `tests/test_house_rules.py` 管;本次复核**没有改任何规则值**,故未动那两个文件(卡 forbidden_paths 也禁 `src/`)。

## 未核 / 无法从仓库侧核的项

- 私有数据 `research_data/s931_data.json` 不在仓库侧 ⇒ **没能逐点核对脚本用的 `core` 序列确实是 `cap_pit24`**(只能核预注册的声明与生产代码的差别)。
- 私有导出里 `px`(BTC/ETH 日线)的日历齐全性未核 ⇒ (b) 里「周日全平不会被跳过」这一条只核到 `cap_pit24` 这一侧。
- 按卡的要求,**没有重跑、没有改脚本、没有评价结果、没有登记情景**;结果段的所有数字都是引用台账 S-931 原文,不是本卡的产出。
