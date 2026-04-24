import os
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TOKEN:
    print("❌ ОШИБКА: Токен не найден!")
else:
    print(f"✅ Токен загружен, начинается с {TOKEN[:10]}...")

async def start(update: Update, context):
    await update.message.reply_text("✅ Бот работает! Токен правильный.")

@app.route('/')
def home():
    return "Бот работает!"

def run_bot():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        print("🚀 Бот запущен и слушает сообщения...")
        application.run_polling()
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")

if __name__ == "__main__":
    import threading
    # Небольшая задержка перед запуском бота
    threading.Timer(2, run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
