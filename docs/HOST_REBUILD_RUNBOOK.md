# 东京执行主机重建(2026-10-29;Vultr 节点故障后)

**起因:** 10-26 21:42 UTC 起主机没有任何回报;Vultr 来信是节点故障(硬件,不是入侵)。
**全部是 Jazz 的动作**(key 只经过 Jazz 的手);Seth 最后从库里核心跳。

## 先看一眼:盘还在不在

在 Mac 终端:`ssh -p 443 root@<IP>`(IP 在 Vultr → Products → 那台机器 → Overview;上一台是 45.32.39.6)。
- **连得上** ⇒ 原盘恢复了,env 和 API 钱包私钥都还在。只跑下面第 2 步那一行(它会看到 env 在、跳过写 env,只更新代码并重启)。
- **连不上** ⇒ 多半是新机器(默认只开 22,而你的 VPN 封 22)。**临时断开 VPN**,`ssh root@<IP>`(密码在 Overview 页面复制)。
  出现 `REMOTE HOST IDENTIFICATION HAS CHANGED`:机器重建过、指纹变了是正常的 ——
  `ssh-keygen -R 45.32.39.6` 后重连。
- 网页控制台(View Console)只作最后手段:它的键盘映射会把 `/`、`|`、`>` 这类符号打错(10-29 实测:`2>/dev/null`
  被打坏,报 No such file or directory)。

## 1 · HL 网页(只在「新机器」时需要)

- **API 钱包:** 不是泄露,不用为安全换。只有在新机器上、而你手上没有那把私钥的备份时,才需要在 HL → API 新建一把
  (授权给主账户;能下单不能提币),旧的那把顺手撤销。
- **R-v2 的保证金(你定):** 永续里要 ≈ 550–600 USDC(每票风险 0.5%、最小名义 $10,§3d)。(a) 现在从现货划到永续,
  X1V 重新进场前再划回一部分(我会提前一天提醒);(b) 补钱,两条腿各有各的钱。
- **手工单换个钱包做**(TRADE_PATH §3g):执行器按整个永续净值定每票尺寸,同账户里的手工单会改它的尺寸。

## 2 · 主机上:一行

ssh 进去之后(root),贴这一行:

```bash
curl -fsSL https://raw.githubusercontent.com/jazzthepig/looloomi-ai/main/deploy/executor/bootstrap.sh -o b.sh && bash b.sh
```

它依次做:装系统包 → SSH 同时开 22 和 443(不关 22,改完当前连接不断;防火墙放行 443)→ 拉代码 →
**没有 env 才**问你要值(`write_env.sh`,私钥 / token 输入不显示)→ `install.sh`(自检 → 起服务)。

`write_env.sh` 会问:

| 变量 | 从哪来 |
|---|---|
| `HL_ACCOUNT_ADDRESS` | 主钱包地址(0x…) |
| `HL_SUBACCOUNT_ADDRESS` | 回车跳过 |
| `HL_API_WALLET_PRIVATE_KEY` | API 钱包私钥(原来那把或新建那把) |
| `EXECUTOR_TOKEN` | Railway → Variables → `EXECUTOR_TOKEN` |
| `JAZZ_CALL_KEY` | Mac 上 `python3 scripts/regime_call.py keygen --show`;脚本打印的指纹应是 `8ec89132` |
| 开关 | 一路回车:`EXECUTOR_MODE=live`、`EXECUTOR_TICKETS_MODE=live`、`EXECUTOR_VERIFY=report` |

## 3 · 自检要看到的

- `mode: live`;`agent.ok: true`;`plan_http: 200`。
- `tickets.perp_account.equity` = 永续里的数;**没有** `warning`(有 ⇒ 永续里没钱,R-v2 开不了票)。
- `tickets.verify.jazz_call_key` = `8ec89132`。
- 三个服务 `active (running)`:`cometcloud-executor`、`cometcloud-recorder`、`cometcloud-whales`。

之后 `ssh -p 443 root@<IP>` 就能连(VPN 开着也行)。贴完告诉 Seth,我从 `loop_attempt` 核心跳。
