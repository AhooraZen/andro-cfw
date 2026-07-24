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
- احراز هویت امن — با OAuth رسمی Cloudflare (wrangler login)، رمز عبور شما هرگز به این کتابخانه ارسال یا در اختیار آن قرار نمی‌گیرد
- **سشن رمزنگاری‌شده** — فایل `cfw.session` با Fernet (AES-128 + HMAC) رمز میشه، کلید جدا توی `~/.andro_cfw/key`
- **پشتیبانی چند لایبری** — telebot، python-telegram-bot، aiogram
- **بدون monkey-patch** — فقط URL رو جایگزین می‌کنی، بقیه کد ع باقی می‌مونه

---

## 📦 نصب

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

**پیش‌نیاز:** [Node.js](https://nodejs.org) — فقط موقع `andro-cfw init` لازمه (برای اجرای `wrangler` CLI). بعدش تو سرور فقط پایتون کافیه.

---

## 🚀 راه‌اندازی (یک بار)

```bash
cd your-bot-project/
andro-cfw init
```

این دستور:
1. مرورگرت رو باز می‌کنه → توی Cloudflare لاگین می‌کنی (OAuth)
2. یه Worker خودکار می‌سازه و deploy می‌کنه
3. فایل `cfw.session` رو رمزنگاری‌شده توی همون مسیر می‌سازه

---

## 🐍 استفاده با pyTelegramBotAPI (telebot)

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

## 🐍 استفاده با python-telegram-bot (v20+)

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

## 🐍 استفاده با aiogram (v3+)

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

---

## 📋 دستورات CLI

| دستور | توضیح |
|-------|-------|
| `andro-cfw init` | لاگین کلادفلر + deploy ورکر + ساخت سشن |
| `andro-cfw init --name foo` | deploy با اسم دلخواه |
| `andro-cfw init --force` | redeploy و بازنویسی سشن قبلی |
| `andro-cfw status` | نمایش اطلاعات ورکر ذخیره‌شده |
| `andro-cfw remove` | حذف ورکر + حذف `cfw.session` |

---

## 🔐 نکات امنیتی

- **`cfw.session` رمزنگاری شده** — با Fernet (AES-128-CBC + HMAC). کلید توی `~/.andro_cfw/key` هست، نه کنار پروژه.
- **گیت:** اگه اشتباهاً `cfw.session` رو commit کنی، بدون کلید قابل خوندن نیست. ولی **حتماً `cfw.session` رو به `.gitignore` اضافه کن**.
- **ورکر pass-through خالصه** — لاگ نمی‌گیره، توکن ذخیره نمی‌کنه، محتوای ریکوئست رو نمی‌بینه.
- پسورد کلادفلر هرگز به این کتابخانه نمی‌رسه — همه‌چیز از طریق OAuth رسمی Cloudflare انجام می‌شه.
---

## 📋 نیازمندی‌ها

- Python 3.9+
- Node.js (فقط موقع `init` و `remove`)
- [اکانت رایگان Cloudflare](https://dash.cloudflare.com/sign-up)

---

## 📄 لایسنس

MIT
