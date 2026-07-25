# andro-cfw

[![PyPI](https://img.shields.io/pypi/v/andro-cfw?color=blue)](https://pypi.org/project/andro-cfw/)
[![Python](https://img.shields.io/pypi/pyversions/andro-cfw)](https://pypi.org/project/andro-cfw/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/readme-EN%20%7C%20FA-blue)](README.md)

> **فارسی** | [English](README.en.md)

---

## 🎯 این لایبری چی کار می‌کنه؟

توی کشوری مثل ایران که `api.telegram.org` فیلتر شده، توسعه‌دهنده‌ها برای اجرای ربات‌هاشون یا باید VPN استفاده کنن یا سرور خارجی بگیرن.

**andro-cfw** این مشکل رو با یه ترفند حل می‌کنه: یه Cloudflare Worker به عنوان reverse proxy بین ربات و تلگرام قرار می‌ده:

```
ربات شما (پایتون / JS / PHP)  ←→  Cloudflare Worker (غیرفیلتر)  ←→  api.telegram.org
```

شبکه‌ی Edge کلادفلر از ایران قابل دسترسه، پس ربات شما به Worker وصل میشه و Worker به تلگرام.

---

## ✨ ویژگی‌ها

- 🔒 **بدون نیاز به VPN** — نه روی سیستم شما، نه روی سرور و نه هنگام تنظیم وب‌هوک.
- ☁️ **میزبانی ۱۰۰٪ سرورلس ابری** — اجرای ۲۴ ساعته ربات‌های واقعی مستقیماً رو لبه‌ی کلادفلر (بدون نیاز به روشن بودن لپ‌تاپ یا سرور).
- 🐍 **پتچر تک‌خطی خودکار (`andro_cfw.patch()`)** — شناسایی خودکار لایبری‌ها (telebot, ptb, aiogram, pyrogram, hydrogram).
- 🔀 **لود بالانس چند اکانته** — ادغام سهمیه رایگان چندین اکانت کلادفلر (۱۰۰ هزار درخواست در روز برای هر اکانت) با سوییچ خودکار.
- ⚡ **ساخت کد و وب‌هوک خودکار (`andro-cfw serverless`)** — دپلوی ۱-دستوری ربات‌های سرورلس با پرسش‌وپاسخ هوشمند.
- 🔍 **تست پینگ و سلامت ورکر (`andro-cfw check`)** — بررسی زنده سرعت پاسخ‌دهی (Keep-Alive) و کد وضعیت HTTP ورکرها.
- 🔐 **سشن رمزنگاری‌شده** — فایل `cfw.session` با Fernet (AES-128 + HMAC) رمزنگاری می‌شود.

---

## 📦 نصب و تنظیم راه اندازی

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

### ثبت ایمن دستور در PATH سیستم‌عامل

اگر بعد از نصب، اجرای `andro-cfw` در ترمینال با خطای `command not found` مواجه شد:

```bash
python -m andro_cfw.cli setup-path
```

---

## 📖 راهنمای کامل: اجرای ۱۰۰٪ سرورلس ربات‌های تلگرام روی کلادفلر

شما می‌توانید ربات تلگرام خودتون رو **۱۰۰٪ سرورلس** روی Cloudflare Edge با **آپتایم ۲۴ ساعته**، **تاخیر پاسخ‌دهی ۵ میلی‌ثانیه** و **هزینه صفر** (با استفاده از پلن رایگان ۱۰۰،۰۰۰ درخواست در روز کلادفلر) اجرا کنید.

---

### روش اول: دپلوی ۱-دستوری سرورلس (`andro-cfw serverless`)

در کمتر از ۳۰ ثانیه ربات سرورلس خودتون رو دپلوی کنید:

۱. **دستور دپلوی رو بزنید**:
   ```bash
   andro-cfw serverless
   ```
۲. **توکن ربات** رو از `@BotFather` وارد کنید:
   ```text
   [andro-cfw] Enter your Telegram Bot Token from @BotFather: 7123456789:AAFgX...
   ```
۳. **تمام!** کتابخانه andro-cfw ورکر رو دپلوی کرده و وب‌هوک رو **بدون نیاز به VPN** روی تلگرام ست می‌کنه.

#### دستورات آماده ربات سرورلس:
- `/start` یا `/help` — پیام خوش‌آمدگویی همراه با آمار تاخیر و مشخصات دیتاسنتر.
- `/ping` — پاسخ سریع `pong 🏓 (< 5ms Edge Latency)`.
- `/status` — نمایش وضعیت زنده ورکر کلادفلر.
- `/echo <متن>` — تکرار متن درخواستی.

---

### روش دوم: کد کامل TypeScript / JavaScript برای ورکر اختصاصی

اگر می‌خواهید ربات سرورلس با منطق سفارشی، دکمه‌های شیشه‌ای یا پردازش اختصاصی در JavaScript/TypeScript بنویسید:

#### کد `worker.ts`:

```typescript
export interface Env {
  BOT_TOKEN?: string;
}

const TELEGRAM_ORIGIN = "https://api.telegram.org";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // ۱. پردازش وب‌هوک تلگرام (POST /webhook)
    if (request.method === "POST" && url.pathname.includes("/webhook")) {
      try {
        const token = url.searchParams.get("token") || env.BOT_TOKEN;
        const update = (await request.json()) as any;

        if (update && update.message && update.message.text && token) {
          const chatId = update.message.chat.id;
          const text = update.message.text.trim();

          let replyText = "";

          // منطق دستورات سفارشی ربات
          if (text === "/start") {
            replyText = "👋 سلام! این ربات ۱۰۰٪ سرورلس روی Cloudflare Edge اجرا می‌شه!";
          } else if (text === "/ping") {
            replyText = "🏓 پینگ از ورکر کلادفلر!";
          } else if (text.startsWith("/echo ")) {
            replyText = `📢 متن شما: ${text.slice(6)}`;
          } else {
            replyText = `🤖 پیام شما دریافت شد: "${text}"`;
          }

          // ارسال پاسخ به تلگرام
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
      } catch (err) {
        console.error("Webhook processing error:", err);
      }
      return new Response("OK", { status: 200 });
    }

    // ۲. پروکسی معکوس شفاف برای ربات‌های پایتون/سیستم محلی
    const targetUrl = TELEGRAM_ORIGIN + url.pathname + url.search;
    return fetch(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      // @ts-ignore
      duplex: "half",
    });
  },
};
```

---

### روش سوم: ربات پایتون با پتچر تک‌خطی (`andro_cfw.patch()`)

اگر ترجیح می‌دید رباتتون رو با پایتون (telebot, pyrogram, aiogram, ptb) بنویسید:

```python
import telebot
import andro_cfw

# تنظیم خودکار پروکسی فقط با ۱ خط کد
session = andro_cfw.patch()

bot = telebot.TeleBot("YOUR_BOT_TOKEN_FROM_BOTFATHER")

@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(
        message,
        "🤖 **سلام از پشت فیلتر!**\n\n"
        f"🌐 **آدرس ورکر**: `{session.worker_url}`\n"
        "🔒 **وضعیت**: بدون فیلتر و بدون نیاز به VPN!"
    )

if __name__ == "__main__":
    print(f"🚀 ربات روی پروکسی ورکر روشن شد ({session.worker_url})...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
```

---

### روش چهارم: حالت هدایت وب‌هوک به PHP / هاست شخصی (`FORWARD_WEBHOOK_URL`)

اگر یک ربات PHP یا Node.js روی هاست سی‌پنل یا سرور شخصی خودتون دارید و فیلتر شده:

۱. متغیر زیر رو توی تنظیمات ورکر ست کنید:
   ```toml
   [vars]
   FORWARD_WEBHOOK_URL = "https://your-server.com/my_bot_webhook.php"
   ```
۲. کلادفلر آپدیت‌های تلگرام رو می‌گیره، فیلترینگ رو دور می‌زنه و مستقیماً به هاست PHP شما ارسال می‌کنه!

---

## ⚡ تولید کد آماده پروژه (`andro-cfw snippet`)

```bash
# کد اولیه برای telebot
andro-cfw snippet -f telebot

# ذخیره مستقیم کد آماده توی فایل bot.py برای aiogram / pyrogram / ptb
andro-cfw snippet -f aiogram -o bot.py
andro-cfw snippet -f pyrogram -o bot.py
andro-cfw snippet -f hydrogram -o bot.py
andro-cfw snippet -f ptb -o bot.py
```

---

## 🔍 بررسی زنده سلامت و پینگ ورکرها (`andro-cfw check`)

```bash
andro-cfw check
```

نمونه خروجی:
```
  Worker [0]: account-1
    URL     : https://andro-cfw-12345678.workers.dev
    Status  : HTTP 200 OK (59.1 ms)
    Quota   : [available]
```

---

## 📋 دستورات CLI

| دستور | توضیح |
|-------|-------|
| `andro-cfw init` | لاگین کلادفلر + deploy ورکر + ساخت سشن |
| `andro-cfw init --accounts 2` | ساخت سشن چنداکانته لودبالانس‌شده |
| `andro-cfw serverless` | دپلوی خودکار ربات سرورلس ۲۴ ساعته روی کلادفلر |
| `andro-cfw add-account` | افزودن اکانت جدید کلادفلر به سشن موجود |
| `andro-cfw snippet -f telebot` | ساخت خودکار کد پایتون آماده برای لایبری‌های مختلف |
| `andro-cfw check` | تست پینگ زنده و بررسی سلامت ورکرهای دپلوی شده |
| `andro-cfw status` | نمایش اطلاعات ورکرهای ذخیره‌شده |
| `andro-cfw setup-path` | افزودن ایمن مسیر اجرا به PATH کاربر |
| `andro-cfw remove` | حذف ورکر + حذف `cfw.session` |

---

## 🔐 نکات امنیتی

- **`cfw.session` رمزنگاری شده** — با Fernet (AES-128-CBC + HMAC). کلید توی `~/.andro_cfw/key` هست.
- **گیت:** حتماً `cfw.session` رو به `.gitignore` اضافه کن.

---

## 📄 لایسنس

MIT