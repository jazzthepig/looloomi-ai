# Railway 恢复构建之后:一次轮换完所有密钥(2026-10-22)

**起因:** Railway 10-21 公告存放客户环境变量的系统被入侵,部分变量被解密拿走,建议轮换全部变量
(<https://blog.railway.com/p/security-disclosure-wednesday-october-21st>)。构建暂停期间换了也部署不上、只会把线上弄停,
所以等构建恢复后**一次做完**。在那之前 Seth 盯 Supabase 访问日志:那把 secret key 只要出现在非 Railway 的 IP 上,就立刻删、不等。

**为什么分两步部署:** 恢复后的第一次部署会带上积压的几十个提交。**先用旧密钥把新代码部署好、验活**,再换密钥 ——
两件事分开,哪一步出问题一眼就知道是代码还是密钥。

**谁做:** 每一步都是 Jazz 的(密钥只经过 Jazz 的手);Seth 在每一步之后给验证命令并核对 Supabase 日志。

**进度(10-22 17:20 UTC):** 第 0 步 ✅;`GITHUB_TOKEN` ✅(Jazz 已在 Railway 换成新的一把)。**剩第 1–4 步,一次改完再部署,然后第 5 步。**

## 0 · 构建恢复、积压的代码先上线(旧密钥)—— ✅ 10-22

- ✅ 构建 ~06:14 UTC 恢复,积压全部上线;此后每次推送都正常部署(17:14 线上 0bb57d60;16:38 有一次构建失败,下一推 44 秒上线 —— 平台偶发)。
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
| `GITHUB_TOKEN` | ✅ **10-22 全部做完**:与 Mac 的 `gh` 共用的那份 OAuth 授权已撤销;Mac 改用只限本仓库的 fine-grained token;Railway 已由 Jazz 换成新的一把 | —— 一个用途一把,不再与 Mac 共用 |

表里的变量 Railway 上没有的(Jazz 10-22:LLM 相关的 key 不多)直接跳过 —— 以 Railway → Variables 里实际有的为准,一行一行对。

## 5 · 收尾验证(Seth)

- Supabase 日志:旧 secret 前缀 0 次;所有 secret 请求来自 Railway(`asOrganization = Railway`)或 Mac。
- `bash scripts/external_probe.sh` 绿;`bash scripts/preflight.sh` 绿。
- PROJECT_STATE OPEN RISK 记一行「Railway 变量已全部轮换(日期)」。

**不在 Railway 上、不用换的:** HL API 钱包私钥(只在东京主机)、`JAZZ_CALL_KEY`(只在 Jazz 的 Mac 与主机)、
lane 的 publishable key(只读,不在 Railway)。

---

# 11-05 全量轮换补遗:10-22 之后新增的使用方,以及每把钥匙在哪几处

**为什么要补:** 10-22 之后多了几处读钥匙的地方(lane 的只读 key、东京主机的执行器、⓪ 签名、agent 判断臂、lane 的备用后端)。
**少换一处 = 那一处静默停**(执行器 / CIS 推送 / lane 读库都是「拿不到 ⇒ 不做」,不会报错到你面前)。值只经过 Jazz 的手;下面只有**名字与位置**。

**顺序:** ① 只在 Railway 的(第 4 节那张表 + `LLM_API_KEY`)→ ② 两边共用的(`INTERNAL_TOKEN`、`EXECUTOR_TOKEN`、`JAZZ_CALL_KEY`)**同一时刻**改两边 → ③ Supabase 两把 → ④ **最后**才动钱相关的 `HL_API_WALLET_PRIVATE_KEY`(避开整点后 5 分钟的执行轮次)。Railway 变量全部改完**只部署一次**。

| 钥匙 | 在哪几处(全部要换) | 不换 / 漏换的样子 | 换完怎么验(不打印值) |
|---|---|---|---|
| Supabase **secret** key | Railway `SUPABASE_KEY`(`SUPABASE_SERVICE_KEY` 若在,同一把)· Mac 引擎 env(`~/.cometcloud/engine.env`;Minimax 根下脚本读 `SUPABASE_KEY` / `SUPABASE_SERVICE_KEY`)· 仓库根 `.env`(Seth 的脚本) | 循环写库全 401,`loop_attempt` 停在换钥匙那一刻 | Seth 查 `select max(at) from loop_attempt` 在 10 分钟内;Supabase 日志旧前缀 0 次 |
| Supabase **publishable** key(lane 只读) | `~/.cometcloud/lane.env`(`SUPABASE_URL` / `SUPABASE_KEY`,必须是 `sb_publishable_` 开头,否则 lane_bot 不给 lane) | lane 读库全 401,交付里写「连不上库」 | `python3 scripts/lane_bot/lane_bot.py --status`;下一轮 lane 回复里有行数 |
| `INTERNAL_TOKEN` | Railway · Mac 引擎 env(CIS 推送)· 仓库根 `.env`(`scripts/regime_call.py`、seth_bot 的核对) | Mac 推 CIS 403,`last_cis_push` 变老;⓪ 开关 403 | `curl -s https://web-production-0cdf76.up.railway.app/internal/build-state` 的 `last_cis_push.age_seconds` < 1800 |
| `EXECUTOR_TOKEN` | Railway · 东京主机 `/etc/cometcloud/executor.env` → `bash /opt/cometcloud/repo/deploy/executor/install.sh` | 主机拿不到计划 ⇒ 不交易(安全失败),2 小时后看门狗发 Telegram | install.sh 自检 `plan_http: 200`;Seth 查 `executor_host` 下一个整点有行 |
| `JAZZ_CALL_KEY`(⓪ 签名) | Mac(`scripts/regime_call.py` 读的 key 文件)· 东京主机 executor.env | 主机验签失败 ⇒ J 票与信心倍数一律不生效(强制) | `python3 scripts/regime_call.py status` 不报签名错;主机日志只记指纹 |
| `HL_API_WALLET_PRIVATE_KEY` | **只在**东京主机 executor.env;轮换 = HL 网页上用主账户新批一个 API 钱包 → 换 env → 重启 → 撤销旧的 | 真钱下单失败 | Seth 查 `executor_host` 下一轮 `mode = live` 且无 error;HL 网页上旧 API 钱包已撤 |
| `LLM_API_KEY`(MiniMax 推理 API) | Railway(`LLM_BASE_URL` = `https://api.minimax.io/v1`,`LLM_MODEL` = `MiniMax-M3`,三项都 strip 过换行) | 新闻帖退回模板;**agent 判断臂(S-725)当天空着** | Seth 查 `loop_attempt` 的 `_agent_judgment_loop` 不再 refused、`agent_judgment_daily` 有当天行 |
| lane 的 MiniMax coding plan token | 三个 lane 各自 claude 设置(`ANTHROPIC_AUTH_TOKEN`)· `~/.cometcloud/lane_fallback.env`(若配了) | lane 轮次 exit 1「auth」 | `lane_bot.py --status` 下一轮 exit 0 |
| `TELEGRAM_BOT_TOKEN`(+ webhook secret) | Railway(群按标题自动找,换 token 不用改 chat id) | 简报 / 群帖 / 看门狗告警全停 | 下一条 feed 帖或 01:00 UTC 简报到群 |
| CoinGecko / EODHD / FRED / Upstash | Railway **和** Mac 引擎 env(Minimax 根下 `CG_PRO_API_KEY` / `COINGECKO_API_KEY` / `EODHD_API_KEY` / `FRED_API_KEY` / `UPSTASH_REDIS_REST_TOKEN`)| 面板 / 宏观 / 缓存某一侧断 | Seth 查 `ohlcv_daily` 当天 coingecko_pro_ohlc / eodhd 有行 |
| 其余只在 Railway 的(第 4 节表:Sharpe / Santiment / Moralis / Helius / Etherscan / CryptoRank / JEV / Dune / Resend / GitHub) | Railway(Mac 的 gh 是另一把 fine-grained,10-22 已分开) | 对应数据源那一块空 | 跟着上面一起看 `loop_attempt` 有没有新 error |

**做完告诉 Seth 一句「换完了」** —— Seth 从库这侧把上表最后一列逐条核一遍,结果写进 PROJECT_STATE。
