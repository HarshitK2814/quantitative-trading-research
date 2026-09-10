/**
 * Cloudflare Worker: per-second live feed for the public dashboard.
 *
 * WHY THIS EXISTS
 * ---------------
 * GitHub Pages is a static CDN. The fastest it can republish is roughly every
 * 5 minutes (GitHub Actions' cron floor), and each republish is a full deploy.
 * Per-second data is therefore impossible from Pages alone -- not a
 * configuration problem, an architectural one.
 *
 * This Worker sits between the public page and Alpaca:
 *
 *     browser  --(every 1s)-->  Worker  --(at most every 2s)-->  Alpaca
 *
 * The Alpaca key lives in the Worker's environment, never in the page. The
 * Worker exposes ONLY read-only account state and refuses every method except
 * GET, so a leaked endpoint URL cannot be used to trade.
 *
 * RATE LIMITS -- the reason for the cache
 * ---------------------------------------
 * Alpaca allows ~200 requests/minute. Without caching, ten viewers polling
 * every second would be 600 req/min and would get the account throttled. The
 * 2-second edge cache means upstream load is ~30 req/min REGARDLESS of how
 * many people are watching, while each viewer still sees data at most two
 * seconds old.
 *
 * DEPLOY (free tier, ~5 minutes)
 * ------------------------------
 *   1. Create a free account at https://dash.cloudflare.com
 *   2. npm install -g wrangler && wrangler login
 *   3. cd cloudflare && wrangler deploy
 *   4. wrangler secret put ALPACA_API_KEY_ID
 *      wrangler secret put ALPACA_API_SECRET_KEY
 *   5. Put the resulting https://<name>.<subdomain>.workers.dev/feed URL into
 *      LIVE_PROXY at the top of the <script> block in docs/dashboard.html,
 *      then push. The page switches to 1-second polling automatically.
 *
 * Free tier is 100,000 requests/day. One viewer polling every second for a
 * 6.5-hour session uses ~23,000, so this comfortably serves a handful of
 * simultaneous readers -- which is the realistic audience for a track record
 * linked from a resume.
 */

const ALPACA = "https://paper-api.alpaca.markets";
const STARTING_CAPITAL = 100000;
const CACHE_SECONDS = 2;

/** Only these upstream paths may ever be requested. Allow-list, not deny-list. */
const ALLOWED = ["/v2/account", "/v2/positions", "/v2/clock"];

async function alpacaGet(path, env) {
  if (!ALLOWED.includes(path)) {
    throw new Error(`Refusing non-allow-listed path: ${path}`);
  }
  const r = await fetch(ALPACA + path, {
    headers: {
      "APCA-API-KEY-ID": env.ALPACA_API_KEY_ID,
      "APCA-API-SECRET-KEY": env.ALPACA_API_SECRET_KEY,
      accept: "application/json",
    },
  });
  if (!r.ok) throw new Error(`Alpaca ${path} -> HTTP ${r.status}`);
  return r.json();
}

async function buildFeed(env) {
  const [account, positions, clock] = await Promise.all([
    alpacaGet("/v2/account", env),
    alpacaGet("/v2/positions", env),
    alpacaGet("/v2/clock", env),
  ]);

  const equity = parseFloat(account.equity);
  const lastEquity = parseFloat(account.last_equity);

  // Only fields the page actually renders. Nothing here can place an order,
  // and no credential or PII is echoed back.
  return {
    generated_at: new Date().toISOString(),
    source: "cloudflare-worker",
    paper: true,
    strategy: "H1-momentum-126-21-k5-monthly",
    account: {
      status: account.status,
      equity,
      last_equity: lastEquity,
      cash: parseFloat(account.cash),
      buying_power: parseFloat(account.buying_power),
      day_change: equity - lastEquity,
      day_change_pct: lastEquity ? equity / lastEquity - 1 : 0,
      total_change: equity - STARTING_CAPITAL,
      total_change_pct: equity / STARTING_CAPITAL - 1,
      starting_capital: STARTING_CAPITAL,
    },
    market: {
      is_open: Boolean(clock.is_open),
      next_open: clock.next_open,
      next_close: clock.next_close,
    },
    positions: (positions || []).map((p) => ({
      symbol: p.symbol,
      qty: parseFloat(p.qty),
      avg_entry_price: parseFloat(p.avg_entry_price),
      current_price: parseFloat(p.current_price),
      market_value: parseFloat(p.market_value),
      unrealized_pl: parseFloat(p.unrealized_pl),
      unrealized_plpc: parseFloat(p.unrealized_plpc),
      asset_class: p.asset_class || "us_equity",
    })),
    // Order history and the equity curve stay on the static feed: they change
    // slowly, and there is no reason to re-fetch them once per second.
    orders: [],
    history: {},
    note: "Live slice. Order history and chart series come from the static feed.",
  };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Read-only by construction: anything that is not a GET is refused before
    // credentials are touched.
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, OPTIONS",
          "access-control-max-age": "86400",
        },
      });
    }
    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }
    if (url.pathname !== "/feed") {
      return new Response("Not found", { status: 404 });
    }

    const cache = caches.default;
    // Cache key deliberately ignores the page's cache-busting query string, so
    // every viewer shares one upstream fetch per CACHE_SECONDS window.
    const cacheKey = new Request(new URL("/feed", url.origin).toString(), {
      method: "GET",
    });

    const hit = await cache.match(cacheKey);
    if (hit) return hit;

    let body, status;
    try {
      body = JSON.stringify(await buildFeed(env));
      status = 200;
    } catch (err) {
      // Never leak upstream detail that might include header or key material.
      body = JSON.stringify({ error: "upstream unavailable" });
      status = 503;
    }

    const response = new Response(body, {
      status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
        "cache-control": `public, max-age=${CACHE_SECONDS}`,
      },
    });

    if (status === 200) ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  },
};
