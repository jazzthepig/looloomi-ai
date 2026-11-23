# 情景文件:lane 的前向预期,机器结算

每张研究卡交付时,把你对**结果之后会发生什么**的预期写成 `<lane>-T-NNN.json` 放在这里,随分支进 PR。
Seth 合并后,Railway 每小时把还没入账的条目写进 `scenario_ledger`(只追加,入账那天由数据库记),
到期按 Brier 结算进 `scenario_scores`,按作者汇总 —— 你说「70%」的那些事,实际成了几成,从此是量出来的。

```json
{
  "author": "lane-a",
  "entries": [
    {"id": "T-222-1", "scenario": "T-222 资金费套息",
     "statement": "BTC 永续 8 小时资金费 30 日均值在 2026-12-01 仍为正",
     "variable": "state:funding_btc_30d", "op": "gt", "lo": 0, "prob": 0.7, "horizon_d": "2026-12-01"}
  ]
}
```

规则(`src/data/evaluation/scenario_ledger.py` 校验,不合格的只报不写):
- `id` 唯一、以卡号开头;`variable` 四类:`close:<SYMBOL>`(ohlcv_daily 收盘)/ `high:<SYMBOL>[@HH]`、`low:<SYMBOL>[@HH]`(写下之后到结算日 HH:00 UTC 之间小时线的最高 / 最低 —— 「某时刻前碰没碰到某价位」,T-409)/ `state:<feature>`(state_daily, entity=panel)/
  `macro:<series>`(macro_daily)/ `manual`(人工结算);`op` 是 `between`(lo ≤ x ≤ hi)、`gt`(x > lo)、`lt`(x < hi);
- `prob` ∈ [0, 1];`horizon_d` 要晚于入账那天 —— **留 ≥ 7 天余量**,合并不是当天的事;
- 每张卡 ≥ 3 条,至少一条是自动结算的(close / state / macro);**不写收益承诺**,写可核的量。
- 写下之后不能改:要改观点就加新条目(新 id),旧的照常结算。

## 作废记录(第三类):`voids/`

台账只追加、不可改 —— 那是对的(事前写下的东西不能改),但对**登记错误**是错的:一条登记错了的命题进了池子就再也出不来,
它会被自动结算成一个看起来很正常的 outcome,并被算进作者的命中率与 Brier ⇒ 校准(这套装置里唯一的自我纠错信号)被污染。

所以有第三类记录,放 `docs/research/scenarios/voids/<作废人>-<UTC 日期>.json`:

```json
{"voided_by": "seth",
 "voids": [
   {"id": "T-417-1", "reason": "defective_threshold",
    "evidence": "docs/research/t417_audit.py → 81,200 是 BO20 触发价不是现价"}
 ]}
```

**作废 ≠ 结算**:作废 = 这条登记**从来不是一条有效的前向命题**;结算 = 命题为真/为假。
作废在 `scenario_scores` 里只留一行标记(`observed` / `outcome` / `brier` 全空),台账一行都不动
⇒ 不进校准、不会被结算、不再被算成「该结了」。`voids/` 是自己的目录,不会被当成情景文件读进来。

规则(`src/data/evaluation/scenario_ledger.py` 校验,不满足的那条被拒、其余照做):

1. `voided_by` 只能是 **seth / jazz / ai:\*** —— 作废是登记错误的更正,作者本人不能给自己的命题判死刑;
   lane 不能作废任何人的条目(否则就能把自己的失败样本从校准里拿掉)。
2. `reason` 是**闭集**:`defective_threshold`(阈值取错对象,如 BO20 触发价当现价)/ `defective_base_rate`(基率窗口与到期日不对齐)/
   `complement_pair`(与另一条互为补集 ⇒ 有一半注定错)/ `not_machine_checkable`(量不出一个数)/ `duplicate_id` /
   `superseded`(被新 id 接替,必须写 `superseded_by`)。**闭集里没有「被证伪」** —— 被证伪只能走结算。
3. 不能自己作废自己;**已结的不能作废**(结算是不可改的历史事实,作废擦不掉它)。
4. 台账里没有的 id **不写行,只点名**(`scenario_scores.id` 外键指向 `scenario_ledger.id`;补登记 = 造一条事后的假记录);
   点名会带出「为什么不能进库」。
5. 机器怎么认出作废行:唯一通道是 `note` 的**稳定前缀**(`作废 · `)+ 纯函数 `is_void(row)`;
   自动结算 / 人工结算 / 「该结了」三个消费点一律调它(不做自由文本匹配)。
6. **时点**:已结的不能作废 ⇒ 这一层必须**早于**那条的结算日落地,否则那条永远作废不掉。
