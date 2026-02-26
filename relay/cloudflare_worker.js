/**
 * Cloudflare Worker — CLOB API Relay for Polymarket
 * 
 * Forwards signed order requests to clob.polymarket.com,
 * bypassing IP-based geo-restrictions.
 * 
 * FREE: 100,000 requests/day on Cloudflare free plan.
 * 
 * Deploy:
 *   1. npm install -g wrangler
 *   2. wrangler login
 *   3. cd relay/
 *   4. wrangler deploy
 * 
 * Then set CLOB_RELAY_URL=https://poly-relay.<your-subdomain>.workers.dev
 */

const TARGET = 'https://clob.polymarket.com';

// Optional: restrict to your bot's IP or a secret token
// Set AUTH_TOKEN in Cloudflare Worker environment variables
// Your bot sends: Authorization: Bearer <token>

export default {
  async fetch(request, env) {
    // ── CORS preflight ──
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
          'Access-Control-Allow-Headers': '*',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    // ── Optional auth check ──
    if (env.AUTH_TOKEN) {
      const authHeader = request.headers.get('Authorization') || '';
      const token = authHeader.replace('Bearer ', '').trim();
      if (token !== env.AUTH_TOKEN) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    }

    // ── Build target URL ──
    const url = new URL(request.url);
    const targetUrl = `${TARGET}${url.pathname}${url.search}`;

    // ── Clone all headers, replace Host ──
    const headers = new Headers(request.headers);
    headers.set('Host', 'clob.polymarket.com');
    headers.delete('Authorization');  // Don't forward our relay auth to Polymarket
    headers.delete('CF-Connecting-IP');
    headers.delete('CF-IPCountry');
    headers.delete('X-Forwarded-For');
    headers.delete('X-Real-IP');

    // ── Forward request ──
    const modifiedRequest = new Request(targetUrl, {
      method: request.method,
      headers: headers,
      body: request.method !== 'GET' ? request.body : undefined,
    });

    try {
      const response = await fetch(modifiedRequest);

      // Clone response and add CORS headers
      const responseHeaders = new Headers(response.headers);
      responseHeaders.set('Access-Control-Allow-Origin', '*');
      responseHeaders.set('X-Relay', 'poly-relay');

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({ error: 'Relay error', detail: err.message }),
        {
          status: 502,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    }
  },
};
