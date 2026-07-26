"""
Example: a minimal echo bot using pyTelegramBotAPI (telebot), routed through
an andro-cfw Cloudflare Worker proxy.

Setup:
    pip install git+https://github.com/AhooraZen/andro-cfw.git pyTelegramBotAPI
    andro-cfw init            # run once, in this same directory
    python telebot_example.py
"""

import telebot

from andro_cfw import CFWSession

session = CFWSession.load()
telebot.apihelper.API_URL = session.telebot_api_url()
telebot.apihelper.FILE_URL = session.telebot_file_url()

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
bot = telebot.TeleBot(BOT_TOKEN)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(message, "Hi! I'm running through andro-cfw. Send me anything and I'll echo it.")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, message.text)


if __name__ == "__main__":
    print(f"Bot is running via {session.worker_url} ...")
    bot.infinity_polling()
