# Per-second live feed (optional)

The public dashboard works without this. Deploying it upgrades the refresh
rate from **5 minutes to 1 second**.

## Why it is needed at all

GitHub Pages is a static CDN. The fastest it can republish is roughly every
5 minutes — GitHub Actions' cron floor — and each republish is a full deploy.
Per-second data from Pages alone is not a configuration problem, it is an
architectural impossibility.

Alpaca's own dashboard achieves per-second updates with an authenticated
WebSocket inside a logged-in session. A public page cannot do that without
shipping a credential to every visitor, and Alpaca keys can **place and cancel
orders**, not merely read state.

This Worker resolves that: it holds the key server-side and exposes only
read-only account state.

```
browser --(every 1s)--> Worker --(at most every 2s)--> Alpaca
```

## Rate limits

Alpaca allows ~200 requests/minute. The Worker caches responses for 2 seconds
at the edge, so upstream load stays around 30 req/min **regardless of how many
people are watching**, while each viewer still sees data at most 2 seconds old.

Cloudflare's free tier allows 100,000 requests/day. One viewer polling every
second through a 6.5-hour session uses about 23,000 — comfortable for the
realistic audience of a resume link.

## Deploy (free, about 5 minutes)

1. Create a free account at <https://dash.cloudflare.com>
2. `npm install -g wrangler && wrangler login`
3. `cd cloudflare && wrangler deploy`
4. Set the secrets (they are prompted for, never written to disk):
   ```
   wrangler secret put ALPACA_API_KEY_ID
   wrangler secret put ALPACA_API_SECRET_KEY
   ```
5. Copy the deployed URL and set it in `docs/dashboard.html`:
   ```js
   const LIVE_PROXY = "https://paper-trading-feed.<subdomain>.workers.dev/feed";
   ```
   Push, and the page switches to 1-second polling automatically.

## Safety properties

- Only `GET /feed` is served; every other method and path is refused.
- Upstream calls are restricted by an **allow-list** (`/v2/account`,
  `/v2/positions`, `/v2/clock`). Order endpoints are unreachable by
  construction, so a leaked Worker URL cannot be used to trade.
- Errors return a generic message rather than upstream detail, so no header or
  key material can leak through an exception path.
- The static `live.json` feed remains published either way, and the page falls
  back to it automatically if the Worker is unreachable.
