import os
import json
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
import gspread
from google.oauth2.service_account import Credentials

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY")

# Читаем список ID менеджеров из переменной окружения (через запятую)
MANAGER_IDS_STR = os.environ.get("MANAGER_IDS", "")
MANAGER_IDS = [int(x.strip()) for x in MANAGER_IDS_STR.split(",") if x.strip()]

if not MANAGER_IDS:
    print("⚠️ ВНИМАНИЕ: MANAGER_IDS не указан! Кнопка Помощь не будет работать.")
else:
    print(f"✅ Загружены менеджеры: {MANAGER_IDS}")

app = Flask(__name__)

# Состояния для диалогов
NAME, PHOTO, PRICE, MIN_HOURS, CITY, DESCRIPTION, CONTACT = range(7)
SELECT_DAY, SELECT_HOUR, SELECT_DURATION = range(10, 13)

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
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            print("❌ GOOGLE_CREDENTIALS не найдена")
            return False

        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEETS_KEY)

        users_sheet = sheet.worksheet("Users")
        items_sheet = sheet.worksheet("Items")
        orders_sheet = sheet.worksheet("Orders")
        bookings_sheet = sheet.worksheet("Bookings")

        print("✅ Google Sheets подключена")
        return True
    except Exception as e:
        print(f"❌ Ошибка Google Sheets: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С GOOGLE SHEETS ==========
def save_user_to_sheets(user_id, role, username, full_name):
    try:
        users_sheet.append_row([str(user_id), role, username or "", full_name or ""])
        return True
    except Exception as e:
        print(f"Ошибка сохранения пользователя: {e}")
        return False

def save_item_to_sheets(owner_id, name, photo, price, min_hours, city, description, contact):
    try:
        items_sheet.append_row([
            "", str(owner_id), photo or "", name,
            str(price), str(min_hours), city, description, contact
        ])
        return True
    except Exception as e:
        print(f"Ошибка сохранения товара: {e}")
        return False

def save_order_to_sheets(item_id, renter_id, owner_id, start_dt, end_dt, total_hours, total_price, status):
    try:
        orders_sheet.append_row([
            "", str(item_id), str(renter_id), str(owner_id),
            start_dt.isoformat(), end_dt.isoformat(),
            str(total_hours), str(total_price), status, datetime.now().isoformat()
        ])
        return True
    except Exception as e:
        print(f"Ошибка сохранения заказа: {e}")
        return False

def save_booking_to_sheets(item_id, order_id, start_dt, end_dt):
    try:
        bookings_sheet.append_row([
            "", str(item_id), str(order_id),
            start_dt.isoformat(), end_dt.isoformat()
        ])
        return True
    except Exception as e:
        print(f"Ошибка сохранения брони: {e}")
        return False

def get_items_from_sheets():
    try:
        records = items_sheet.get_all_records()
        items = []
        for i, row in enumerate(records, start=2):
            if row.get('name'):
                items.append({
                    'id': i,
                    'owner_id': int(row.get('owner_id', 0)),
                    'name': row.get('name', ''),
                    'photo': row.get('photo', ''),
                    'price': row.get('price_per_hour', 0),
                    'min_hours': int(row.get('min_hours', 1)),
                    'city': row.get('city', ''),
                    'description': row.get('description', ''),
                    'contact': row.get('contact', '')
                })
        return items
    except Exception as e:
        print(f"Ошибка загрузки товаров: {e}")
        return []

def get_orders_from_sheets():
    try:
        records = orders_sheet.get_all_records()
        orders = []
        for i, row in enumerate(records, start=2):
            orders.append({
                'id': i,
                'item_id': int(row.get('item_id', 0)),
                'renter_id': int(row.get('renter_id', 0)),
                'owner_id': int(row.get('owner_id', 0)),
                'start_datetime': row.get('start_datetime', ''),
                'end_datetime': row.get('end_datetime', ''),
                'total_price': row.get('total_price', 0),
                'status': row.get('status', 'Новая заявка')
            })
        return orders
    except Exception as e:
        print(f"Ошибка загрузки заказов: {e}")
        return []

def get_bookings_from_sheets():
    try:
        records = bookings_sheet.get_all_records()
        bookings = []
        for row in records:
            bookings.append({
                'item_id': int(row.get('item_id', 0)),
                'order_id': int(row.get('order_id', 0)),
                'start_datetime': row.get('start_datetime', ''),
                'end_datetime': row.get('end_datetime', '')
            })
        return bookings
    except Exception as e:
        print(f"Ошибка загрузки броней: {e}")
        return []

def update_order_status_in_sheets(order_id, status):
    try:
        cell = orders_sheet.find(str(order_id))
        if cell:
            orders_sheet.update_cell(cell.row, 9, status)
            return True
    except Exception as e:
        print(f"Ошибка обновления статуса: {e}")
    return False

def check_booking_conflict(item_id, start_dt, end_dt):
    bookings = get_bookings_from_sheets()
    for booking in bookings:
        if booking['item_id'] == item_id:
            existing_start = datetime.fromisoformat(booking['start_datetime'])
            existing_end = datetime.fromisoformat(booking['end_datetime'])
            if start_dt < existing_end and end_dt > existing_start:
                return True
    return False

def get_last_order_id():
    orders = get_orders_from_sheets()
    return orders[-1]['id'] if orders else 1

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def show_main_menu(update: Update, context):
    role = context.user_data.get('role', '')

    if role == "Арендатор":
        keyboard = [
            [InlineKeyboardButton("📷 Каталог", callback_data="catalog")],
            [InlineKeyboardButton("📦 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton("🆘 Помощь", callback_data="help")]
        ]
        text = "🏠 Главное меню (Арендатор):"
    elif role == "Арендодатель":
        keyboard = [
            [InlineKeyboardButton("📷 Каталог", callback_data="catalog")],
            [InlineKeyboardButton("➕ Добавить технику", callback_data="add_item")],
            [InlineKeyboardButton("📋 Мои объявления", callback_data="my_ads")],
            [InlineKeyboardButton("🆘 Помощь", callback_data="help")]
        ]
        text = "🏠 Главное меню (Арендодатель):"
    else:
        keyboard = [
            [InlineKeyboardButton("👤 Арендатор", callback_data="role_renter")],
            [InlineKeyboardButton("👑 Арендодатель", callback_data="role_owner")]
        ]
        text = "📸 Добро пожаловать! Кто вы?"

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ========== КОМАНДЫ ==========
async def start(update: Update, context):
    context.user_data.clear()
    await show_main_menu(update, context)

async def help_handler(update: Update, context):
    """Помощь — пересылка сообщения ВСЕМ менеджерам"""
    query = update.callback_query
    await query.answer()

    if not MANAGER_IDS:
        await query.message.reply_text("🆘 Менеджер пока не назначен. Попробуйте позже.")
        return

    success_count = 0
    for manager_id in MANAGER_IDS:
        try:
            await context.bot.forward_message(
                chat_id=manager_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
            success_count += 1
        except Exception as e:
            print(f"Ошибка отправки менеджеру {manager_id}: {e}")

    if success_count > 0:
        await query.message.reply_text(
            f"🆘 Сообщение отправлено {success_count} менеджер(ам).\n\n"
            f"Ответ придёт в ближайшее время."
        )
    else:
        await query.message.reply_text("❌ Не удалось отправить сообщение. Попробуйте позже.")

# ========== ОТВЕТЫ МЕНЕДЖЕРОВ ПОЛЬЗОВАТЕЛЯМ ==========
async def manager_reply(update: Update, context):
    """
    Когда менеджер отвечает на пересланное сообщение пользователя,
    бот отправляет ответ оригинальному пользователю
    """
    # Проверяем, что отправитель — менеджер
    if update.effective_user.id not in MANAGER_IDS:
        return

    message = update.message

    # Если ответ на пересланное сообщение
    if message.reply_to_message and message.reply_to_message.forward_origin:
        try:
            user_id = message.reply_to_message.forward_origin.chat.id

            await context.bot.send_message(
                chat_id=user_id,
                text=f"📩 *Ответ от поддержки:*\n\n{message.text}",
                parse_mode="Markdown"
            )

            await message.reply_text("✅ Ответ отправлен пользователю.")

        except Exception as e:
            await message.reply_text(f"❌ Ошибка отправки: {e}")
            print(f"Ошибка manager_reply: {e}")

# ========== ВЫБОР РОЛИ ==========
async def role_choice(update: Update, context):
    query = update.callback_query
    await query.answer()

    role = "Арендатор" if query.data == "role_renter" else "Арендодатель"
    context.user_data['role'] = role
    context.user_data['user_id'] = query.from_user.id

    save_user_to_sheets(
        query.from_user.id,
        role,
        query.from_user.username or "",
        query.from_user.full_name or ""
    )

    await show_main_menu(update, context)

# ========== КАТАЛОГ ==========
async def catalog(update: Update, context):
    items = get_items_from_sheets()
    if not items:
        await update.callback_query.message.reply_text("📭 Пока нет объявлений.")
        return

    for item in items:
        text = f"📷 {item['name']}\n💰 {item['price']} ₽/час\n📍 {item['city']}\n{item['description']}"
        keyboard = [[InlineKeyboardButton("📅 Забронировать", callback_data=f"book_{item['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

# ========== БРОНИРОВАНИЕ ==========
async def start_booking(update: Update, context):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split('_')[1])
    context.user_data['booking_item_id'] = item_id

    items = get_items_from_sheets()
    item = next((i for i in items if i['id'] == item_id), None)
    if not item:
        await query.message.reply_text("❌ Товар не найден")
        return
    context.user_data['booking_item'] = item

    keyboard = []
    for i in range(7):
        date = datetime.now() + timedelta(days=i)
        keyboard.append([InlineKeyboardButton(date.strftime("%d.%m.%Y"), callback_data=f"day_{i}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Выберите ДЕНЬ аренды:", reply_markup=reply_markup)
    return SELECT_DAY

async def select_day(update: Update, context):
    query = update.callback_query
    await query.answer()
    day_offset = int(query.data.split('_')[1])
    selected_date = datetime.now() + timedelta(days=day_offset)
    context.user_data['booking_date'] = selected_date

    keyboard = []
    for hour in range(10, 21):
        keyboard.append([InlineKeyboardButton(f"{hour}:00", callback_data=f"hour_{hour}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"📅 {selected_date.strftime('%d.%m.%Y')}\nВыберите ЧАС начала:", reply_markup=reply_markup)
    return SELECT_HOUR

async def select_hour(update: Update, context):
    query = update.callback_query
    await query.answer()
    hour = int(query.data.split('_')[1])
    context.user_data['booking_hour'] = hour

    item = context.user_data['booking_item']
    min_hours = item.get('min_hours', 1)
    keyboard = []
    for h in range(min_hours, min(13, min_hours + 5)):
        keyboard.append([InlineKeyboardButton(f"{h} час(ов)", callback_data=f"dur_{h}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"⏰ Начало в {hour}:00\nВыберите ДЛИТЕЛЬНОСТЬ (мин. {min_hours} ч):", reply_markup=reply_markup)
    return SELECT_DURATION

async def select_duration(update: Update, context):
    query = update.callback_query
    await query.answer()
    duration = int(query.data.split('_')[1])

    start_dt = context.user_data['booking_date'].replace(hour=context.user_data['booking_hour'], minute=0)
    end_dt = start_dt + timedelta(hours=duration)
    item = context.user_data['booking_item']
    total_price = int(item['price']) * duration

    if check_booking_conflict(item['id'], start_dt, end_dt):
        await query.message.reply_text("❌ Это время уже занято! Выберите другое.")
        return

    save_order_to_sheets(
        item['id'],
        update.effective_user.id,
        item['owner_id'],
        start_dt,
        end_dt,
        duration,
        total_price,
        "Новая заявка"
    )

    order_id = get_last_order_id()
    save_booking_to_sheets(item['id'], order_id, start_dt, end_dt)

    text = f"✅ Заявка создана!\n\n📷 {item['name']}\n📅 {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n💰 {total_price} ₽\n\n⏳ Ожидайте подтверждения."
    await query.message.reply_text(text)

    keyboard = [
        [InlineKeyboardButton("✅ Обсудить", callback_data=f"discuss_{order_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=item['owner_id'],
        text=f"🔔 НОВАЯ ЗАЯВКА!\n\n📷 {item['name']}\n📅 {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n💰 {total_price} ₽",
        reply_markup=reply_markup
    )

# ========== ОБРАБОТКА ЗАЯВОК ==========
async def discuss_order(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])

    orders = get_orders_from_sheets()
    order = next((o for o in orders if o['id'] == order_id), None)
    if not order:
        await query.message.reply_text("❌ Заказ не найден")
        return

    update_order_status_in_sheets(order_id, "В обсуждении")

    items = get_items_from_sheets()
    item = next((i for i in items if i['id'] == order['item_id']), {})

    await context.bot.send_message(
        chat_id=order['renter_id'],
        text=f"✅ Арендодатель готов обсуждать детали!\n\n📞 Его контакт: {item.get('contact', 'не указан')}\n\nОбсудите условия аренды напрямую."
    )

    renter_contact = f"@{query.from_user.username}" if query.from_user.username else f"ID: {query.from_user.id}"
    await query.message.reply_text(
        f"✅ Вы начали обсуждение!\n\n📞 Контакт арендатора: {renter_contact}\n\nПосле передачи техники нажмите ниже.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Техника выдана", callback_data=f"issued_{order_id}")]])
    )

async def reject_order(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])

    orders = get_orders_from_sheets()
    order = next((o for o in orders if o['id'] == order_id), None)
    if order:
        update_order_status_in_sheets(order_id, "Отклонена")

    await context.bot.send_message(
        chat_id=order['renter_id'],
        text="❌ Арендодатель отклонил вашу заявку."
    )
    await query.message.reply_text("❌ Заявка отклонена.")

async def mark_issued(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])

    update_order_status_in_sheets(order_id, "Техника выдана")
    await query.message.reply_text(
        "✅ Техника выдана.\n\nПосле возврата нажмите:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Техника возвращена", callback_data=f"returned_{order_id}")]])
    )

async def mark_returned(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])

    update_order_status_in_sheets(order_id, "Завершён")
    await query.message.reply_text("✅ Техника возвращена. Спасибо!")

# ========== МОИ ОБЪЯВЛЕНИЯ ==========
async def my_ads(update: Update, context):
    user_id = update.effective_user.id
    items = get_items_from_sheets()
    my_items = [item for item in items if item.get('owner_id') == user_id]

    if not my_items:
        await update.callback_query.message.reply_text("📋 У вас пока нет объявлений.")
        return

    for item in my_items:
        text = f"📷 {item['name']}\n💰 {item['price']} ₽/час\n📍 {item['city']}"
        keyboard = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{item['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

async def delete_item(update: Update, context):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split('_')[1])

    try:
        cell = items_sheet.find(str(item_id))
        if cell:
            items_sheet.delete_row(cell.row)
            await query.edit_message_text("🗑 Объявление удалено.")
    except Exception as e:
        print(f"Ошибка удаления: {e}")
        await query.edit_message_text("❌ Ошибка при удалении.")

# ========== МОИ ЗАКАЗЫ ==========
async def my_orders(update: Update, context):
    user_id = update.effective_user.id
    role = context.user_data.get('role', '')
    orders = get_orders_from_sheets()

    if role == 'Арендатор':
        my_orders_list = [o for o in orders if o.get('renter_id') == user_id]
    else:
        my_orders_list = [o for o in orders if o.get('owner_id') == user_id]

    if not my_orders_list:
        await update.callback_query.message.reply_text("📭 У вас пока нет заказов.")
        return

    for order in my_orders_list:
        status_emoji = {
            'Новая заявка': '🕐',
            'В обсуждении': '💬',
            'Техника выдана': '📦',
            'Завершён': '✅',
            'Отклонена': '❌'
        }.get(order['status'], '❓')

        text = f"{status_emoji} Заказ #{order['id']}\n"
        text += f"📅 {order['start_datetime'][:16].replace('T', ' ')}\n"
        text += f"💰 {order['total_price']} ₽\n"
        text += f"📌 Статус: {order['status']}"
        await update.callback_query.message.reply_text(text)

# ========== ДОБАВЛЕНИЕ ТЕХНИКИ ==========
async def add_item_start(update: Update, context):
    await update.callback_query.message.reply_text("Введите НАЗВАНИЕ техники:")
    return NAME

async def add_item_name(update: Update, context):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Отправьте ФОТО техники:")
    return PHOTO

async def add_item_photo(update: Update, context):
    context.user_data['photo'] = update.message.photo[-1].file_id
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
    save_item_to_sheets(
        update.effective_user.id,
        context.user_data['name'],
        context.user_data.get('photo', ''),
        context.user_data['price'],
        context.user_data.get('min_hours', '1'),
        context.user_data['city'],
        context.user_data['description'],
        update.message.text
    )
    await update.message.reply_text("✅ Техника добавлена в каталог!")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context):
    await update.message.reply_text("❌ Добавление отменено.")
    return ConversationHandler.END

async def unknown(update: Update, context):
    await update.message.reply_text("❓ Напишите /start")

# ========== ЗАПУСК БОТА ==========
async def run_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(role_choice, pattern="^role_"))
    application.add_handler(CallbackQueryHandler(catalog, pattern="^catalog$"))
    application.add_handler(CallbackQueryHandler(my_ads, pattern="^my_ads$"))
    application.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
    application.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(delete_item, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(discuss_order, pattern="^discuss_"))
    application.add_handler(CallbackQueryHandler(reject_order, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(mark_issued, pattern="^issued_"))
    application.add_handler(CallbackQueryHandler(mark_returned, pattern="^returned_"))

    # Обработчик ответов менеджеров
    if MANAGER_IDS:
        application.add_handler(MessageHandler(
            filters.TEXT & filters.REPLY & filters.Chat(chat_id=MANAGER_IDS),
            manager_reply
        ))

    # Бронирование (Conversation)
    book_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_booking, pattern="^book_")],
        states={
            SELECT_DAY: [CallbackQueryHandler(select_day, pattern="^day_")],
            SELECT_HOUR: [CallbackQueryHandler(select_hour, pattern="^hour_")],
            SELECT_DURATION: [CallbackQueryHandler(select_duration, pattern="^dur_")],
        },
        fallbacks=[],
    )
    application.add_handler(book_conv)

    # Добавление техники (Conversation)
    add_conv = ConversationHandler(
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
    application.add_handler(add_conv)

    # Заглушка для неизвестных сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    print("🚀 Бот запущен!")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    while True:
        await asyncio.sleep(1)

# ========== FLASK ДЛЯ RENDER ==========
@app.route('/')
def home():
    return "Photo Rental Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ========== ТОЧКА ВХОДА ==========
if __name__ == "__main__":
    init_google_sheets()

    def start_bot():
        asyncio.run(run_bot())

    threading.Thread(target=start_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
