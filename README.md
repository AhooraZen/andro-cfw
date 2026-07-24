# andro-cfw

Run Telegram bots from filtered/restricted regions (e.g. Iran) **without a VPN**,
by routing Bot API traffic through a Cloudflare Worker reverse proxy that **you** own.

```bash
pip install andro-cfw
```

---

## 📖 Languages / زبان‌ها

| Language | File |
|----------|------|
| 🇬🇧 English  | [README.en.md](README.en.md) |
| 🇮🇷 فارسی     | [README.fa.md](README.fa.md) |

---

## ⚡ Quick Start

```bash
cd your-bot-project/
andro-cfw init      # opens browser → Cloudflare login → deploys worker → saves cfw.session
```

```python
import telebot
from andro_cfw import CFWSession

session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
telebot.apihelper.FILE_URL = session.telebot_file_url()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")
bot.infinity_polling()
```

See the full documentation in your language: [English](README.en.md) | [فارسی](README.fa.md)

---

## 📄 License

MIT
<!-- test webhook 05:53:51 -->
