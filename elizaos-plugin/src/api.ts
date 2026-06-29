/**
 * CometCloud API client
 * Thin fetch wrapper over the public REST API at https://looloomi.ai
 */

import type {
  CISAsset,
  CISUniverseResponse,
  CISReportResponse,
  MacroPulseResponse,
  ExclusionCheckResponse,
} from "./types.js";

const DEFAULT_BASE = "https://looloomi.ai";
const DEFAULT_TIMEOUT_MS = 20_000;

async function apiFetch<T>(
  path: string,
  apiBase: string = DEFAULT_BASE,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${apiBase}${path}`, {
      headers: {
        "Accept": "application/json",
        "User-Agent": "elizaos-plugin-cometcloud/0.1.0",
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`CometCloud API error ${res.status}: ${res.statusText}`);
    }

    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchCISUniverse(
  apiBase?: string,
  timeoutMs?: number
): Promise<CISUniverseResponse> {
  type UniverseRaw = { universe?: CISAsset[]; assets?: CISAsset[] } & Record<string, unknown>;
  const data = await apiFetch<UniverseRaw>(
    "/api/v1/cis/universe",
    apiBase,
    timeoutMs ?? 60_000   // CIS endpoint can be slow on first hit
  );

  // Normalise: API returns `universe` or `assets` depending on version
  const assets = (data.universe ?? data.assets ?? []) as CISAsset[];
  return {
    assets,
    total: assets.length,
    macro_regime: data.macro_regime as string | undefined,
    source: data.source as string | undefined,
    timestamp: data.timestamp as string | undefined,
  };
}

export async function fetchCISReport(
  symbol: string,
  apiBase?: string,
  timeoutMs?: number
): Promise<CISReportResponse> {
  return apiFetch<CISReportResponse>(
    `/api/v1/cis/report/${encodeURIComponent(symbol.toUpperCase())}`,
    apiBase,
    timeoutMs
  );
}

export async function fetchMacroPulse(
  apiBase?: string,
  timeoutMs?: number
): Promise<MacroPulseResponse> {
  return apiFetch<MacroPulseResponse>(
    "/api/v1/market/macro-pulse",
    apiBase,
    timeoutMs
  );
}

export async function fetchExclusionCheck(
  symbol: string,
  apiBase?: string,
  timeoutMs?: number
): Promise<ExclusionCheckResponse> {
  // The /cis/exclusions endpoint returns the full list — we filter client-side
  const data = await apiFetch<{ exclusions?: ExclusionRecord[] }>(
    "/api/v1/cis/exclusions",
    apiBase,
    timeoutMs
  );

  const list: ExclusionRecord[] = data.exclusions ?? [];
  const found = list.find(
    (e) => e.symbol?.toUpperCase() === symbol.toUpperCase()
  );

  return {
    symbol: symbol.toUpperCase(),
    is_excluded: !!found,
    reason:   found?.reason,
    category: found?.category,
  };
}

interface ExclusionRecord {
  symbol?: string;
  reason?: string;
  category?: string;
}

export async function fetchCISLeaderboard(
  limit = 10,
  apiBase?: string,
  timeoutMs?: number
): Promise<CISAsset[]> {
  const universe = await fetchCISUniverse(apiBase, timeoutMs);
  return universe.assets
    .sort((a, b) => (b.cis_score ?? 0) - (a.cis_score ?? 0))
    .slice(0, limit);
}
