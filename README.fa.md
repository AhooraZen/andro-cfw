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
- **نصب خودکار Node.js** *(جدید در نسخه‌ی 0.2.0)* — andro-cfw سیستم‌عامل/دیستروی شما رو تشخیص می‌ده و در صورت نبود Node.js، خودش نصبش می‌کنه
- **لود بالانس هوشمند چند‌اکانتی** *(جدید در نسخه‌ی 0.2.0)* — چند اکانت رایگان Cloudflare رو با هم ترکیب کن؛ سوییچ آنی و ریست خودکار روزانه

---

## 📦 نصب

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install andro-cfw
```

**دیگه لازم نیست خودت Node.js رو نصب کنی.** دستور `andro-cfw init` فقط یک بار به Node.js/npx نیاز داره (برای اجرای `wrangler` CLI رسمی کلادفلر) — و حالا andro-cfw خودش سیستم‌عاملت رو تشخیص می‌ده و در صورت نبودش، به‌صورت خودکار نصبش می‌کنه:

| سیستم‌عامل              | روش تشخیص                | روش نصب خودکار                                |
|--------------------------|----------------------------|--------------------------------------------------|
| ویندوز                   | `platform.system()`         | اول `winget`، بعد `choco`، بعد `scoop`            |
| macOS                    | `platform.system()`         | `brew install node` (یا MacPorts)                 |
| Debian / Ubuntu          | `/etc/os-release`           | اسکریپت NodeSource، در صورت نیاز `apt-get`        |
| Fedora / RHEL / CentOS   | `/etc/os-release`           | `dnf` / `yum`                                     |
| Arch / Manjaro           | `/etc/os-release`           | `pacman`                                          |
| openSUSE                 | `/etc/os-release`           | `zypper`                                          |
| Alpine                   | `/etc/os-release`           | `apk`                                             |

اگه پکیج‌منیجر پشتیبانی‌شده‌ای پیدا نشه (یا نصب نیاز به رمز `sudo` غیرتعاملی داشته باشه که در دسترس نیست)، andro-cfw به‌جای شکست خوردن ساکت، دستورات نصب دستی دقیق برای همون سیستم رو چاپ می‌کنه. بعد از دیپلوی، ران‌تایم پایتون ربات شما اصلاً به Node.js نیاز نداره.

---

## 🚀 راه‌اندازی (یک بار)

```bash
cd your-bot-project/
andro-cfw init
```

این دستور:
1. سیستم‌عاملت رو تشخیص می‌ده و در صورت نبود، Node.js رو خودش نصب می‌کنه
2. مرورگرت رو باز می‌کنه → توی Cloudflare لاگین می‌کنی (OAuth)
3. یه Worker خودکار می‌سازه و deploy می‌کنه
4. فایل `cfw.session` رو رمزنگاری‌شده توی همون مسیر می‌سازه

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

> کد بالا برای هر سه لایبری، چه سشن تک‌اکانتی باشه چه چند‌اکانتی (پایین‌تر ببینید)، دقیقاً یکسانه — فقط دستور `andro-cfw init` فرق می‌کنه، نه کد ربات.

---

## 🔀 لود بالانس هوشمند چند‌اکانتی (جدید)

پلن رایگان Cloudflare Workers محدود به **۱۰۰ هزار ریکوئست در روز به‌ازای هر اکانت** هست. برای ربات‌های پرترافیک همیشه کافی نیست. andro-cfw می‌تونه ترافیک رو بین **چند اکانت Cloudflare** پخش کنه، هرکدوم با سهمیه‌ی ۱۰۰ هزارتای خودش، و به محض تموم شدن سهمیه‌ی یک اکانت، بدون هیچ دانتایمی و بدون تغییر کد، خودکار سوییچ کنه.

```bash
andro-cfw init --accounts 2
```

این دستور:
1. مرورگر رو **دوبار** باز می‌کنه — یک‌بار به‌ازای هر اکانت. هر بار با یک اکانت Cloudflare **متفاوت** لاگین کن. لاگین هر اکانت توی یه پوشه‌ی جدا (`~/.andro_cfw/accounts/account-N`) ذخیره میشه، پس تداخلی پیش نمیاد.
2. یک Worker به‌ازای هر اکانت دیپلوی می‌کنه.
3. همه رو توی یک `cfw.session` واحد ذخیره می‌کنه.

کد ربات شما **دقیقاً همون قبلیه**:

```python
session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
```

پشت صحنه، وقتی سشن بیش از یک اکانت داشته باشه، `telebot_api_url()` (و معادل‌های `ptb_*`/`aiogram_*`) به یک پروکسی لود‌بالانسر **محلی** اشاره می‌کنن که andro-cfw خودش، همون لحظه‌ی اول استفاده، **داخل همون پروسه‌ی پایتون ربات** بالا میاره. این پروکسی:

- هر ریکوئست رو به Worker اکانت فعال فعلی می‌فرسته،
- به محض دریافت `HTTP 429` یا پیام rate-limit کلادفلر (سیگنال رسمی «سهمیه‌ی روزانه تموم شده»)، **آنی** تشخیص می‌ده،
- همون ریکوئست رو بدون این‌که ربات متوجه خطایی بشه، روی اکانت بعدی retry می‌کنه،
- اکانت تموم‌شده رو تا **نیمه‌شب UTC** بعدی (زمان ریست روزانه‌ی کلادفلر) غیرفعال علامت می‌زنه و دقیقاً همون لحظه که زمانش برسه، خودکار دوباره ازش استفاده می‌کنه — و همیشه ترجیح می‌ده اول برگرده سراغ اکانت شماره ۱،
- همه‌ی این وضعیت‌ها (کدوم اکانت تموم شده، تا کی، کدوم فعاله) رو داخل همون `cfw.session` رمزنگاری‌شده ذخیره می‌کنه، پس با ری‌استارت ربات هم از بین نمی‌ره.

اضافه کردن اکانت جدید بعداً، بدون نیاز به دیپلوی مجدد همه‌چیز:

```bash
andro-cfw add-account
```

چک کردن وضعیت سلامت/چرخش همه‌ی اکانت‌ها:

```bash
andro-cfw status
```

---

## 📋 دستورات CLI

| دستور | توضیح |
|-------|-------|
| `andro-cfw init` | لاگین کلادفلر + deploy یک ورکر (تک‌اکانتی) |
| `andro-cfw init --accounts 3` | لاگین ۳ اکانت + دیپلوی مجموعه‌ی لود‌بالانس‌شده |
| `andro-cfw init --name foo` | deploy با اسم دلخواه |
| `andro-cfw init --force` | redeploy و بازنویسی سشن قبلی |
| `andro-cfw add-account` | اضافه کردن یک اکانت دیگه به سشن موجود |
| `andro-cfw status` | نمایش ورکر(ها) و وضعیت سلامت هر اکانت |
| `andro-cfw remove` | حذف ورکر(ها) + حذف `cfw.session` |

---

## 🔐 نکات امنیتی

- **`cfw.session` رمزنگاری شده** — با Fernet (AES-128-CBC + HMAC). کلید توی `~/.andro_cfw/key` هست، نه کنار پروژه.
- **گیت:** اگه اشتباهاً `cfw.session` رو commit کنی، بدون کلید قابل خوندن نیست. ولی **حتماً `cfw.session` رو به `.gitignore` اضافه کن**.
- **ورکر pass-through خالصه** — لاگ نمی‌گیره، توکن ذخیره نمی‌کنه، محتوای ریکوئست رو نمی‌بینه.
- پسورد کلادفلر هرگز به این کتابخانه نمی‌رسه — همه‌چیز از طریق OAuth رسمی Cloudflare انجام می‌شه؛ در حالت چند‌اکانتی، لاگین هر اکانت کاملاً ایزوله از بقیه‌ست.
- شما روی اکانت(های) Cloudflare **خودتون** دیپلوی می‌کنید (پلن رایگان کافیه)، پس کنترل کامل دارید و هر زمان می‌تونید همه‌ی ورکرها رو حذف کنید.

---

## 📋 نیازمندی‌ها

- Python 3.9+
- Node.js — در صورت نبود، توسط andro-cfw **خودکار نصب** می‌شه (فقط موقع `init` / `add-account` / `remove` لازمه)
- یک اکانت رایگان [Cloudflare](https://dash.cloudflare.com/sign-up) (یا چند تا، برای لود بالانس)

---

## 🗒️ تغییرات نسخه‌ها

### 0.2.0
- **نصب خودکار Node.js**: تشخیص سیستم‌عامل (ویندوز/مک/لینوکس + دیسترو) و پکیج‌منیجر، نصب خودکار در صورت نبود.
- **لود بالانس هوشمند چند‌اکانتی**: `andro-cfw init --accounts N` و `andro-cfw add-account` چند اکانت رایگان کلادفلر رو ترکیب می‌کنن، با سوییچ آنی به محض تموم شدن سهمیه‌ی روزانه و بازگشت خودکار بعد از ریست روزانه‌ی UTC.
- `andro-cfw status` حالا وضعیت هر اکانت رو هم گزارش می‌ده.
- کاملاً سازگار با فایل‌های `cfw.session` تک‌اکانتی قدیمی.

### 0.1.0
- انتشار اولیه.

---

## 📄 لایسنس

MIT