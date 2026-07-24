/**
 * andro-cfw Telegram Bot API reverse proxy.
 *
 * Forwards every request unchanged to api.telegram.org, preserving the
 * path (/bot<token>/<method> and /file/bot<token>/<path>), method, headers
 * and body. This lets Telegram bot libraries (telebot, python-telegram-bot,
 * aiogram, ...) talk to Telegram through this worker's URL instead of
 * api.telegram.org directly, which is useful when the Telegram API is
 * blocked at the network level for the developer's location.
 *
 * This worker does not store, log, or inspect bot tokens or message
 * content; it is a transparent pass-through proxy.
 */

export interface Env {}

const TELEGRAM_ORIGIN = "https://api.telegram.org";

export default {
  async fetch(request: Request, _env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Simple health check so users can verify the worker is alive.
    if (url.pathname === "/" || url.pathname === "") {
      return new Response("andro-cfw proxy is running.", { status: 200 });
    }

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
