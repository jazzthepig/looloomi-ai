// Legacy MCP over SSE (/mcp-sse/sse + /mcp-sse/messages/) → Railway origin. Same gap as functions/mcp: Pages served
// the SPA shell for these paths. The event stream is passed through as-is.
const ORIGIN = 'https://web-production-0cdf76.up.railway.app';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, Accept, Last-Event-ID',
};

export async function onRequest(context) {
  const { request, env } = context;
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  const url = new URL(request.url);
  const base = (env && env.RAILWAY_URL) || ORIGIN;
  const proxied = new Request(base + url.pathname + url.search, {
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
