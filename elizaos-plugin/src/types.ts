// CometCloud API response types

export interface CISAsset {
  symbol: string;
  asset_id?: string;
  name?: string;
  cis_score: number;
  raw_cis_score?: number;
  grade: string;
  signal: string;
  asset_class?: string;
  pillars?: {
    F?: number;
    M?: number;
    O?: number;
    S?: number;
    A?: number;
  };
  las?: number;
  confidence?: number;
  data_tier?: "T1" | "T2";
  macro_regime?: string;
  price_usd?: number;
  change_24h?: number;
}

export interface CISUniverseResponse {
  assets: CISAsset[];
  total: number;
  macro_regime?: string;
  source?: string;
  timestamp?: string;
}

export interface CISReportResponse {
  symbol: string;
  name?: string;
  cis_score: number;
  grade: string;
  signal: string;
  pillars?: Record<string, number>;
  las?: number;
  macro_regime?: string;
  analysis?: string;
  timestamp?: string;
}

export interface MacroPulseResponse {
  fear_greed_index?: number;
  fear_greed_label?: string;
  btc_dominance?: number;
  btc_price?: number;
  total_market_cap?: number;
  macro_regime?: string;
  defi_tvl?: number;
  timestamp?: string;
}

export interface ExclusionCheckResponse {
  symbol: string;
  is_excluded: boolean;
  reason?: string;
  category?: string;
}

export interface CometCloudPluginConfig {
  apiBase?: string;
  timeoutMs?: number;
}

// Grade → readable description
export const GRADE_DESCRIPTIONS: Record<string, string> = {
  "A+": "Exceptional (≥85)",
  "A":  "Strong (75–84)",
  "B+": "Above Average (65–74)",
  "B":  "Average (55–64)",
  "C+": "Below Average (45–54)",
  "C":  "Weak (35–44)",
  "D":  "Poor (25–34)",
  "F":  "Failing (<25)",
};

// Compliance-safe signal labels
export const SIGNAL_LABELS: Record<string, string> = {
  STRONG_OUTPERFORM: "STRONG OUTPERFORM",
  OUTPERFORM:        "OUTPERFORM",
  NEUTRAL:           "NEUTRAL",
  UNDERPERFORM:      "UNDERPERFORM",
  UNDERWEIGHT:       "UNDERWEIGHT",
};
