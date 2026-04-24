import os
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
import threading

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ТВОЙ_ТОКЕН_СЮДА")
PORT = int(os.environ.get("PORT", 8080))

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

@app.route('/health')
def health():
    return "OK", 200

async def start(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("👤 Арендатор", callback_data="role_renter")],
        [InlineKeyboardButton("👑 Арендодатель", callback_data="role_owner")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Добро пожаловать! Вы арендатор или арендодатель?", reply_markup=reply_markup)

async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    role = "Арендатор" if query.data == "role_renter" else "Арендодатель"
    await query.edit_message_text(f"✅ Вы зарегистрированы как {role}!")

def run_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

threading.Thread(target=run_bot).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
