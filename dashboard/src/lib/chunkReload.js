/**
 * Stale-chunk recovery (2026-10-28).
 *
 * Every deploy renames the lazy chunks (content hashes) and the host drops the old ones. A tab opened
 * before the deploy still runs the old entry, asks for an old chunk, gets the SPA fallback page instead
 * of JavaScript, and the section dies with "Failed to fetch dynamically imported module". Seen live on
 * the CIS v2 panel after a routine push.
 *
 * Vite fires `vite:preloadError` for exactly this. Reload once to pick up the new entry; a session flag
 * (time-boxed) stops a reload loop if the chunk is missing for some other reason.
 */
const KEY = "cc_chunk_reload_at";

export function isChunkLoadError(err) {
  const m = String((err && (err.message || err)) || "");
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError/i.test(m);
}

export function reloadOnceForNewBuild() {
  try {
    const last = Number(sessionStorage.getItem(KEY) || 0);
    if (Date.now() - last < 60_000) return false;      // already tried in the last minute — don't loop
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    // storage blocked: still reload once per page life
    if (window.__ccChunkReloaded) return false;
    window.__ccChunkReloaded = true;
  }
  window.location.reload();
  return true;
}

if (typeof window !== "undefined") {
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadOnceForNewBuild()) event.preventDefault();
  });
}
