# T-238 v2 · R-v2 在同质永续序列 `perp_bv_daily` 上重验(S-719)

> **v2:perp_bv_daily**(覆盖 v1)。本轮把序列从 `ohlcv_daily(source=binance_um_hist)` 换成
> **`perp_bv_daily`**(真永续),宇宙换成 `perp_bv_pairs.kind='coin'`,成交额 dv = qv。
> 只读:不改代码、不做 DDL、不入库;DB 只读 `perp_bv_daily` / `perp_bv_pairs` / `style_index_pit_daily`。

## 0. 预注册(先写后算;照卡 S-719 原文,只把数据源换成 v2)

**判据(不变)**:**2026-08-08 前同键票占缓存的 ≥ 95%** 且 **2020-03 → 2026-08-08 总 R 与缓存的差在 ±10% 内**
⇒ ✅「验证在永续序列上成立」;否则 ❌ 并列出差在哪些票 / 哪些月。

**① 序列**:从 DB 拉 `perp_bv_daily` 全部符号 2019-10-01 → 昨天(翻页带 `order=symbol.asc,d.asc`;
落 `/Volumes/CometCloudAI/cometcloud-local/research/t238/_bars_pbv.jsonl`,写明拉取时间与行数);
与 T-237 的 `_bars_db.jsonl`(现货)和 t156/t159 缓存按 (symbol, d) 对齐,报三者两两的**收盘差中位**与
**成交额比值中位**(2026-08-08 前 / 后分开)。

**② 票**:s677 生成器、固定 (2.5, 20, 2)、majors 闸门同 S-627、信号窗 2020-03-01 → 2026-10-31、
成本 0.4% 来回、cap 10、f = 1%;在永续序列上生成票;与 770 张缓存逐票对比(两边都有 / 只缓存 / 只永续;
2026-08-08 前后分开计数);同键票 R 的相关与平均绝对差。

**③ 钱曲线**:年化 / 盯市 MDD / Calmar / 名义峰值(对 S-638 的 +24.4% / −32.3% / 0.99 倍);
按 S-677 的切片(它的 OOS 年份口径)各报总 R 与每票 R。

**④ 前向**:2026-10-19 → 昨天:永续序列上完整信号数、闸门状态、若有票列出来。

**⑤ 判**:按上面两条判据出 ✅ / ❌,并列出差异落在哪些票 / 哪些月。

**纪律**:不改代码、不做 DDL、不入库;探针脚本改同一个文件再跑。

## 1. v1 的结论(为什么换源)

v1(分支 `lane-b/T-238`,commit `1d2cb40b`)用 `ohlcv_daily(source=binance_um_hist)` 判 **❌**,原因不是口径
错而是**序列本身有洞**:

- `binance_um_hist` 是「现货历史 + 永续续写」的拼接表(续写函数 `um_bridge_fill` 从 `perp_bv_daily` 复制,
  `volume = qv / c`),不是一条同质的永续序列;
- 2026-08-08 前它与 770 张缓存**逐字节相同**(收盘相对差中位 0.00000000、成交额比值中位 1.0000),
  2026-08-08 后成交额比值中位 **5.4228** —— 缓存末段是现货量、um 是永续量;
- DB 的 `binance_hist` 相对缓存 08-08 后比值 1.0000 ⇒ 它是**混合量纲**的序列;
- um 序列有整段缺口(如 2026-10-28 缺失)、majors 只有 2026-07-10 起的连续日线 ⇒ 220 根预热不足。

⇒ v1 的 ❌ 是**序列的错**,不是 R-v2 的错。v2 直接读真永续表 `perp_bv_daily`,绕开拼接层。

## 2. v2 的数据拉取(本轮实测)

| 项 | 值 |
|---|---|
| 表 | `perp_bv_daily`(列:symbol / d / o / h / l / c / qv / tbqv) |
| 表内总行数(Content-Range exact count) | **668,222** |
| 拉取窗 `d >= 2019-10-01 & d <= 2026-11-04` 的 count | **668,222**(与全表相同 ⇒ 窗外无行) |
| 宇宙表 | `perp_bv_pairs`,**913** 行,列 = `symbol` / `kind` / `dead_from` |
| 翻页 | `order=symbol.asc,d.asc`;Range 页 0–999(服务端 max-rows=1000) |
| 拉取时间(UTC) | pairs:2026-11-05T03:09:32Z;日线:紧接其后同一进程 |
| 产物 | `research/t238/_bars_pbv.jsonl`(行)+ `research/t238/_pairs_pbv.json`(宇宙表 + meta)+ `research/t238/run.log` |

**抓取方式(工程决定,不是研究决定)**:单线程顺序翻页实测 ~70 行/秒(要 2.6 小时),故改**分片并行**:
按 `perp_bv_pairs` 的符号表切片(每片 12 个符号),每片一条 `symbol=in.(...)` + `order=symbol.asc,d.asc`
查询,10 个线程并行,片内 Range 0–999 翻页。
**覆盖校验(硬闸)**:各片行数合计必须等于表的 exact count(668,222),不等则**报错退出、不落半份**;
落盘后按片序(符号连续区间)合并,文件内全局仍按 (symbol, d) 有序。

**口径(v2 与 v1 的三处差异)**:
1. **序列**:`perp_bv_daily`(同质永续)替代 `ohlcv_daily(source=binance_um_hist)`(拼接)。
2. **宇宙**:`perp_bv_pairs.kind = 'coin'`,外加 `kind` 为空但 `dead_from` 有值的;再叠 `t159.EXCL`
   = {USDC, BTCDOM, DEFI}。
3. **成交额**:**dv = qv**(quote volume,USD)。脚本里存 `qv / close`,于是下游 `close × row[5] ≡ qv`,
   与现货侧的 `close × volume` 同量纲,①的三方成交额比值可直接比。

## 3. ②③④⑤ 的数字:本轮**未出**,下一轮收

本轮上下文预算在抓取阶段耗尽(92k token,被 lane guard 拦下),票生成 / 钱曲线 / 前向窗口的
数字由本轮启动的脚本产出,产物路径如下,**下一轮读它、不重跑**:

- 脚本:`docs/research/t238_rv2_um.py`(本分支,`--stage all` 直接从已落盘的 `_bars_pbv.jsonl` 起算)
- 结果:`docs/research/t238_results.json`
  - `meta` — 版本标记(`v2:perp_bv_daily`)、拉取时间、源表
  - `data.pbv` — 符号数 / 行数 / 首末日 / 有 >220 根的符号数 / 最早可出信号日
  - `data.pbv_universe` — 913 行里 kind 直方图、过滤前后符号数
  - `series.pbv_vs_cache` / `pbv_vs_db` / `cache_vs_db` — ① 的收盘差中位与成交额比值中位(08-08 前 / 后)
  - `selfcheck_cache` — 缓存侧重生成是否复现 t159 落盘的 770 张(自检闸)
  - `tickets.compare.pre_split` — ② 的同键票占比(判据第一条)
  - `tickets.compare.by_month` — 差落在哪些月
  - `money` — ③ 的年化 / MDD / Calmar / 名义峰值 + S-638 对照
  - `oos_s677` — ③ 的 S-677 切片(2018-01-01 → 2020-02-29 口径;注意本序列 min(d)=2019-12-31,
    **该切片在 v2 上是残缺的**,只能作部分覆盖的对照,不能当 OOS 复现)
  - `forward` — ④ 的 2026-10-19 → 昨天的闸门状态 / 宇宙 / 完整信号数 / 票
  - `judge` — ⑤ 的两条判据与 ✅ / ❌
- 运行日志:`/Volumes/CometCloudAI/cometcloud-local/research/t238/run.log`

**卡状态**:本轮留 `open`(不是 `in_review`):**②–⑤ 的数字还没出**,标 in_review 会让下一轮跳过这张卡。
下一轮读完 `t238_results.json` → 填本报告第 3 节 → 改卡 `in_review` + notes → push。

## 4. 纪律与边界

- 全程只读:没有 DDL、没有写库、没有改 `src/`;本次改动只在 `docs/research/` 与本卡。
- 未改任何规则:R-v2 的票生成器(`t159.run_long`,逐字照 `r_v2_tickets.sql`)、(2.5, 20, 2)、
  majors 闸门(S-627)、信号窗、成本 0.4%、cap 10、f=1% 全部照旧;**只有数据源/宇宙/成交额换了**。
- 没有零分布 / 多空盈亏的自写实现:本卡不需要(只做逐票对比与钱曲线,不自造统计量)。
- 前向预期:`docs/research/scenarios/lane-b-T-238.json`(≥ 3 条,到期按 Brier 结算)。
