import type { Action, IAgentRuntime, Memory, State, HandlerCallback } from "@elizaos/core";
import { fetchCISUniverse } from "../api.js";
import type { CISAsset } from "../types.js";

const SIGNAL_EMOJI: Record<string, string> = {
  STRONG_OUTPERFORM: "🟢",
  OUTPERFORM:        "🟢",
  NEUTRAL:           "🟡",
  UNDERPERFORM:      "🔴",
  UNDERWEIGHT:       "🔴",
};

function signalEmoji(signal: string): string {
  const key = signal.replace(/\s+/g, "_").toUpperCase();
  return SIGNAL_EMOJI[key] ?? "⚪";
}

export const getCisUniverseAction: Action = {
  name: "GET_CIS_UNIVERSE",
  similes: [
    "CIS_UNIVERSE",
    "LEADERBOARD",
    "CIS_LEADERBOARD",
    "TOP_ASSETS",
    "BEST_CRYPTO",
    "CRYPTO_RANKINGS",
    "TOP_RATED",
    "ALL_SCORES",
    "UNIVERSE",
  ],
  description:
    "Fetch the full CometCloud CIS universe — all scored crypto assets ranked by Crypto Intelligence Score. " +
    "Returns the top assets with grades, signals, and macro regime. Use this for portfolio screening, " +
    "sector overviews, or when the user wants to see what is highest rated across the CometCloud universe.",

  validate: async (_runtime: IAgentRuntime, message: Memory): Promise<boolean> => {
    const text = message.content.text?.toLowerCase() ?? "";
    return (
      /\b(universe|leaderboard|top|best|highest|ranking|rankings|all scores|overview)\b/.test(text) &&
      /\b(cis|cometcloud|crypto|asset|rating|rated|score)\b/.test(text)
    );
  },

  handler: async (
    runtime: IAgentRuntime,
    _message: Memory,
    _state: State | undefined,
    options: Record<string, unknown>,
    callback: HandlerCallback
  ): Promise<boolean> => {
    const apiBase = (runtime.getSetting("COMETCLOUD_API_BASE") as string | undefined) ?? "https://looloomi.ai";
    const limit   = (options?.limit as number | undefined) ?? 10;

    try {
      const universe = await fetchCISUniverse(apiBase);
      const sorted: CISAsset[] = universe.assets
        .sort((a, b) => (b.cis_score ?? 0) - (a.cis_score ?? 0))
        .slice(0, limit);

      const rows = sorted.map((a, i) => {
        const emoji = signalEmoji(a.signal ?? "");
        const score = (a.cis_score ?? 0).toFixed(1);
        const grade = a.grade ?? "—";
        const sig   = a.signal ?? "—";
        return `${String(i + 1).padStart(2)}. ${emoji} **${a.symbol}**  ${score}  ${grade}  ${sig}`;
      });

      const regime = universe.macro_regime ? `**Macro Regime:** ${universe.macro_regime}  ·  ` : "";
      const source = universe.source === "mac_mini" ? "CIS PRO · LOCAL ENGINE" : "CIS MARKET · ESTIMATED";

      const responseText = [
        `## CometCloud CIS Universe — Top ${sorted.length} Assets`,
        `${regime}**Source:** ${source}  ·  **Total:** ${universe.total} assets`,
        ``,
        rows.join("\n"),
        ``,
        `*Grades: A+≥85 · A≥75 · B+≥65 · B≥55 · C+≥45 · C≥35 · D≥25 · F<25*`,
        `*This ranking is for informational purposes only and does not constitute investment advice.*`,
      ].join("\n");

      await callback({ text: responseText });
      return true;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      await callback({ text: `Could not fetch CIS universe: ${msg}` });
      return false;
    }
  },

  examples: [
    [
      { user: "{{user1}}", content: { text: "Show me the CIS leaderboard" } },
      { user: "{{agent}}", content: { text: "Fetching CometCloud CIS universe rankings...", action: "GET_CIS_UNIVERSE" } },
    ],
    [
      { user: "{{user1}}", content: { text: "What are the top rated crypto assets on CometCloud?" } },
      { user: "{{agent}}", content: { text: "Loading top-rated assets from CometCloud...", action: "GET_CIS_UNIVERSE" } },
    ],
    [
      { user: "{{user1}}", content: { text: "Give me a crypto rankings overview" } },
      { user: "{{agent}}", content: { text: "Retrieving CometCloud asset rankings...", action: "GET_CIS_UNIVERSE" } },
    ],
  ],
};
