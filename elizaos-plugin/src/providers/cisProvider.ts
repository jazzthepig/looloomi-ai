/**
 * CIS Context Provider
 *
 * Injects current macro regime + top-5 CIS assets into every agent response.
 * This gives the agent ambient awareness of market conditions without requiring
 * an explicit tool call — useful for trading agents, portfolio assistants, etc.
 */

import type { Provider, IAgentRuntime, Memory, State } from "@elizaos/core";
import { fetchCISUniverse, fetchMacroPulse } from "../api.js";

// In-memory cache to avoid hammering the API on every message
let _cache: { text: string; ts: number } | null = null;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

export const cisContextProvider: Provider = {
  get: async (runtime: IAgentRuntime, _message: Memory, _state?: State): Promise<string> => {
    // Return cached context if still fresh
    if (_cache && Date.now() - _cache.ts < CACHE_TTL_MS) {
      return _cache.text;
    }

    const apiBase = (runtime.getSetting("COMETCLOUD_API_BASE") as string | undefined) ?? "https://looloomi.ai";

    try {
      const [universe, pulse] = await Promise.allSettled([
        fetchCISUniverse(apiBase),
        fetchMacroPulse(apiBase),
      ]);

      const lines: string[] = ["## CometCloud Market Intelligence (live context)"];

      // Macro regime
      if (pulse.status === "fulfilled") {
        const p = pulse.value;
        lines.push(
          `**Macro Regime:** ${p.macro_regime ?? "Unknown"}  |  ` +
          `**Fear & Greed:** ${p.fear_greed_index ?? "—"} (${p.fear_greed_label ?? "—"})  |  ` +
          `**BTC Dominance:** ${p.btc_dominance?.toFixed(1) ?? "—"}%`
        );
      }

      // Top 5 assets
      if (universe.status === "fulfilled") {
        const top5 = universe.value.assets
          .sort((a, b) => (b.cis_score ?? 0) - (a.cis_score ?? 0))
          .slice(0, 5);

        lines.push("");
        lines.push("**Top 5 CIS-Rated Assets:**");
        top5.forEach((a, i) => {
          lines.push(
            `${i + 1}. ${a.symbol}  CIS ${(a.cis_score ?? 0).toFixed(1)}  ${a.grade ?? "—"}  ${a.signal ?? "—"}`
          );
        });
        lines.push(`*(${universe.value.total} total assets scored)*`);
      }

      lines.push("");
      lines.push(
        "*CIS = Crypto Intelligence Score. Signals: STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT. " +
        "Not investment advice.*"
      );

      const text = lines.join("\n");
      _cache = { text, ts: Date.now() };
      return text;
    } catch {
      return "CometCloud CIS data temporarily unavailable.";
    }
  },
};
