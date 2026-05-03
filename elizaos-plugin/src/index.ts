/**
 * @elizaos-plugins/plugin-cometcloud
 *
 * CometCloud CIS (Crypto Intelligence Score) plugin for ElizaOS.
 *
 * Provides institutional-grade crypto ratings, macro pulse data, and exclusion
 * screening for AI agents operating in DeFi and crypto markets.
 *
 * Actions:
 *   GET_CIS_SCORE     — CIS score + grade + 5-pillar breakdown for any asset
 *   GET_CIS_UNIVERSE  — Full rated universe leaderboard
 *   GET_MACRO_PULSE   — Macro regime + Fear & Greed + BTC dominance + MCap
 *   CHECK_EXCLUSION   — §4 exclusion list screening for any asset
 *
 * Providers:
 *   cisContextProvider — Injects regime + top-5 CIS context into every response
 *
 * Configuration (runtime settings):
 *   COMETCLOUD_API_BASE — Override API base URL (default: https://looloomi.ai)
 *
 * @see https://looloomi.ai
 * @see https://looloomi.ai/llms.txt
 * @see https://looloomi.ai/mcp/sse
 */

import type { Plugin } from "@elizaos/core";

import { getCisScoreAction }    from "./actions/getCisScore.js";
import { getCisUniverseAction } from "./actions/getCisUniverse.js";
import { getMacroPulseAction }  from "./actions/getMacroPulse.js";
import { checkExclusionAction } from "./actions/checkExclusion.js";
import { cisContextProvider }   from "./providers/cisProvider.js";

export * from "./types.js";
export * from "./api.js";

export const cometcloudPlugin: Plugin = {
  name: "plugin-cometcloud",
  description:
    "CometCloud CIS (Crypto Intelligence Score) — Morningstar-style institutional ratings for crypto assets. " +
    "Score, grade, signal, and 5-pillar breakdown (Fundamental, Momentum, On-chain, Sentiment, Alpha) " +
    "for 80+ assets. Includes macro regime, Fear & Greed, and §4 exclusion screening. " +
    "No investment advice — positioning signals only.",
  actions: [
    getCisScoreAction,
    getCisUniverseAction,
    getMacroPulseAction,
    checkExclusionAction,
  ],
  providers: [
    cisContextProvider,
  ],
  evaluators: [],
  services:   [],
};

export default cometcloudPlugin;
