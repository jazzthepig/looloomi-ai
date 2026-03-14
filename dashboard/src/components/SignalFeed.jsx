import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/* ─── Signal Types ───────────────────────────────────────────────────── */
const SIGNAL_TYPES = {
  MACRO:    { label: "MACRO",    color: T.gold,   bg: "rgba(200,168,75,0.12)", border: "rgba(200,168,75,0.2)" },
  WHALE:    { label: "WHALE",    color: T.purple, bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.2)" },
  FUNDING:  { label: "FUNDING",  color: T.blue,   bg: "rgba(75,158,255,0.10)", border: "rgba(75,158,255,0.2)" },
  FLOW:     { label: "FLOW",     color: T.green,  bg: "rgba(0,232,122,0.08)", border: "rgba(0,232,122,0.2)" },
  RISK:     { label: "RISK",     color: T.red,    bg: "rgba(255,61,90,0.10)", border: "rgba(255,61,90,0.2)" },
  MOMENTUM: { label: "MOMENTUM", color: T.cyan,   bg: "rgba(0,200,224,0.10)", border: "rgba(0,200,224,0.2)" },
};

const IMPORTANCE_STYLES = {
  HIGH: { color: T.red, bg: "rgba(255,61,90,0.12)", border: "rgba(255,61,90,0.25)" },
  MED:  { color: T.gold, bg: "rgba(200,168,75,0.10)", border: "rgba(200,168,75,0.2)" },
  LOW:  { color: T.t3, bg: "rgba(255,255,255,0.04)", border: T.border },
};

/* ─── Helper Functions ───────────────────────────────────────────────── */
const formatRelativeTime = (isoTimestamp) => {
  const timestamp = new Date(isoTimestamp).getTime();
  const diff = Date.now() - timestamp;
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const minutes = Math.floor(diff / (1000 * 60));

  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }
  if (hours >= 1) {
    return `${hours}h ago`;
  }
  return `${minutes}m ago`;
};

/* ─── Mock Signal Data (Fallback) ────────────────────────────────────────── */
const MOCK_SIGNALS = [
  {
    "id": "sig_001",
    "type": "WHALE",
    "importance": "HIGH",
    "description": "Abraxas Capital 将 4.8 亿美元 USDC 从 Coinbase 转移至冷钱包私钥托管，链上追踪显示此类操作历史数据表明 72 小时内 BTC 平均上涨 8.3%",
    "affected_assets": ["BTC", "USDC"],
    "timestamp": "2026-03-14T08:15:00Z",
    "source": "Nansen",
    "confidence": 0.87
  },
  {
    "id": "sig_002",
    "type": "WHALE",
    "importance": "HIGH",
    "description": "Jump Crypto 钱包地址近 30 天净买入 12,450 ETH，均价约 $2,510，累计价值 3,120 万美元",
    "affected_assets": ["ETH"],
    "timestamp": "2026-03-14T07:42:00Z",
    "source": "Nansen",
    "confidence": 0.92
  },
  {
    "id": "sig_003",
    "type": "WHALE",
    "importance": "MED",
    "description": "Wintermute 在以太坊链上新增 8500 万美元稳定币部署，主要为 USDC 和 DAI，做市策略规模扩张",
    "affected_assets": ["ETH", "USDC", "DAI"],
    "timestamp": "2026-03-14T06:30:00Z",
    "source": "DeFiLlama",
    "confidence": 0.78
  },
  {
    "id": "sig_004",
    "type": "WHALE",
    "importance": "LOW",
    "description": "休眠 5 年的比特币钱包地址激活，转出 1,247 BTC（价值约 1.12 亿美元），转移到多个新地址",
    "affected_assets": ["BTC"],
    "timestamp": "2026-03-14T04:18:00Z",
    "source": "链上数据",
    "confidence": 0.85
  },
  {
    "id": "sig_005",
    "type": "FLOW",
    "importance": "HIGH",
    "description": "Ondo USDY 单日净流入 2,370 万美元，为本月最高单日数据，机构 RWA 配置信号持续强化",
    "affected_assets": ["ONDO", "USDY"],
    "timestamp": "2026-03-14T08:55:00Z",
    "source": "DeFiLlama",
    "confidence": 0.91
  },
  {
    "id": "sig_006",
    "type": "FLOW",
    "importance": "MED",
    "description": "Curve DAO 协议 TVL 24 小时内增长 1,800 万美元，DeFi 套利资金和稳定币流动性迁移加速",
    "affected_assets": ["CRV", "USDC"],
    "timestamp": "2026-03-14T07:12:00Z",
    "source": "DeFiLlama",
    "confidence": 0.82
  },
  {
    "id": "sig_007",
    "type": "FLOW",
    "importance": "MED",
    "description": "Aave V3 新增 12 个大型机构地址，锁仓量增长 4,200 万美元，机构参与度回升",
    "affected_assets": ["AAVE", "USDC", "ETH"],
    "timestamp": "2026-03-14T05:48:00Z",
    "source": "Nansen",
    "confidence": 0.79
  },
  {
    "id": "sig_008",
    "type": "FLOW",
    "importance": "LOW",
    "description": "Stacks sBTC 锁仓量突破 1.5 万 BTC，Bitcoin L2 叙事推动原生资产流动",
    "affected_assets": ["STX", "BTC"],
    "timestamp": "2026-03-14T03:22:00Z",
    "source": "DeFiLlama",
    "confidence": 0.76
  },
  {
    "id": "sig_009",
    "type": "FUNDING",
    "importance": "HIGH",
    "description": "ETH 永续合约资金费率连续 18 小时为负（-0.04%），Coinglass 历史数据显示此后 48 小时内价格修复概率达 73%",
    "affected_assets": ["ETH"],
    "timestamp": "2026-03-14T08:30:00Z",
    "source": "Coinglass",
    "confidence": 0.88
  },
  {
    "id": "sig_010",
    "type": "FUNDING",
    "importance": "MED",
    "description": "BTC 矿工收入骤降 28%至每 TH/s 14.2 美元，挖矿盈利能力触及 6 个月低点，部分小矿池考虑关机",
    "affected_assets": ["BTC"],
    "timestamp": "2026-03-14T06:55:00Z",
    "source": "链上数据",
    "confidence": 0.84
  },
  {
    "id": "sig_011",
    "type": "FUNDING",
    "importance": "LOW",
    "description": "MakerDAO PSM 储备金达 52 亿美元创年度新高，DAI 发行量增长 3.8%",
    "affected_assets": ["MKR", "DAI"],
    "timestamp": "2026-03-14T04:45:00Z",
    "source": "DeFiLlama",
    "confidence": 0.81
  },
  {
    "id": "sig_012",
    "type": "RISK",
    "importance": "HIGH",
    "description": "币安 BTC 永续合约多空比触及 0.62 极端值，Coinglass 数据显示多头集中度过高，短期回调风险加剧",
    "affected_assets": ["BTC"],
    "timestamp": "2026-03-14T08:08:00Z",
    "source": "Coinglass",
    "confidence": 0.86
  },
  {
    "id": "sig_013",
    "type": "RISK",
    "importance": "MED",
    "description": "以太坊 Gas 费用飙升 340% 至 180 gwei，NFT 铸造热潮导致网络拥堵",
    "affected_assets": ["ETH"],
    "timestamp": "2026-03-14T07:33:00Z",
    "source": "链上数据",
    "confidence": 0.79
  },
  {
    "id": "sig_014",
    "type": "RISK",
    "importance": "LOW",
    "description": "DeFi 协议 EigenLayer TVL 单日下降 2.1 亿美元，Liquid Restaking 市场出现获利了结",
    "affected_assets": ["EIGEN", "ETH"],
    "timestamp": "2026-03-14T05:15:00Z",
    "source": "DeFiLlama",
    "confidence": 0.72
  },
  {
    "id": "sig_015",
    "type": "MOMENTUM",
    "importance": "HIGH",
    "description": "Solana DEX 7 日交易量达 184 亿美元，超越以太坊主网同期 142 亿美元，连续第 3 周保持领先",
    "affected_assets": ["SOL"],
    "timestamp": "2026-03-14T08:00:00Z",
    "source": "DeFiLlama",
    "confidence": 0.94
  },
  {
    "id": "sig_016",
    "type": "MOMENTUM",
    "importance": "MED",
    "description": "Chainlink CCIP 跨链桥单日转账额突破 2.5 亿美元，网络效应持续扩大",
    "affected_assets": ["LINK"],
    "timestamp": "2026-03-14T06:20:00Z",
    "source": "DeFiLlama",
    "confidence": 0.83
  },
  {
    "id": "sig_017",
    "type": "MOMENTUM",
    "importance": "LOW",
    "description": "Toncoin 链上日活跃地址数突破 100 万创历史新高，生态 DApp 活跃度持续攀升",
    "affected_assets": ["TON"],
    "timestamp": "2026-03-14T04:38:00Z",
    "source": "链上数据",
    "confidence": 0.81
  },
  {
    "id": "sig_018",
    "type": "MACRO",
    "importance": "HIGH",
    "description": "美国 SEC 就现货以太坊 ETF 零售准入征求意见，审批截止日期 2026-04-15，市场预期通过概率升至 78%",
    "affected_assets": ["ETH"],
    "timestamp": "2026-03-14T08:45:00Z",
    "source": "Alternative.me",
    "confidence": 0.89
  },
  {
    "id": "sig_019",
    "type": "MACRO",
    "importance": "MED",
    "description": "贝莱德代币化基金 AUM 突破 4.5 亿美元，传统金融机构加速布局链上资产",
    "affected_assets": ["ONDO", "BLK"],
    "timestamp": "2026-03-14T06:05:00Z",
    "source": "Nansen",
    "confidence": 0.85
  },
  {
    "id": "sig_020",
    "type": "MACRO",
    "importance": "LOW",
    "description": "香港 SFC 就代币化货币基金零售准入新框架征求意见，意见截止日期 2026-04-15",
    "affected_assets": ["HKDR", "USDC"],
    "timestamp": "2026-03-14T03:55:00Z",
    "source": "Alternative.me",
    "confidence": 0.77
  }
];

/* ─── Fetch Real Signals ───────────────────────────────────────────────── */
async function fetchSignalsFromAPI() {
  try {
    const response = await fetch("/api/v1/signals");
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    const data = await response.json();
    return data.signals?.length > 0 ? data.signals : MOCK_SIGNALS;
  } catch (e) {
    console.error("Failed to fetch signals:", e);
    return MOCK_SIGNALS;
  }
}

/* ─── Signal Row Component ─────────────────────────────────────────────── */
const SignalRow = ({ signal, isNew }) => {
  const typeConfig = SIGNAL_TYPES[signal.type] || SIGNAL_TYPES.MACRO;
  const impStyle = IMPORTANCE_STYLES[signal.importance] || IMPORTANCE_STYLES.LOW;

  return (
    <div
      className={isNew ? "signal-row new" : "signal-row"}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        gap: 11,
        alignItems: "start",
        padding: "13px 16px",
        borderBottom: `1px solid ${T.border}`,
        transition: "background 0.14s",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "rgba(255,255,255,0.02)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      {/* Type Badge */}
      <div className={`stype st-${signal.type.toLowerCase()}`} style={{
        fontFamily: FONTS.display,
        fontSize: 7,
        fontWeight: 700,
        letterSpacing: "0.12em",
        padding: "3px 6px",
        borderRadius: 3,
        background: typeConfig.bg,
        color: typeConfig.color,
        border: `1px solid ${typeConfig.border}`,
        textTransform: "uppercase",
        marginTop: 1,
        whiteSpace: "nowrap",
      }}>
        {typeConfig.label}
      </div>

      {/* Content */}
      <div className="sr-body" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <div className="sr-title" style={{
          fontFamily: FONTS.display,
          fontSize: 11,
          fontWeight: 600,
          color: T.t1,
          letterSpacing: "0.01em",
          lineHeight: 1.35,
        }}>
          {signal.description}
        </div>
        {/* Asset Tags */}
        <div className="sr-assets" style={{ display: "flex", gap: 3, flexWrap: "wrap", marginTop: 2 }}>
          {signal.affected_assets?.map((asset) => (
            <span key={asset} className="sr-asset" style={{
              fontSize: 8,
              fontFamily: FONTS.mono,
              color: T.t3,
              background: "rgba(255,255,255,0.045)",
              border: `1px solid ${T.border}`,
              padding: "1px 5px",
              borderRadius: 2,
            }}>
              {asset}
            </span>
          ))}
        </div>
      </div>

      {/* Right: Time & Importance */}
      <div className="sr-right" style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, minWidth: 54 }}>
        <div className="sr-time" style={{
          fontSize: 8,
          color: T.t3,
          whiteSpace: "nowrap",
        }}>
          {formatRelativeTime(signal.timestamp)}
        </div>
        {signal.importance && (
          <div className={`impact imp-${signal.importance.toLowerCase()}`} style={{
            fontFamily: FONTS.display,
            fontSize: 8,
            fontWeight: 700,
            letterSpacing: "0.12em",
            padding: "2px 7px",
            borderRadius: 3,
            background: impStyle.bg,
            color: impStyle.color,
            border: `1px solid ${impStyle.border}`,
          }}>
            {signal.importance}
          </div>
        )}
      </div>
    </div>
  );
};

/* ─── Skeleton Row ───────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{
    display: "grid",
    gridTemplateColumns: "auto 1fr auto",
    gap: 11,
    alignItems: "start",
    padding: "13px 16px",
    borderBottom: `1px solid ${T.border}`,
  }}>
    <div className="sk" style={{ height: 16, width: 50 }} />
    <div>
      <div className="sk" style={{ height: 14, width: "90%", marginBottom: 8 }} />
      <div className="sk" style={{ height: 16, width: 80 }} />
    </div>
    <div className="sk" style={{ height: 14, width: 40 }} />
  </div>
);

/* ─── Main Component ─────────────────────────────────────────────────── */
export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [signals, setSignals] = useState([]);
  const [displayedSignals, setDisplayedSignals] = useState([]);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [currentIndex, setCurrentIndex] = useState(0);

  const fetchSignals = async () => {
    setError(null);
    try {
      const raw = await fetchSignalsFromAPI();
      // Deduplicate by description to avoid backend returning identical signals
      const seen = new Set();
      const unique = raw.filter(s => {
        const key = s.description?.trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      setSignals(unique);
      setDisplayedSignals(unique.slice(0, 5));
      setCurrentIndex(0);
      setLastUpdate(new Date());
    } catch (err) {
      console.error("SignalFeed fetch error:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchSignals();
  }, [refreshTrigger]);

  // Auto-rotate signals every 30 seconds
  useEffect(() => {
    if (signals.length === 0) return;

    const rotateSignals = () => {
      setCurrentIndex(prev => {
        const nextIndex = (prev + 1) % signals.length;
        // Circular slice — wraps around so we always show 5 entries
        const sliced = [];
        for (let i = 0; i < 5; i++) {
          sliced.push(signals[(nextIndex + i) % signals.length]);
        }
        setDisplayedSignals(sliced);
        return nextIndex;
      });
    };

    const interval = setInterval(rotateSignals, 30000); // 30s rotation
    return () => clearInterval(interval);
  }, [signals]);

  // Error state
  if (error && signals.length === 0) {
    return (
      <div className="signal-panel" style={{
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        overflow: "hidden",
        background: T.surface,
      }}>
        <div className="sp-head" style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "13px 16px",
          borderBottom: `1px solid ${T.border}`,
          background: "rgba(255,255,255,0.018)",
        }}>
          <div className="sp-title" style={{
            fontFamily: FONTS.display,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.18em",
            color: T.t2,
            textTransform: "uppercase",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            <span style={{ width: 14, height: 1, background: T.t2 }} />
            Signal Feed
          </div>
        </div>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 200,
          color: T.red,
          fontSize: 12,
          fontFamily: FONTS.mono,
        }}>
          数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
        </div>
      </div>
    );
  }

  return (
    <div className="signal-panel" style={{
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      overflow: "hidden",
      background: T.surface,
      position: "sticky",
      top: 20,
    }}>
      {/* Header */}
      <div className="sp-head" style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "13px 16px",
        borderBottom: `1px solid ${T.border}`,
        background: "rgba(255,255,255,0.018)",
      }}>
        <div className="sp-title" style={{
          fontFamily: FONTS.display,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.2em",
          color: T.t3,
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}>
          <span style={{ width: 14, height: 1, background: T.t3 }} />
          Signal Feed
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            background: "rgba(245,158,11,0.1)",
            color: T.amber,
            border: "1px solid rgba(245,158,11,0.2)",
            fontSize: 7,
            fontWeight: 700,
            letterSpacing: "0.1em",
            padding: "2px 6px",
            borderRadius: 3,
            fontFamily: FONTS.display,
          }}>LIVE</span>
          <div style={{
            width: 4,
            height: 4,
            borderRadius: "50%",
            background: T.green,
          }} />
        </div>
      </div>

      {/* Signal List */}
      <div className="sp-body" style={{
        maxHeight: "calc(100vh - 300px)",
        overflowY: "auto",
        minHeight: 400,
      }}>
        {loading
          ? Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)
          : displayedSignals.map((signal, idx) => (
              <SignalRow
                key={signal.id}
                signal={signal}
                onClick={onSignalClick}
                isNew={idx === 0}
              />
            ))
        }
      </div>

      {/* Legend */}
      <div style={{
        display: "flex",
        gap: 12,
        padding: "12px 16px",
        borderTop: `1px solid ${T.border}`,
        flexWrap: "wrap",
      }}>
        {Object.entries(SIGNAL_TYPES).map(([key, val]) => (
          <div key={key} style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <div style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: val.color,
            }} />
            <span style={{
              fontSize: 8,
              fontFamily: FONTS.mono,
              color: T.t3,
            }}>
              {val.label}
            </span>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes signal-in {
          from { opacity: 0; transform: translateY(-5px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .signal-row.new {
          animation: signal-in 0.35s ease;
        }
      `}</style>
    </div>
  );
}
