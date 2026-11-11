# 人工命题的结算记录

`variable = manual` 的命题到期后,在这里交结算。一个文件一批,文件名 `<结算人>-<UTC 日期>.json`:

```json
{"settled_by": "lane-b",
 "settlements": [
   {"id": "T-342-4", "observed": 1.013, "evidence": "select … from forward_book_nav …(RB_T25_Y 1.0421 / T25_K 1.0287)"}
 ]}
```

三条纪律(`src/data/evaluation/scenario_ledger.settle_manual`,不满足的那条被拒、其余照结):

1. 只交**观测值 + 证据**。成没成由登记时的 `op / lo / hi` 算,文件里写 `outcome` 没有用。
2. **不结自己的。** lane-b 不结 lane-b 写的命题;Seth 写的由 lane 结。
3. 到期之后才能结;结过的不重结。量不出来就不交 —— 不要填 0。

随分支进 PR;Seth 合并后,部署的下一个整点入账(`scenario_scores`,`code_ref` 标 manual)。
该结哪些:`GET /internal/scenarios` 的 `manual_open`(按作者方:已到期 / 30 天内到期)。
