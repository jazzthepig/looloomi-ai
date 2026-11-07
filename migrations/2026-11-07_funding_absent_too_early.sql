-- 2026-11-07 · funding_vision_absent 记了「还没发布」的月:2026-10 的月档 11-01 去取时 Binance 还没上传 ⇒ 404 ⇒ 225 个名字被记成
-- 「那个月没有文件」,以后永不再取(GMXUSDT-fundingRate-2026-10.zip 11-07 实测 200)。代码侧加了宽限(月末之后 10 天内的 404
-- 不记缺档,下一轮重试;binance_vision_funding.ABSENT_GRACE_DAYS)。这里把最近一个完整月的缺档标记清掉,让它们重取 ——
-- 真正没有文件的会在宽限期过后重新被记上(标记是可再生的缓存,不是数据)。
delete from public.funding_vision_absent where month = date '2026-10-01';
