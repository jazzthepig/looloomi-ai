import type { Action, IAgentRuntime, Memory, State, HandlerCallback } from "@elizaos/core";
import { fetchMacroPulse } from "../api.js";

function fmt(n: number | undefined, decimals = 1): string {
  return n != null ? n.toFixed(decimals) : "—";
}

function fmtLargeUsd(n: number | undefined): string {
  if (n == null) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toFixed(0)}`;
}

function fmtBtcPrice(n: number | undefined): string {
  if (n == null) return "—";
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export const getMacroPulseAction: Action = {
  name: "GET_MACRO_PULSE",
  similes: [
    "MACRO_PULSE",
    "MACRO_DATA",
    "MARKET_OVERVIEW",
    "CRYPTO_MARKET",
    "FEAR_GREED",
    "BTC_DOMINANCE",
    "MARKET_CONDITIONS",
    "MACRO_REGIME",
    "CURRENT_REGIME",
  ],
  description:
    "Fetch the CometCloud Macro Pulse — current crypto market conditions including Fear & Greed index, " +
    "BTC dominance, total market cap, DeFi TVL, and the current macro regime " +
    "(RISK_ON, RISK_OFF, TIGHTENING, EASING, STAGFLATION, or GOLDILOCKS). " +
    "Use when the user asks about overall market conditions, sentiment, or the current crypto environment.",

  validate: async (_runtime: IAgentRuntime, message: Memory): Promise<boolean> => {
    const text = message.content.text?.toLowerCase() ?? "";
    return /\b(macro|market|sentiment|fear|greed|btc dominance|regime|conditions|overview|pulse|tvl)\b/.test(text);
  },

  handler: async (
    runtime: IAgentRuntime,
    _message: Memory,
    _state: State | undefined,
    _options: Record<string, unknown>,
    callback: HandlerCallback
  ): Promise<boolean> => {
    const apiBase = (runtime.getSetting("COMETCLOUD_API_BASE") as string | undefined) ?? "https://looloomi.ai";

    try {
      const pulse = await fetchMacroPulse(apiBase);

      const fngBar = pulse.fear_greed_index != null
        ? buildFngBar(pulse.fear_greed_index)
        : "";

      const responseText = [
        `## CometCloud Macro Pulse`,
        ``,
        `**Macro Regime:** ${pulse.macro_regime ?? "Unknown"}`,
        `**Fear & Greed:** ${fmt(pulse.fear_greed_index, 0)} / 100 — ${pulse.fear_greed_label ?? "—"}${fngBar ? `  ${fngBar}` : ""}`,
        `**BTC Price:** ${fmtBtcPrice(pulse.btc_price)}`,
        `**BTC Dominance:** ${fmt(pulse.btc_dominance, 1)}%`,
        `**Total Market Cap:** ${fmtLargeUsd(pulse.total_market_cap)}`,
        pulse.defi_tvl ? `**DeFi TVL:** ${fmtLargeUsd(pulse.defi_tvl)}` : "",
        ``,
        `*Regimes: RISK_ON · RISK_OFF · TIGHTENING · EASING · STAGFLATION · GOLDILOCKS*`,
        `*Data sourced from CoinGecko, Alternative.me, and DeFiLlama via CometCloud.*`,
      ]
        .filter((l) => l !== "")
        .join("\n");

      await callback({ text: responseText });
      return true;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      await callback({ text: `Could not fetch macro pulse: ${msg}` });
      return false;
    }
  },

  examples: [
    [
      { user: "{{user1}}", content: { text: "What's the current macro regime?" } },
      { user: "{{agent}}", content: { text: "Checking CometCloud macro pulse...", action: "GET_MACRO_PULSE" } },
    ],
    [
      { user: "{{user1}}", content: { text: "How's the market sentiment right now?" } },
      { user: "{{agent}}", content: { text: "Fetching market conditions from CometCloud...", action: "GET_MACRO_PULSE" } },
    ],
    [
      { user: "{{user1}}", content: { text: "Show me fear and greed index" } },
      { user: "{{agent}}", content: { text: "Loading current Fear & Greed data...", action: "GET_MACRO_PULSE" } },
    ],
  ],
};

function buildFngBar(value: number): string {
  // Simple ASCII bar 0-100 → 10 segments
  const filled = Math.round(value / 10);
  return "[" + "█".repeat(filled) + "░".repeat(10 - filled) + "]";
}
