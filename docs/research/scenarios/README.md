# 情景文件:lane 的前向预期,机器结算

每张研究卡交付时,把你对**结果之后会发生什么**的预期写成 `<lane>-T-NNN.json` 放在这里,随分支进 PR。
Seth 合并后,Railway 每小时把还没入账的条目写进 `scenario_ledger`(只追加,入账那天由数据库记),
到期按 Brier 结算进 `scenario_scores`,按作者汇总 —— 你说「70%」的那些事,实际成了几成,从此是量出来的。

```json
{
  "author": "lane-a",
  "entries": [
    {"id": "T-222-1", "author": "lane-a", "scenario": "T-222 资金费套息",
     "statement": "BTC 永续 8 小时资金费 30 日均值在 2026-12-01 仍为正",
     "variable": "state:funding_btc_30d", "op": "gt", "lo": 0, "prob": 0.7, "horizon_d": "2026-12-01"}
  ]
}
```

规则(`src/data/evaluation/scenario_ledger.py` 校验,不合格的只报不写):
- `id` 唯一、以卡号开头;`variable` 四类:`close:<SYMBOL>`(ohlcv_daily 收盘)/ `high:<SYMBOL>[@HH]`、`low:<SYMBOL>[@HH]`(写下之后到结算日 HH:00 UTC 之间小时线的最高 / 最低 —— 「某时刻前碰没碰到某价位」,T-409)/ `state:<feature>`(state_daily, entity=panel)/
  `macro:<series>`(macro_daily)/ `manual`(人工结算);`op` 是 `between`(lo ≤ x ≤ hi)、`gt`(x > lo)、`lt`(x < hi);
- 每条 entry 也要带 `author`(逐条 `validate()` 查「缺 author」);台账写入时以**文件级** `author` 为准,正文里的 author 不算数;
- `prob` ∈ [0, 1];`horizon_d` 要晚于入账那天 —— **留 ≥ 7 天余量**,合并不是当天的事;
- 每张卡 ≥ 3 条,至少一条是自动结算的(close / state / macro);**不写收益承诺**,写可核的量。
  自动量优先(自动结算不依赖人);但 `validate()` 与 `ingest_repo()` 都不强制「至少一条自动」—— 口径差 / A-B 差 / 名数这类量写不成 close/state/macro 时,整卡走 `manual` 合法(人工结算:结算人**不能是作者本人**,记录写 `docs/research/scenarios/settlements/`,`evidence` 要写出脚本路径 / SQL + 数);
- 写下之后不能改:要改观点就加新条目(新 id),旧的照常结算。
