import type { Action, IAgentRuntime, Memory, State, HandlerCallback } from "@elizaos/core";
import { fetchExclusionCheck } from "../api.js";

export const checkExclusionAction: Action = {
  name: "CHECK_EXCLUSION",
  similes: [
    "EXCLUSION_CHECK",
    "IS_EXCLUDED",
    "CHECK_BLACKLIST",
    "EXCLUSION_LIST",
    "CIS_EXCLUSION",
    "SCREEN_ASSET",
    "IS_ELIGIBLE",
    "CIS_ELIGIBLE",
    "INCLUSION_CHECK",
  ],
  description:
    "Check whether a crypto asset is on the CometCloud CIS exclusion list. " +
    "The CIS exclusion list screens out assets that fail institutional standards: meme coins, " +
    "high-risk gaming tokens, regulatory violations, insufficient liquidity, or other §4 criteria. " +
    "Excluded assets are not eligible for CIS scoring or Fund-of-Funds allocation. " +
    "Use this before making any allocation decision — a clean exclusion check is required.",

  validate: async (_runtime: IAgentRuntime, message: Memory): Promise<boolean> => {
    const text = message.content.text?.toLowerCase() ?? "";
    const hasExclusionIntent = /\b(exclud|blacklist|eligible|inclusion|screen|banned|block|delist)\b/.test(text);
    const hasTicker = /\b[A-Z]{2,8}\b/.test(message.content.text ?? "");
    return hasExclusionIntent && hasTicker;
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

    // Extract ticker symbol
    const knownTickers = text.match(/\b([A-Z]{2,8})\b/g) ?? [];
    const commonWords  = new Set(["IS", "FOR", "GET", "THE", "CIS", "ME", "AND", "OR", "IN", "ON", "AT", "TO", "CHECK"]);
    const candidates   = knownTickers.filter((t) => !commonWords.has(t));
    const symbol       = candidates[0];

    if (!symbol) {
      await callback({ text: "I need a ticker symbol to check exclusion status. For example: 'Is PEPE excluded?' or 'Check exclusion for WIF'" });
      return false;
    }

    try {
      const result = await fetchExclusionCheck(symbol, apiBase);

      let responseText: string;
      if (result.is_excluded) {
        responseText = [
          `## CometCloud Exclusion Check — ${result.symbol}`,
          ``,
          `⛔ **${result.symbol} is EXCLUDED** from the CometCloud CIS universe.`,
          ``,
          result.reason   ? `**Reason:** ${result.reason}` : "",
          result.category ? `**Category:** ${result.category}` : "",
          ``,
          `Excluded assets are not eligible for CIS scoring or Fund-of-Funds allocation under CometCloud §4 criteria.`,
        ]
          .filter((l) => l !== "")
          .join("\n");
      } else {
        responseText = [
          `## CometCloud Exclusion Check — ${result.symbol}`,
          ``,
          `✅ **${result.symbol} is NOT excluded** from the CometCloud CIS universe.`,
          ``,
          `This asset passes CometCloud §4 inclusion criteria and is eligible for CIS scoring.`,
          `Use GET_CIS_SCORE to retrieve its current rating.`,
        ].join("\n");
      }

      await callback({ text: responseText });
      return true;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      await callback({ text: `Could not check exclusion status for ${symbol}: ${msg}` });
      return false;
    }
  },

  examples: [
    [
      { user: "{{user1}}", content: { text: "Is PEPE excluded from CometCloud?" } },
      { user: "{{agent}}", content: { text: "Checking CometCloud exclusion list for PEPE...", action: "CHECK_EXCLUSION" } },
    ],
    [
      { user: "{{user1}}", content: { text: "Check if WIF is eligible for CIS scoring" } },
      { user: "{{agent}}", content: { text: "Checking CIS eligibility for WIF...", action: "CHECK_EXCLUSION" } },
    ],
    [
      { user: "{{user1}}", content: { text: "Is BTC on the exclusion blacklist?" } },
      { user: "{{agent}}", content: { text: "Checking CometCloud exclusion status for BTC...", action: "CHECK_EXCLUSION" } },
    ],
  ],
};
