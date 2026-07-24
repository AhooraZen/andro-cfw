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
بات پایتون شما  ←→  Cloudflare Worker (غیرفیلتر)  ←→  api.telegram.org
```

شبکه‌ی Edge کلادفلر از ایران قابل دسترسه، پس ربات شما به Worker وصل میشه و Worker به تلگرام. به همین سادگی.

---

## ✨ ویژگی‌ها

- **بدون VPN** — نه روی سیستم توسعه، نه روی سرور
- **ورکر مال خودته** — روی اکانت Cloudflare خودت deploy میشه، کنترل کامل داری
- **احراز هویت امن** — با OAuth رسمی Cloudflare (`wrangler login`)، رمز عبور شما هرگز به این کتابخانه ارسال نمی‌شود
- **سشن رمزنگاری‌شده** — فایل `cfw.session` با Fernet (AES-128 + HMAC) رمز میشه، کلید جدا توی `~/.andro_cfw/key`
- **پشتیبانی انواع لایبری‌ها** — telebot، python-telegram-bot، aiogram، pyrogram، hydrogram
- **بدون monkey-patch** — فقط URL رو جایگزین می‌کنی، بقیه کد ع باقی می‌مونه
- **ساخت کد آماده پروژه (`andro-cfw snippet`)** — تولید خودکار کد نمونه آماده برای تمام لایبری‌های پایتونی
- **تست پینگ و سلامت ورکر (`andro-cfw check`)** — بررسی زنده سرعت پاسخ‌دهی و کد وضعیت HTTP ورکرها
- **خروجی رنگی زیبا در ترمینال** — گزارش مرحله‌به‌مرحله با رنگ‌های ANSI استاندارد
- **افزودن ایمن مسیر به PATH (`andro-cfw setup-path`)** — ثبت ایمن مسیر اجرا بدون خراب کردن PATH سیستم‌عامل

---

## 📦 نصب

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

---

## 🚀 راه‌اندازی (یک بار)

```bash
cd your-bot-project/
andro-cfw init
```

این دستور:
1. محیط Node.js و Wrangler رو بررسی می‌کنه (اگه نصب نباشه خودکار نصب می‌کنه).
2. مرورگرت رو باز می‌کنه → توی Cloudflare لاگین می‌کنی (OAuth).
3. یه Worker خودکار می‌سازه و deploy می‌کنه.
4. فایل `cfw.session` رو رمزنگاری‌شده توی همون مسیر می‌سازه.

---

## ⚡ تولید کد آماده پروژه (`andro-cfw snippet`)

دیگه نیازی نیست کد نمونه رو کپی کنی! با این دستور کد اولیه آماده‌ی بوت‌سترپ رو دریافت یا ذخیره کن:

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

برای تست سرعت اتصال و بررسی وضعیت ورکرهای دپلوی شده:

```bash
andro-cfw check
```

نمونه خروجی:
```
  Worker [0]: account-1
    URL     : https://andro-cfw-12345678.workers.dev
    Status  : HTTP 200 OK (45.2 ms)
    Quota   : [available]
```

---

## 🐍 نمونه کدهای استفاده

### استفاده با pyTelegramBotAPI (telebot)

```python
import telebot
from andro_cfw import CFWSession

session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
telebot.apihelper.FILE_URL = session.telebot_file_url()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "سلام! این ربات از پشت فیلتر کار می‌کنه! 🎉")

bot.infinity_polling()
```

### استفاده با python-telegram-bot (v20+)

```python
from telegram.ext import ApplicationBuilder, CommandHandler
from andro_cfw import CFWSession

session = CFWSession.load()

app = (
    ApplicationBuilder()
    .token("YOUR_BOT_TOKEN")
    .base_url(session.ptb_base_url())
    .base_file_url(session.ptb_base_file_url())
    .build()
)

async def start(update, context):
    await update.message.reply_text("سلام! این ربات از پشت فیلتر کار می‌کنه! 🎉")

app.add_handler(CommandHandler("start", start))
app.run_polling()
```

### استفاده با aiogram (v3+)

```python
from aiogram import Bot
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.session.aiohttp import AiohttpSession
from andro_cfw import CFWSession

session = CFWSession.load()
api_server = TelegramAPIServer(**session.aiogram_server_url())

bot = Bot(
    token="YOUR_BOT_TOKEN",
    session=AiohttpSession(api=api_server),
)
```

### استفاده با Pyrogram / Hydrogram

```python
from pyrogram import Client
from andro_cfw import CFWSession

session = CFWSession.load()
app = Client("my_bot", bot_token="YOUR_BOT_TOKEN", api_id=12345, api_hash="HASH")
app.api_url = session.api_base_url()
```

---

## 📋 دستورات CLI

| دستور | توضیح |
|-------|-------|
| `andro-cfw init` | لاگین کلادفلر + deploy ورکر + ساخت سشن |
| `andro-cfw init --accounts 2` | ساخت سشن چنداکانته لودبالانس‌شده |
| `andro-cfw snippet -f telebot` | ساخت خودکار کد پایتون آماده برای لایبری‌های مختلف |
| `andro-cfw check` | تست پینگ زنده و بررسی سلامت ورکرهای دپلوی شده |
| `andro-cfw status` | نمایش اطلاعات ورکرهای ذخیره‌شده |
| `andro-cfw setup-path` | افزودن ایمن مسیر اجرا به PATH کاربر |
| `andro-cfw remove` | حذف ورکر + حذف `cfw.session` |

---

## 🔐 نکات امنیتی

- **`cfw.session` رمزنگاری شده** — با Fernet (AES-128-CBC + HMAC). کلید توی `~/.andro_cfw/key` هست.
- **گیت:** حتماً `cfw.session` رو به `.gitignore` اضافه کن.
- **ورکر pass-through خالصه** — لاگ نمی‌گیره، توکن ذخیره نمی‌کنه، محتوای ریکوئست رو نمی‌بینه.

---

## 📄 لایسنس

MIT