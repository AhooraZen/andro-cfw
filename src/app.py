import telebot
from andro_cfw import CFWSession

# Load your deployed worker proxy session
session = CFWSession.load()

# Configure telebot to route requests through andro-cfw proxy
telebot.apihelper.API_URL = session.telebot_api_url()
telebot.apihelper.FILE_URL = session.telebot_file_url()

bot = telebot.TeleBot("YOUR_BOT_TOKEN")

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "Hello! This bot is running through andro-cfw proxy! 🚀")

if __name__ == "__main__":
    print("Bot is starting via andro-cfw proxy...")
    bot.infinity_polling()