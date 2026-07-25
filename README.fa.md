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
- **پتچر تک‌خطی خودکار (`andro_cfw.patch()`)** — شناسایی خودکار لایبری‌ها (telebot, ptb, aiogram, pyrogram, hydrogram)
- **میزبانی ۱۰۰٪ سرورلس (Webhook)** — امکان اجرای ۲۴ ساعته ربات بدون نیاز به روشن بودن لپ‌تاپ یا سرور
- **پشتیبانی انواع لایبری‌ها** — telebot، python-telegram-bot، aiogram، pyrogram، hydrogram
- **ساخت کد آماده پروژه (`andro-cfw snippet`)** — تولید خودکار کد نمونه آماده برای تمام لایبری‌های پایتونی
- **تست پینگ و سلامت ورکر (`andro-cfw check`)** — بررسی زنده سرعت پاسخ‌دهی (Keep-Alive) و کد وضعیت HTTP ورکرها
- **خروجی رنگی زیبا در ترمینال** — گزارش مرحله‌به‌مرحله با رنگ‌های ANSI استاندارد
- **افزودن ایمن مسیر به PATH (`andro-cfw setup-path`)** — ثبت ایمن مسیر اجرا بدون خراب کردن PATH سیستم‌عامل

---

## 📦 نصب و تنظیم راه اندازی

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

### ثبت ایمن دستور در PATH سیستم‌عامل

اگر بعد از نصب، اجرای `andro-cfw` در ترمینال با خطای `command not found` مواجه شد، با اجرای دستور زیر مسیر اجرایی پکیج رو به صورت ایمن به PATH اضافه کنید:

```bash
python -m andro_cfw.cli setup-path
```
- **در ویندوز**: مسیر `Scripts\` پایتون رو در `HKCU\Environment\PATH` ریجستری اضافه می‌کنه بدون اینکه PATH فعلی سیستم پاک یا خراب بشه.
- **در لینوکس / مک**: مسیر `~/.local/bin` یا venv رو به `.zshrc` / `.bashrc` اضافه می‌کنه.

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

## ⚡ اجرای ۱۰۰٪ سرورلس رو کلادفلر (بدون نیاز به سرور یا لپ‌تاپ)

ورکر دپلوی شده توسط andro-cfw علاوه بر پروکسی، دارای **موتور سرورلس ابری (Webhook)** هست و می‌تونه ربات شما رو **۲۴ ساعته کاملاً رایگان** روی لبه‌ی کلادفلر اجرا کنه:

### مراحل فعال‌سازی حالت ۱۰۰٪ سرورلس:

۱. **ثبت توکن ربات روی ورکر**:
   متغیر `BOT_TOKEN` رو توی فایل `wrangler.toml` ورکر یا پنل کلادفلر ست کنید:
   ```toml
   [vars]
   BOT_TOKEN = "YOUR_BOT_TOKEN_FROM_BOTFATHER"
   ```

۲. **ست کردن وب‌هوک در تلگرام**:
   لینک زیر رو توی مرورگر یا ترمینال باز کنید:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<YOUR_WORKER_URL>/webhook"
   ```

۳. **تمام!**:
   از این به بعد هر پیامی که به ربات ارسال بشه، تلگرام مستقیماً به ورکر کلادفلر ارسال می‌کنه و کلادفلر در کمتر از **۵ میلی‌ثانیه** پاسخ رو میده — حتی اگه سیستم شما کاملاً خاموش باشه!

---

## 🐍 استفاده با پتچر تک‌خطی (`andro_cfw.patch()`)

```python
import telebot
import andro_cfw

# تنظیم خودکار پروکسی فقط با ۱ خط کد
andro_cfw.patch()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "سلام! این ربات از پشت فیلتر کار می‌کنه! 🎉")

bot.infinity_polling()
```

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