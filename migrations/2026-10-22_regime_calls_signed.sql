-- 2026-10-22 · Jazz ⓪ 的判断带签名(S-666 / src/exec_host/verify.py)。
--
-- 为什么:Railway 10-21 公告存放环境变量的系统被入侵。能写 regime_calls 的人就能塞一条「on、3 档、战场 = 他拉盘的币」,
-- 主机第二天照着开 J 票。现在 Jazz 在自己的 Mac 上用 HMAC-SHA256 签每一条判断(scripts/regime_call.py),
-- 密钥只在 Jazz 的 Mac 与东京主机上 —— Railway 和库里都没有。库只原样保存签名内容与签名,主机自己验:
--   signed  签名覆盖的那段 JSON(state / conviction / battlefield / close / days / note / signed_at / nonce),原样
--   sig     HMAC-SHA256 十六进制(64 位)
-- 没签名的判断照收、照记分,但主机不为它开 J 票,也不放大 R-v2 票的风险(压回 1 倍)。
-- 加列,不改已有行;旧部署不写这两列也不受影响。

alter table public.regime_calls add column if not exists signed text;
alter table public.regime_calls add column if not exists sig text;
alter table public.regime_calls drop constraint if exists regime_calls_sig_hex;
alter table public.regime_calls add constraint regime_calls_sig_hex check (sig is null or sig ~ '^[0-9a-f]{64}$');
