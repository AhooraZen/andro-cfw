"""
Example: the one-line integration.

Import your framework first, then call patch(). It rewrites the imported
framework's API base URL to point at your Cloudflare Worker.

Setup:
    pip install git+https://github.com/AhooraZen/andro-cfw.git pyTelegramBotAPI
    andro-cfw init            # run once, in this same directory
    python patch_example.py
"""

import telebot

from andro_cfw import patch

session = patch()

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
bot = telebot.TeleBot(BOT_TOKEN)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(message, "Hi! I'm running through andro-cfw.")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, message.text)


if __name__ == "__main__":
    print(f"Bot is running via {session.worker_url} ...")
    bot.infinity_polling()
