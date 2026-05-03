import type { Action, IAgentRuntime, Memory, State, HandlerCallback } from "@elizaos/core";
import { fetchCISReport } from "../api.js";
import { GRADE_DESCRIPTIONS } from "../types.js";

export const getCisScoreAction: Action = {
  name: "GET_CIS_SCORE",
  similes: [
    "CIS_SCORE",
    "CRYPTO_RATING",
    "ASSET_SCORE",
    "GET_RATING",
    "SCORE_ASSET",
    "RATE_CRYPTO",
    "COMETCLOUD_SCORE",
    "CIS_REPORT",
  ],
  description:
    "Fetch the CometCloud CIS (Crypto Intelligence Score) for a specific crypto asset. " +
    "Returns the composite score (0–100), letter grade (A+→F), 5-pillar breakdown " +
    "(Fundamental, Momentum, On-chain, Sentiment, Alpha), positioning signal, and " +
    "Liquidity-Adjusted Score (LAS). CIS is a Morningstar-style institutional rating system.",

  validate: async (_runtime: IAgentRuntime, message: Memory): Promise<boolean> => {
    const text = message.content.text?.toLowerCase() ?? "";
    // Match if message mentions a score/rating request AND a known ticker pattern
    const hasScoreIntent = /\b(cis|score|rating|grade|rate|assess|analyse|analyze)\b/.test(text);
    const hasTicker = /\b[A-Z]{2,8}\b/.test(message.content.text ?? "");
    return hasScoreIntent && hasTicker;
  },

  handler: async (
    runtime: IAgentRuntime,
    message: Memory,
    _state: State | undefined,
    _options: Record<string, unknown>,
    callback: HandlerCallback
  ): Promise<boolean> => {
    const apiBase = (runtime.getSetting("COMETCLOUD_API_BASE") as string | undefined) ?? "https://looloomi.ai";
    const text    = message.content.text ?? "";

    // Extract ticker — greedy match on uppercase 2–8 chars that look like symbols
    const knownTickers = text.match(/\b([A-Z]{2,8})\b/g) ?? [];
    // Prefer known-sounding crypto symbols (skip "I", "A", "ETH" in "Ethereum" etc.)
    const commonWords = new Set(["IS", "FOR", "GET", "THE", "CIS", "ME", "AND", "OR", "IN", "ON", "AT", "TO"]);
    const candidates  = knownTickers.filter((t) => !commonWords.has(t));
    const symbol = candidates[0];

    if (!symbol) {
      await callback({ text: "I need a ticker symbol to look up the CIS score. For example: 'Get CIS score for BTC' or 'Rate ETH'" });
      return false;
    }

    try {
      const report = await fetchCISReport(symbol, apiBase);

      const pillarsText = report.pillars
        ? Object.entries(report.pillars)
            .map(([k, v]) => `**${k}** ${Math.round(v as number)}`)
            .join("  |  ")
        : "N/A";

      const gradeDesc = GRADE_DESCRIPTIONS[report.grade] ?? "";
      const las = report.las != null ? `  ·  LAS ${report.las.toFixed(1)}` : "";

      const responseText = [
        `## CometCloud CIS — ${report.symbol}${report.name ? ` (${report.name})` : ""}`,
        ``,
        `**Score:** ${report.cis_score.toFixed(1)} / 100   **Grade:** ${report.grade} ${gradeDesc}`,
        `**Signal:** ${report.signal}${las}`,
        report.macro_regime ? `**Regime:** ${report.macro_regime}` : "",
        ``,
        `### Pillar Breakdown`,
        pillarsText,
        ``,
        `*F = Fundamental  ·  M = Momentum  ·  O = On-chain  ·  S = Sentiment  ·  A = Alpha*`,
        ``,
        `*This rating is for informational purposes only and does not constitute investment advice.*`,
      ]
        .filter((l) => l !== "")
        .join("\n");

      await callback({ text: responseText });
      return true;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      await callback({
        text: `Could not fetch CIS score for ${symbol}: ${msg}. Check if the asset is in the CometCloud universe at https://looloomi.ai`,
      });
      return false;
    }
  },

  examples: [
    [
      { user: "{{user1}}", content: { text: "Get the CIS score for ETH" } },
      { user: "{{agent}}", content: { text: "Fetching CometCloud CIS score for ETH...", action: "GET_CIS_SCORE" } },
    ],
    [
      { user: "{{user1}}", content: { text: "What is BTC's rating?" } },
      { user: "{{agent}}", content: { text: "Looking up CIS rating for BTC...", action: "GET_CIS_SCORE" } },
    ],
    [
      { user: "{{user1}}", content: { text: "Rate SOL using CometCloud" } },
      { user: "{{agent}}", content: { text: "Retrieving CometCloud CIS for SOL...", action: "GET_CIS_SCORE" } },
    ],
  ],
};
