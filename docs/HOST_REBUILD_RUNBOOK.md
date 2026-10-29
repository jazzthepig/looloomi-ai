# 东京执行主机重建(2026-10-29;Vultr 节点故障后)

**起因:** 10-26 21:42 UTC 起主机没有任何回报;Vultr 来信是节点故障,实例需要在新机器上重建。
**全部是 Jazz 的动作**(key 只经过 Jazz 的手;Seth 只在最后从库里核心跳)。按顺序做,每段做完再往下。

## A · HL 网页(上主机之前)

1. **换 API 钱包。** 旧的那把(`cometcloud-exec`)私钥在故障节点的磁盘上 —— 按已泄露对待:HL → API → 撤销它,
   再新建一把(比如 `cometcloud-exec-2`)、授权给主账户,私钥只复制这一次,只贴进第 C 段。API 钱包能下单、不能提币。
2. **手动单挪到另一个钱包**(TRADE_PATH §3g)。执行器按**整个**永续净值定 R-v2 每票风险,同一个账户里的手动单会改它的尺寸,
   也会让「真相之书」把你平掉的仓记成「交易所上已平」。HL 开子账户要累计成交 ≥ $100k,所以现在用另一个钱包隔开:
   手动交易用新钱包,这个账户整个留给执行器。
3. **钱分给哪条腿(你定):** 账上约 613 USDC。R-v2 每票风险 0.5%、最小名义 $10 ⇒ 永续里要 ≈ 550–600 才开得出止损宽的票(§3d);
   X1V 用现货 USDC,现在规则空仓、用不到钱。两种做法:
   - **(a)** 现在把 ≈ 600 从现货划到永续给 R-v2;X1V 的闸门重新打开那天,再划回一部分(或补钱)—— 那天我会提前一天提醒。
   - **(b)** 补钱,两条腿各自有钱。
   划转在 HL 网页做,执行器不划转。

## B · Vultr(实例是全新的才需要)

你的网络封了出站 22 端口,上一台主机 SSH 走 443。用 Vultr 网页控制台(View Console)以 root 登录,贴:

```bash
sed -i 's/^#\?Port .*/Port 443/' /etc/ssh/sshd_config &&
(systemctl disable --now ssh.socket 2>/dev/null || true) &&
systemctl enable --now ssh.service &&
systemctl restart ssh.service &&
ss -tlnp | grep ':443'
```

最后一行看到 `sshd` 在 443 上就行。Vultr 防火墙组若有,要放行 TCP 443。若实例是**从快照恢复**的,先看
`ls -l /etc/cometcloud/executor.env` —— 文件在就跳过第 C 段的写 env 那一步(脚本会问你要不要覆盖)。

## C · 主机上(root,一次贴完)

```bash
apt-get update -qq &&
apt-get install -y -qq git python3-venv &&
mkdir -p /opt/cometcloud &&
( [ -d /opt/cometcloud/repo/.git ] || git clone -q --depth 1 https://github.com/jazzthepig/looloomi-ai.git /opt/cometcloud/repo ) &&
git -C /opt/cometcloud/repo pull -q --ff-only &&
bash /opt/cometcloud/repo/deploy/executor/write_env.sh &&
bash /opt/cometcloud/repo/deploy/executor/install.sh
```

`write_env.sh` 会依次问(私钥 / token 输入不显示):

| 变量 | 从哪来 |
|---|---|
| `HL_ACCOUNT_ADDRESS` | 主钱包地址(0x…) |
| `HL_SUBACCOUNT_ADDRESS` | 留空(还没有子账户) |
| `HL_API_WALLET_PRIVATE_KEY` | A-1 新建的 API 钱包私钥 |
| `EXECUTOR_TOKEN` | Railway → Variables → `EXECUTOR_TOKEN` 复制 |
| `JAZZ_CALL_KEY` | Mac 上 `python3 scripts/regime_call.py keygen --show`;脚本会打印指纹,应与 Mac 上的一致(上一台是 `8ec89132`) |
| 开关 | 回车用默认:`EXECUTOR_MODE=live`、`EXECUTOR_TICKETS_MODE=live`(10-29:R-v2 继续真钱)、`EXECUTOR_VERIFY=report` |

## D · install.sh 自检要看到的

- `mode: live`;`agent.ok: true`(新 API 钱包已被主账户批准);`plan_http: 200`。
- `tickets.perp_account.equity` = 你划进永续的数;**没有** `warning`(有 ⇒ 永续里没钱,R-v2 开不了票)。
- `tickets.verify.jazz_call_key` = Mac 上的指纹。
- 最后三个服务 `active (running)`:`cometcloud-executor`、`cometcloud-recorder`、`cometcloud-whales`。

## E · Seth 核(你贴完告诉我)

```sql
select at, outcome, detail->>'kind', detail->>'mode', detail->'balances'
from loop_attempt where loop_name = 'executor_host' order by at desc limit 3;
```

一小时一行心跳;第一轮进场 / 平仓判断在 UTC 00:50 前后(R-v2)与收盘后(X1V)。
