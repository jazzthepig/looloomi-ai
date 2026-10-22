# Railway 恢复构建之后:一次轮换完所有密钥(2026-10-22)

**起因:** Railway 10-21 公告存放客户环境变量的系统被入侵,部分变量被解密拿走,建议轮换全部变量
(<https://blog.railway.com/p/security-disclosure-wednesday-october-21st>)。构建暂停期间换了也部署不上、只会把线上弄停,
所以等构建恢复后**一次做完**。在那之前 Seth 盯 Supabase 访问日志:那把 secret key 只要出现在非 Railway 的 IP 上,就立刻删、不等。

**为什么分两步部署:** 恢复后的第一次部署会带上积压的几十个提交。**先用旧密钥把新代码部署好、验活**,再换密钥 ——
两件事分开,哪一步出问题一眼就知道是代码还是密钥。

**谁做:** 每一步都是 Jazz 的(密钥只经过 Jazz 的手);Seth 在每一步之后给验证命令并核对 Supabase 日志。

## 0 · 构建恢复、积压的代码先上线(旧密钥)

- 看 <https://status.railway.com> 写明我们所在的套餐已恢复构建。
- Railway 自己会部署最新提交;没动就在 Railway 里对最新部署点 Redeploy。
- 验:`curl -s https://web-production-0cdf76.up.railway.app/internal/build-state` 的 `git_sha_short` = `origin/main` 最新;
  探针 `bash scripts/external_probe.sh` 绿。

## 1 · Supabase secret key(最大的一把:绕过 RLS 读写全库)

1. Supabase → Settings → API Keys → Secret keys → 新建一把(起名 `railway-2026-10`)。
2. Railway → Variables:`SUPABASE_KEY` 换成新的(`SUPABASE_SERVICE_KEY` 若存在也换成同一把)。**先别部署**,接着做第 2–4 步,
   所有 Railway 变量改完再一次部署。
3. 部署后验(Seth):Supabase 日志里新前缀从 Railway 的 IP 来、200 / 201;旧的那把前缀不再出现。
4. 删掉旧的那把 secret key。

## 2 · INTERNAL_TOKEN(Mac 推 CIS、⓪ 开关、一键停都用它)

新值:`openssl rand -hex 32`。**同一时刻**改三处:Railway 变量 `INTERNAL_TOKEN`、Mac 引擎的 env
(`~/.cometcloud/engine.env`;还没搬就是 `cometcloud-local/.env`)、仓库根目录 `.env`(`scripts/regime_call.py` 读它)。
验:30 分钟内 `build-state` 的 `last_cis_push.age_seconds` < 1800;`python3 scripts/regime_call.py status` 不报 403。

## 3 · EXECUTOR_TOKEN(东京主机 ↔ Railway)

新值:`openssl rand -hex 32`。Railway 变量 `EXECUTOR_TOKEN` + 主机 `/etc/cometcloud/executor.env` 的 `EXECUTOR_TOKEN`,
然后主机上 `bash /opt/cometcloud/repo/deploy/executor/install.sh`(顺带拉到主机复核那一版)。
验:install.sh 的自检里 `plan_http: 200`,`tickets.verify.mode: report`。

## 4 · 其余 Railway 变量

| 变量 | 在哪换 | 不换的后果 |
|---|---|---|
| `UPSTASH_REDIS_REST_TOKEN` | Upstash 控制台 → 该库 → Reset token | 别人能改缓存 ⇒ 对外接口吐假数 |
| `COINGECKO_API_KEY` / `EODHD_API_KEY` / `FRED_API_KEY` / `SHARPE_AI_KEY` / `SANTIMENT_KEY` / `MORALIS_API_KEY` / `HELIUS_API_KEY` / `ETHERSCAN_API_KEY` / `CRYPTORANK_API_KEY` / `JEV_API_KEY` | 各家控制台 | 额度被盗用、付费档被刷 |
| `TELEGRAM_BOT_TOKEN`(+ `TELEGRAM_WEBHOOK_SECRET`) | BotFather `/revoke` | 别人能用我们的机器人给你发「告警」 |
| `RESEND_API_KEY` | Resend 控制台 | 别人能用我们的域名发邮件 |
| `LLM_API_KEY` / `NARRATIVE_LLM_API_KEY` | 对应推理服务 | 攻击者点名要的就是这类(推理费用) |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings | 有写权限就是供应链风险,优先级最高。新的只给公开仓库只读,或干脆不设 |

**`GITHUB_TOKEN`、推理 key、`RESEND_API_KEY` 不必等构建恢复 —— 现在就在各家作废**(线上只是暂时少这几个功能)。

## 5 · 收尾验证(Seth)

- Supabase 日志:旧 secret 前缀 0 次;所有 secret 请求来自 Railway(`asOrganization = Railway`)或 Mac。
- `bash scripts/external_probe.sh` 绿;`bash scripts/preflight.sh` 绿。
- PROJECT_STATE OPEN RISK 记一行「Railway 变量已全部轮换(日期)」。

**不在 Railway 上、不用换的:** HL API 钱包私钥(只在东京主机)、`JAZZ_CALL_KEY`(只在 Jazz 的 Mac 与主机)、
lane 的 publishable key(只读,不在 Railway)。
