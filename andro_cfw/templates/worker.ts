/**
 * andro-cfw Telegram Bot API reverse proxy & serverless webhook engine.
 *
 * Provides dual capabilities:
 * 1. Pass-through Reverse Proxy: Forwards requests unchanged to api.telegram.org.
 * 2. Serverless Webhook Engine: Handles Telegram updates directly at Cloudflare Edge.
 */

export interface Env {
  BOT_TOKEN?: string;
  SECRET_TOKEN?: string;
  FORWARD_WEBHOOK_URL?: string;
}

const TELEGRAM_ORIGIN = "https://api.telegram.org";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS, PUT, DELETE",
  "Access-Control-Allow-Headers": "*",
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // 1. Handle CORS preflight OPTIONS requests
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: CORS_HEADERS,
      });
    }

    // 2. Health check endpoint
    if (url.pathname === "/" || url.pathname === "") {
      return new Response("andro-cfw proxy & serverless engine is running.", {
        status: 200,
        headers: { "Content-Type": "text/plain", ...CORS_HEADERS },
      });
    }

    // 3. Serverless Webhook Handler (POST /webhook, /webhook?token=..., /webhook/:token)
    if (request.method === "POST" && url.pathname.includes("/webhook")) {
      // Optional Secret Token verification if configured
      if (env.SECRET_TOKEN) {
        const receivedSecret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
        if (receivedSecret !== env.SECRET_TOKEN) {
          return new Response("Unauthorized", { status: 401 });
        }
      }

      try {
        let token = url.searchParams.get("token") || env.BOT_TOKEN;
        if (!token) {
          const parts = url.pathname.split("/").filter(Boolean);
          const idx = parts.indexOf("webhook");
          if (idx !== -1 && parts.length > idx + 1) {
            token = parts[idx + 1];
          }
        }

        const update = (await request.json()) as any;

        // If a custom downstream webhook backend URL is configured, forward the update payload to it
        if (env.FORWARD_WEBHOOK_URL) {
          await fetch(env.FORWARD_WEBHOOK_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(update),
          });
        }

        if (update && update.message && update.message.text && token) {
          const chatId = update.message.chat.id;
          const text = update.message.text.trim();

          let replyText: string | null = null;

          if (text.startsWith("/start") || text.startsWith("/help")) {
            replyText =
              "🤖 *I'm Useless*\n\n" +
              "⚡ *Response Latency*: `~5 ms` (100% Serverless Edge)\n" +
              "🌐 *Host*: Cloudflare Worker\n" +
              "🔒 *Uptime*: 24/7 (No laptop/server required)";
          } else if (text.startsWith("/ping")) {
            replyText = "🏓 *Pong!* (Cloudflare Edge Latency: `< 5ms`)";
          } else if (text.startsWith("/status")) {
            replyText = "🟢 *Worker Status*: Healthy & Active\n🌐 *Region*: Cloudflare Anycast POP";
          } else if (text.startsWith("/echo ")) {
            replyText = `📢 ${text.slice(6)}`;
          }

          if (replyText) {
            const replyUrl = `${TELEGRAM_ORIGIN}/bot${token}/sendMessage`;
            await fetch(replyUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                chat_id: chatId,
                text: replyText,
                parse_mode: "Markdown",
              }),
            });
          }
        }
      } catch (err) {
        console.error("Webhook processing error:", err);
      }
      return new Response("OK", { status: 200, headers: CORS_HEADERS });
    }

    // 4. Transparent Pass-through Reverse Proxy
    const targetUrl = TELEGRAM_ORIGIN + url.pathname + url.search;

    const init: RequestInit = {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      // @ts-ignore - required by Cloudflare Workers runtime for streaming bodies
      duplex: "half",
    };

    try {
      const upstreamResponse = await fetch(targetUrl, init);

      const responseHeaders = new Headers(upstreamResponse.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      responseHeaders.set("X-Content-Type-Options", "nosniff");

      return new Response(upstreamResponse.body, {
        status: upstreamResponse.status,
        statusText: upstreamResponse.statusText,
        headers: responseHeaders,
      });
    } catch (proxyErr) {
      console.error("Proxy error:", proxyErr);
      return new Response(JSON.stringify({ ok: false, error_code: 502, description: "Bad Gateway via andro-cfw proxy" }), {
        status: 502,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      });
    }
  },
};
