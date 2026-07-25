/**
 * andro-cfw Telegram Bot API reverse proxy & serverless webhook engine.
 *
 * Provides dual capabilities:
 * 1. Pass-through Reverse Proxy: Forwards requests unchanged to api.telegram.org.
 * 2. Serverless Webhook Engine: Handles Telegram updates directly at Cloudflare Edge.
 */

export interface Env {
  BOT_TOKEN?: string;
}

const TELEGRAM_ORIGIN = "https://api.telegram.org";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Simple health check
    if (url.pathname === "/" || url.pathname === "") {
      return new Response("andro-cfw proxy & serverless engine is running.", { status: 200 });
    }

    // Serverless Webhook Handler (POST /webhook or /webhook?token=... or /webhook/...token...)
    if (request.method === "POST" && url.pathname.includes("/webhook")) {
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
        if (update && update.message && update.message.text && token) {
          const chatId = update.message.chat.id;
          const text = update.message.text;

          if (text.startsWith("/start") || text.startsWith("/help")) {
            const replyUrl = `${TELEGRAM_ORIGIN}/bot${token}/sendMessage`;
            await fetch(replyUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                chat_id: chatId,
                text: "🤖 *I'm Useless*\n\n⚡ *Response Latency*: `~5 ms` (100% Serverless Edge)\n🌐 *Host*: Cloudflare Worker\n🔒 *Uptime*: 24/7 (No laptop/server required)",
                parse_mode: "Markdown",
              }),
            });
          }
        }
      } catch (err) {
        console.error("Webhook processing error:", err);
      }
      return new Response("OK", { status: 200 });
    }

    // Transparent Pass-through Reverse Proxy
    const targetUrl = TELEGRAM_ORIGIN + url.pathname + url.search;

    const init: RequestInit = {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      // @ts-ignore - required by Cloudflare Workers runtime for streaming bodies
      duplex: "half",
    };

    const upstreamResponse = await fetch(targetUrl, init);

    const responseHeaders = new Headers(upstreamResponse.headers);
    responseHeaders.set("Access-Control-Allow-Origin", "*");

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  },
};
