// MCP (Streamable HTTP) → Railway origin. 11-07: looloomi.ai is Cloudflare Pages and only /api/* and /internal/*
// had a proxy, so the endpoint we advertise (llms.txt, .well-known/agent.json, `claude mcp add … https://looloomi.ai/mcp`)
// answered GET with the SPA shell and POST with 405 — no external agent could ever connect, which is why
// agent_call_log has 0 rows since launch (it was never the logging pipeline).
// The origin mounts the MCP app at /mcp/ (trailing slash; POST /mcp without it is 405 on the origin too),
// so the bare /mcp is rewritten to /mcp/. Responses are streamed through untouched (text/event-stream).
const ORIGIN = 'https://web-production-0cdf76.up.railway.app';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, Accept, Mcp-Session-Id, Mcp-Protocol-Version, Last-Event-ID',
  'Access-Control-Expose-Headers': 'Mcp-Session-Id',
};

export function originPath(pathname) {
  return pathname === '/mcp' ? '/mcp/' : pathname;
}

export async function onRequest(context) {
  const { request, env } = context;
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  const url = new URL(request.url);
  const base = (env && env.RAILWAY_URL) || ORIGIN;
  const target = base + originPath(url.pathname) + url.search;
  const proxied = new Request(target, {
    method: request.method,
    headers: request.headers,
    body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
    redirect: 'manual',
  });
  try {
    const response = await fetch(proxied);
    const headers = new Headers(response.headers);
    Object.entries(CORS_HEADERS).forEach(([k, v]) => headers.set(k, v));
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'MCP proxy error', detail: err.message }), {
      status: 502,
      headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
    });
  }
}
