"""
Example: a minimal echo bot using python-telegram-bot (v20+), routed through
an andro-cfw Cloudflare Worker proxy.

Setup:
    pip install andro-cfw "python-telegram-bot>=20.0"
    andro-cfw init            # run once, in this same directory
    python ptb_example.py
"""

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from andro_cfw import CFWSession

session = CFWSession.load()

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

app = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .base_url(session.ptb_base_url())
    .base_file_url(session.ptb_base_file_url())
    .build()
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I'm running through andro-cfw.")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)


app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

if __name__ == "__main__":
    print(f"Bot is running via {session.worker_url} ...")
    app.run_polling()
