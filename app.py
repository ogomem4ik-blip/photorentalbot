import os
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler

app = Flask(__name__)

# Получаем токен из переменных окружения Render
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Проверка: если токен не загрузился
if not TOKEN:
    print("❌ ОШИБКА: Токен не найден! Добавь TELEGRAM_TOKEN в Environment Variables")
else:
    print(f"✅ Токен загружен, начинается с {TOKEN[:10]}...")

# Простейшая команда /start
async def start(update: Update, context):
    await update.message.reply_text("✅ Бот работает! Токен правильный.")

# Flask — чтобы Render не жаловался
@app.route('/')
def home():
    return "Бот работает!"

# Запуск бота
def run_bot():
    if not TOKEN:
        return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    print("🚀 Бот запущен и слушает сообщения...")
    application.run_polling()

if __name__ == "__main__":
    import threading
    # Запускаем бота в отдельном потоке
    thread = threading.Thread(target=run_bot)
    thread.start()
    # Запускаем Flask для Render
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
