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
    await update.message.reply_text("✅ Бот работает! Версия 21.5")

@app.route('/')
def home():
    return "Бот работает!"

async def run_bot():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        print("🚀 Бот запущен и слушает сообщения...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        # Держим бота запущенным
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")

if __name__ == "__main__":
    import threading
    import asyncio
    import time
    
    # Запускаем бота в отдельном потоке
    def start_bot_thread():
        asyncio.run(run_bot())
    
    threading.Thread(target=start_bot_thread, daemon=True).start()
    
    # Flask запускаем в главном потоке
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
