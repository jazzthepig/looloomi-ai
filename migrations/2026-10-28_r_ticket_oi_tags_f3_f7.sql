-- S-696 前向记录(台账):R-v2 每张纸面票在开票日同一截面上的 S-691 F3(ΔOI 30 天)与 F7(主动买卖比 7 天)规模中性分位。
-- 只记,不挡票。S-693 / S-695 在历史票上都没过;它们留下的探索(S-690 的亏损集中在「当天高杠杆 × 30 天杠杆在堆」)只能在新票上验。
alter table public.r_ticket_oi_tags add column if not exists p_doi30 double precision;
alter table public.r_ticket_oi_tags add column if not exists high_doi30 boolean;
alter table public.r_ticket_oi_tags add column if not exists p_taker7 double precision;
