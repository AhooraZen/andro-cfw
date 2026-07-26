/**
 * andro-cfw Telegram Bot API reverse proxy & serverless webhook relay.
 *
 * Plain ES module, not TypeScript: andro-cfw uploads this file straight to the
 * Cloudflare API, and that path has no bundler or type stripper. Types are
 * documented in JSDoc instead.
 *
 * Two capabilities:
 *   1. Pass-through reverse proxy: forwards every request unchanged to the
 *      Bot API, so a Telegram library in a filtered region can reach it by
 *      pointing at this worker instead.
 *   2. Serverless webhook relay: accepts Telegram updates at POST /webhook,
 *      authenticates them, and forwards them to FORWARD_WEBHOOK_URL.
 *
 * Configuration (all optional, set with `andro-cfw serverless` or the
 * Cloudflare dashboard):
 *   BOT_TOKEN            Bot token, if the deployment needs one server-side.
 *                        NEVER read from the request URL.
 *   WEBHOOK_SECRET       Shared secret Telegram sends back in the
 *                        X-Telegram-Bot-Api-Secret-Token header. When set,
 *                        /webhook rejects any update without a matching value.
 *   FORWARD_WEBHOOK_URL  Your own backend. Updates are POSTed here verbatim.
 *   FORWARD_SERVICE      Service binding to another Worker on the same account,
 *                        used in preference to FORWARD_WEBHOOK_URL. Required
 *                        when the backend is itself a Worker: a plain fetch()
 *                        to a workers.dev hostname is NOT dispatched to that
 *                        Worker, so the update would vanish with no error.
 *   ALLOWED_ORIGINS      Comma-separated browser origins allowed to call this
 *                        worker via CORS, or "*" to allow any. Unset means no
 *                        CORS headers are emitted at all (the safe default:
 *                        Telegram libraries do not need them).
 *   UPSTREAM_API_ORIGIN  Bot API server to proxy to. Defaults to
 *                        https://api.telegram.org. Point it at your own
 *                        `telegram-bot-api` instance to lift Telegram's 50 MB
 *                        upload cap or keep media on your own infrastructure.
 */

const DEFAULT_TELEGRAM_ORIGIN = "https://api.telegram.org";

/**
 * Hop-by-hop headers must not be forwarded to the origin or echoed back to the
 * client; the runtime manages framing itself.
 */
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

/**
 * Resolve the Bot API origin to proxy to.
 *
 * A misconfigured value must not silently become a request to somewhere
 * unexpected, so anything that is not a well-formed http(s) origin falls back
 * to Telegram's own. Any path, query or fragment is dropped -- only the origin
 * is used, since the request's own path is appended to it.
 */
function upstreamOrigin(env) {
  const configured = (env.UPSTREAM_API_ORIGIN || "").trim();
  if (!configured) return DEFAULT_TELEGRAM_ORIGIN;

  try {
    const parsed = new URL(configured);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      console.error(`Ignoring UPSTREAM_API_ORIGIN with unsupported scheme: ${parsed.protocol}`);
      return DEFAULT_TELEGRAM_ORIGIN;
    }
    return parsed.origin;
  } catch {
    console.error("Ignoring malformed UPSTREAM_API_ORIGIN; falling back to api.telegram.org.");
    return DEFAULT_TELEGRAM_ORIGIN;
  }
}

/**
 * Resolve CORS headers for a request. Returns an empty object unless the
 * deployer opted in via ALLOWED_ORIGINS, so by default this worker is not a
 * general-purpose CORS bypass for the Bot API.
 */
function corsHeaders(request, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").trim();
  if (!allowed) return {};

  const origin = request.headers.get("Origin");
  if (!origin) return {};

  const isAllowed =
    allowed === "*" ||
    allowed
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean)
      .includes(origin);

  if (!isAllowed) return {};

  return {
    "Access-Control-Allow-Origin": allowed === "*" ? "*" : origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

/**
 * Length-independent, timing-safe string comparison. A naive `===` on a secret
 * can leak information about it through response timing.
 */
function secretsMatch(a, b) {
  const encoder = new TextEncoder();
  const left = encoder.encode(a);
  const right = encoder.encode(b);
  let diff = left.length ^ right.length;
  const max = Math.max(left.length, right.length);
  for (let i = 0; i < max; i++) {
    diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  }
  return diff === 0;
}

async function handleWebhook(request, env, cors) {
  // Telegram echoes the secret configured via setWebhook(secret_token=...).
  // Without it, anyone who learns this URL can inject fabricated updates.
  if (env.WEBHOOK_SECRET) {
    const received = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
    if (!secretsMatch(received, env.WEBHOOK_SECRET)) {
      return new Response("Unauthorized", { status: 401, headers: cors });
    }
  }

  const service = env.FORWARD_SERVICE;
  if (!service && !env.FORWARD_WEBHOOK_URL) {
    // Nothing to relay to. Still 200, so Telegram does not retry forever.
    return new Response("OK (no forward target configured)", {
      status: 200,
      headers: { "Content-Type": "text/plain", ...cors },
    });
  }

  let payload;
  try {
    payload = await request.text();
  } catch (err) {
    console.error("Failed to read webhook body:", err);
    return new Response("OK", { status: 200, headers: cors });
  }

  // A service binding calls the target Worker directly, in-network. It is the
  // only reliable way to reach another Worker: fetch()ing its public hostname
  // from here is not guaranteed to enter that Worker at all.
  // A service binding ignores the hostname, but it still shows up in the
  // target Worker's logs, so make it point at something recognisable.
  const target = service
    ? new URL("/", request.url).toString()
    : env.FORWARD_WEBHOOK_URL;
  const send = service ? service.fetch.bind(service) : fetch;

  try {
    const relayed = await send(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    });
    // Log rather than propagate: a non-200 makes Telegram redeliver the same
    // update indefinitely, which amplifies a backend outage into a retry loop.
    // But a silent forward is how a broken relay hides, so record it.
    if (!relayed.ok) {
      console.error(`Forward target answered ${relayed.status}`);
    }
  } catch (err) {
    console.error("Failed to forward update:", err);
  }

  return new Response("OK", { status: 200, headers: cors });
}

async function handleProxy(request, url, origin, cors) {
  const targetUrl = origin + url.pathname + url.search;

  const forwardHeaders = new Headers();
  for (const [key, value] of request.headers) {
    const lowered = key.toLowerCase();
    if (!HOP_BY_HOP.has(lowered) && lowered !== "host") {
      forwardHeaders.set(key, value);
    }
  }

  const init = {
    method: request.method,
    headers: forwardHeaders,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    duplex: "half", // required by the Workers runtime for streaming bodies
  };

  try {
    const upstream = await fetch(targetUrl, init);

    const responseHeaders = new Headers();
    for (const [key, value] of upstream.headers) {
      if (!HOP_BY_HOP.has(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    }
    responseHeaders.set("X-Content-Type-Options", "nosniff");
    for (const [key, value] of Object.entries(cors)) {
      responseHeaders.set(key, value);
    }

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (err) {
    console.error("Proxy error:", err);
    return new Response(
      JSON.stringify({
        ok: false,
        error_code: 502,
        description: "Bad Gateway via andro-cfw proxy",
      }),
      {
        status: 502,
        headers: { "Content-Type": "application/json", ...cors },
      },
    );
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request, env);

    // 1. CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    // 2. Health check, used by `andro-cfw check`
    if (url.pathname === "/" || url.pathname === "") {
      return new Response("andro-cfw proxy is running.", {
        status: 200,
        headers: { "Content-Type": "text/plain", ...cors },
      });
    }

    // 3. Serverless webhook relay. Exact path only -- a substring match would
    //    also swallow proxied Bot API calls such as /bot<token>/setWebhook.
    if (url.pathname === "/webhook") {
      if (request.method !== "POST") {
        return new Response("Method Not Allowed", {
          status: 405,
          headers: { Allow: "POST", ...cors },
        });
      }
      return handleWebhook(request, env, cors);
    }

    // 4. Transparent pass-through reverse proxy
    return handleProxy(request, url, upstreamOrigin(env), cors);
  },
};
