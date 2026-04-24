import os
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY", "ТВОЙ_ID_ТАБЛИЦЫ")

app = Flask(__name__)

# Состояния для диалога добавления техники
NAME, PHOTO, PRICE, MIN_HOURS, CITY, DESCRIPTION, CONTACT = range(7)

# Глобальные переменные для Google Sheets
gc = None
users_sheet = None
items_sheet = None
orders_sheet = None
bookings_sheet = None

# ========== ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ==========
def init_google_sheets():
    global gc, users_sheet, items_sheet, orders_sheet, bookings_sheet
    try:
        # Для Render нужно будет добавить credentials.json как переменную окружения
        # Пока работаем без Google Sheets, если нет ключей
        print("⚠️ Google Sheets: функция временно отключена (нужен credentials.json)")
        return False
    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

# ========== КОМАНДЫ ==========
async def start(update: Update, context):
    """Главное меню с выбором роли"""
    keyboard = [
        [InlineKeyboardButton("👤 Арендатор", callback_data="role_renter")],
        [InlineKeyboardButton("👑 Арендодатель", callback_data="role_owner")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📸 Добро пожаловать в Маркетплейс аренды фототехники!\n\n"
        "Кто вы?",
        reply_markup=reply_markup
    )

async def help_handler(update: Update, context):
    """Помощь — пересылка менеджеру"""
    MANAGER_ID = int(os.environ.get("MANAGER_ID", "0"))
    if MANAGER_ID:
        await context.bot.forward_message(
            chat_id=MANAGER_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.effective_message.id
        )
        await update.message.reply_text("🆘 Сообщение отправлено менеджеру. Ответ придёт в ближайшее время.")
    else:
        await update.message.reply_text("🆘 Менеджер пока не назначен.")

async def my_ads(update: Update, context):
    """Мои объявления (для арендодателя)"""
    await update.callback_query.message.reply_text("📋 Скоро здесь будут ваши объявления.")

async def my_orders(update: Update, context):
    """Мои заказы (для арендатора)"""
    await update.callback_query.message.reply_text("📦 Скоро здесь будут ваши заказы.")

# ========== ВЫБОР РОЛИ ==========
async def role_choice(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    role = "Арендатор" if query.data == "role_renter" else "Арендодатель"
    context.user_data['role'] = role
    
    # Главное меню после регистрации
    keyboard = [
        [InlineKeyboardButton("📷 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("➕ Добавить технику", callback_data="add_item")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="my_ads")],
        [InlineKeyboardButton("📦 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton("🆘 Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Вы зарегистрированы как {role}!\n\n"
        f"Главное меню:",
        reply_markup=reply_markup
    )

# ========== КАТАЛОГ ==========
async def catalog(update: Update, context):
    """Показать все объявления"""
    # Временные тестовые данные
    items = [
        {"name": "Canon 5D Mark IV", "price": 1500, "city": "Москва", "description": "Профессиональная камера"},
        {"name": "Sony A7III", "price": 1200, "city": "СПб", "description": "Полнокадровая беззеркалка"}
    ]
    
    if not items:
        await update.callback_query.message.reply_text("📭 Пока нет объявлений.")
        return
    
    for item in items:
        text = f"📷 {item['name']}\n💰 {item['price']} ₽/час\n📍 {item['city']}\n{item['description']}"
        keyboard = [[InlineKeyboardButton("🔍 Подробнее", callback_data=f"view_1")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

# ========== ДОБАВЛЕНИЕ ТЕХНИКИ ==========
async def add_item_start(update: Update, context):
    """Начало диалога добавления техники"""
    await update.callback_query.message.reply_text("Введите НАЗВАНИЕ техники:")
    return NAME

async def add_item_name(update: Update, context):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Отправьте ФОТО техники (одним сообщением):")
    return PHOTO

async def add_item_photo(update: Update, context):
    photo = update.message.photo[-1].file_id
    context.user_data['photo'] = photo
    await update.message.reply_text("Введите ЦЕНУ за час (только число):")
    return PRICE

async def add_item_price(update: Update, context):
    context.user_data['price'] = update.message.text
    await update.message.reply_text("Введите минимальное количество часов (1-24):")
    return MIN_HOURS

async def add_item_min_hours(update: Update, context):
    context.user_data['min_hours'] = update.message.text
    await update.message.reply_text("Введите ГОРОД:")
    return CITY

async def add_item_city(update: Update, context):
    context.user_data['city'] = update.message.text
    await update.message.reply_text("Введите ОПИСАНИЕ техники:")
    return DESCRIPTION

async def add_item_description(update: Update, context):
    context.user_data['description'] = update.message.text
    await update.message.reply_text("Введите ваш КОНТАКТ (телефон или @username):")
    return CONTACT

async def add_item_contact(update: Update, context):
    context.user_data['contact'] = update.message.text
    
    # Сохраняем в память (пока без Google Sheets)
    if 'items' not in context.bot_data:
        context.bot_data['items'] = []
    
    new_id = len(context.bot_data['items']) + 1
    context.bot_data['items'].append({
        'id': new_id,
        'owner_id': update.effective_user.id,
        'name': context.user_data['name'],
        'photo': context.user_data.get('photo', ''),
        'price': context.user_data['price'],
        'min_hours': context.user_data['min_hours'],
        'city': context.user_data['city'],
        'description': context.user_data['description'],
        'contact': context.user_data['contact']
    })
    
    await update.message.reply_text("✅ Техника добавлена в каталог!")
    return ConversationHandler.END

async def cancel(update: Update, context):
    await update.message.reply_text("❌ Добавление отменено.")
    return ConversationHandler.END

# ========== ЗАПУСК БОТА ==========
async def run_bot():
    try:
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_handler))
        
        # Callback handlers
        application.add_handler(CallbackQueryHandler(role_choice, pattern="^role_"))
        application.add_handler(CallbackQueryHandler(catalog, pattern="^catalog$"))
        application.add_handler(CallbackQueryHandler(my_ads, pattern="^my_ads$"))
        application.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
        application.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
        application.add_handler(CallbackQueryHandler(add_item_start, pattern="^add_item$"))
        
        # Conversation handler для добавления техники
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(add_item_start, pattern="^add_item$")],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_name)],
                PHOTO: [MessageHandler(filters.PHOTO, add_item_photo)],
                PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_price)],
                MIN_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_min_hours)],
                CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_city)],
                DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_description)],
                CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_contact)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(conv_handler)
        
        # Заглушка для неизвестных сообщений
        async def unknown(update: Update, context):
            await update.message.reply_text("Я вас не понял. Напишите /start")
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
        
        print("🚀 Бот запущен и слушает сообщения...")
        
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")

# ========== FLASK ДЛЯ RENDER ==========
@app.route('/')
def home():
    return "Photo Rental Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    # Инициализация Google Sheets (пока отключена)
    init_google_sheets()
    
    # Запуск бота
    def start_bot_thread():
        asyncio.run(run_bot())
    
    bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
    bot_thread.start()
    
    # Flask для Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
