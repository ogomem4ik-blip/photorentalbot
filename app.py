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

MANAGER_IDS_STR = os.environ.get("MANAGER_IDS", "")
MANAGER_IDS = [int(x.strip()) for x in MANAGER_IDS_STR.split(",") if x.strip()]

if not MANAGER_IDS:
    print("⚠️ ВНИМАНИЕ: MANAGER_IDS не указан!")
else:
    print(f"✅ Загружены менеджеры: {MANAGER_IDS}")

app = Flask(__name__)

# Состояния для диалогов
NAME, PHOTO, PRICE, MIN_HOURS, CITY, DESCRIPTION, CONTACT = range(7)
SELECT_DAY, SELECT_HOUR, SELECT_DURATION = range(10, 13)
HELP_MESSAGE = 20
AWAITING_REPLY_TEXT = 30

# Google Sheets
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
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
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

# ========== ФУНКЦИИ GOOGLE SHEETS ==========
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

def get_items_from_sheets():
    try:
        all_rows = items_sheet.get_all_values()
        if len(all_rows) <= 1:
            return []
        items = []
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) >= 5 and row[3]:
                items.append({
                    'id': i,
                    'owner_id': int(row[1]) if row[1] else 0,
                    'photo': row[2] if len(row) > 2 else '',
                    'name': row[3] if len(row) > 3 else '',
                    'price': int(row[4]) if len(row) > 4 and row[4] else 0,
                    'min_hours': int(row[5]) if len(row) > 5 and row[5] else 1,
                    'city': row[6] if len(row) > 6 else '',
                    'description': row[7] if len(row) > 7 else '',
                    'contact': row[8] if len(row) > 8 else ''
                })
        return items
    except Exception as e:
        print(f"Ошибка загрузки товаров: {e}")
        return []

def get_orders_from_sheets():
    try:
        all_rows = orders_sheet.get_all_values()
        if len(all_rows) <= 1:
            return []
        orders = []
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) >= 4 and row[3]:
                orders.append({
                    'id': i,
                    'item_id': int(row[1]) if row[1] else 0,
                    'renter_id': int(row[2]) if row[2] else 0,
                    'owner_id': int(row[3]) if row[3] else 0,
                    'start_datetime': row[4] if len(row) > 4 else '',
                    'end_datetime': row[5] if len(row) > 5 else '',
                    'total_price': int(row[7]) if len(row) > 7 and row[7] else 0,
                    'status': row[8] if len(row) > 8 else 'Новая заявка'
                })
        return orders
    except Exception as e:
        print(f"Ошибка загрузки заказов: {e}")
        return []

def update_order_status_in_sheets(order_id, status):
    try:
        orders_sheet.update_cell(order_id, 9, status)
        return True
    except Exception as e:
        print(f"Ошибка обновления статуса: {e}")
        return False

def check_booking_conflict(item_id, start_dt, end_dt):
    try:
        all_rows = bookings_sheet.get_all_values()
        if len(all_rows) <= 1:
            return False
        for row in all_rows[1:]:
            if len(row) >= 2 and row[1] and int(row[1]) == item_id:
                existing_start = datetime.fromisoformat(row[3])
                existing_end = datetime.fromisoformat(row[4])
                if start_dt < existing_end and end_dt > existing_start:
                    return True
        return False
    except Exception as e:
        print(f"Ошибка проверки конфликта: {e}")
        return False

# ========== ГЛАВНОЕ МЕНЮ ==========
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

# ========== КОМАНДЫ ИЗ МЕНЮ ==========
async def start(update: Update, context):
    context.user_data.clear()
    await show_main_menu(update, context)

async def my_ads_command(update: Update, context):
    user_id = update.effective_user.id
    role = context.user_data.get('role', '')
    
    if role != "Арендодатель":
        await update.message.reply_text("❌ Эта команда только для арендодателей.")
        return
    
    items = get_items_from_sheets()
    my_items = [item for item in items if item.get('owner_id') == user_id]
    
    if not my_items:
        await update.message.reply_text("📋 У вас пока нет объявлений.")
        return
    
    for item in my_items:
        text = f"📷 *{item['name']}*\n💰 {item['price']} ₽/час\n⏰ Мин. аренда: {item.get('min_hours', 1)} час(ов)\n📍 {item['city']}"
        keyboard = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{item['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if item.get('photo'):
            try:
                await update.message.reply_photo(photo=item['photo'], caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            except Exception:
                await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def my_orders_command(update: Update, context):
    user_id = update.effective_user.id
    role = context.user_data.get('role', '')
    orders = get_orders_from_sheets()
    
    if role == 'Арендатор':
        my_list = [o for o in orders if o.get('renter_id') == user_id]
        title = "📦 Ваши заказы:"
    elif role == 'Арендодатель':
        my_list = [o for o in orders if o.get('owner_id') == user_id]
        title = "📋 Заявки на вашу технику:"
    else:
        await update.message.reply_text("❌ Сначала выберите роль через /start")
        return
    
    if not my_list:
        await update.message.reply_text("📭 У вас пока нет заказов.")
        return
    
    await update.message.reply_text(title)
    for order in my_list:
        status_emoji = {
            'Новая заявка': '🕐', 'В обсуждении': '💬',
            'Техника выдана': '📦', 'Завершён': '✅', 'Отклонена': '❌'
        }.get(order['status'], '❓')
        text = f"{status_emoji} Заказ #{order['id']}\n"
        text += f"📅 {order['start_datetime'][:16].replace('T', ' ')}\n"
        text += f"💰 {order['total_price']} ₽\n📌 Статус: {order['status']}"
        await update.message.reply_text(text)

# ========== ВЫБОР РОЛИ ==========
async def role_choice(update: Update, context):
    query = update.callback_query
    await query.answer()

    role = "Арендатор" if query.data == "role_renter" else "Арендодатель"
    context.user_data['role'] = role
    context.user_data['user_id'] = query.from_user.id

    save_user_to_sheets(
        query.from_user.id, role,
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
        text = f"📷 *{item['name']}*\n💰 {item['price']} ₽/час\n⏰ Мин. аренда: {item.get('min_hours', 1)} час(ов)\n📍 {item['city']}\n\n{item['description']}"
        keyboard = [[InlineKeyboardButton("📅 Забронировать", callback_data=f"book_{item['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if item.get('photo'):
            try:
                await update.callback_query.message.reply_photo(photo=item['photo'], caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            except Exception:
                await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

# ========== БРОНИРОВАНИЕ ==========
async def start_booking(update: Update, context):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split('_')[1])
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
    await query.message.reply_text("Выберите ДЕНЬ аренды:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_DAY

async def select_day(update: Update, context):
    query = update.callback_query
    await query.answer()
    day_offset = int(query.data.split('_')[1])
    context.user_data['booking_date'] = datetime.now() + timedelta(days=day_offset)
    keyboard = [[InlineKeyboardButton(f"{h}:00", callback_data=f"hour_{h}")] for h in range(10, 21)]
    await query.message.reply_text(f"📅 {context.user_data['booking_date'].strftime('%d.%m.%Y')}\nВыберите ЧАС начала:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_HOUR

async def select_hour(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['booking_hour'] = int(query.data.split('_')[1])
    item = context.user_data['booking_item']
    min_hours = item.get('min_hours', 1)
    keyboard = [[InlineKeyboardButton(f"{h} час(ов)", callback_data=f"dur_{h}")] for h in range(min_hours, min(13, min_hours + 5))]
    await query.message.reply_text(f"⏰ Начало в {context.user_data['booking_hour']}:00\nВыберите ДЛИТЕЛЬНОСТЬ:", reply_markup=InlineKeyboardMarkup(keyboard))
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
        await query.message.reply_text("❌ Это время уже занято!")
        return
    
    # Сохраняем заказ
    new_row = [
        "", str(item['id']), str(update.effective_user.id), str(item['owner_id']),
        start_dt.isoformat(), end_dt.isoformat(), str(duration), str(total_price),
        "Новая заявка", datetime.now().isoformat()
    ]
    orders_sheet.append_row(new_row)
    
    # Получаем ID заказа (номер строки)
    all_orders = orders_sheet.get_all_values()
    order_id = len(all_orders)
    
    # Сохраняем бронирование
    bookings_sheet.append_row([
        "", str(item['id']), str(order_id), start_dt.isoformat(), end_dt.isoformat()
    ])
    
    await query.message.reply_text(f"✅ Заявка создана!\n\n📷 {item['name']}\n📅 {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n💰 {total_price} ₽\n\n⏳ Ожидайте подтверждения.")
    
    keyboard = [[InlineKeyboardButton("✅ Обсудить", callback_data=f"discuss_{order_id}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}")]]
    await context.bot.send_message(
        chat_id=item['owner_id'],
        text=f"🔔 НОВАЯ ЗАЯВКА!\n\n📷 {item['name']}\n📅 {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n💰 {total_price} ₽",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ========== ОБРАБОТКА ЗАЯВОК ==========
async def discuss_order(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])
    
    all_rows = orders_sheet.get_all_values()
    if order_id >= len(all_rows) or order_id < 1:
        await query.message.reply_text("❌ Заказ не найден")
        return
    
    row = all_rows[order_id]
    if len(row) < 9:
        await query.message.reply_text("❌ Заказ не найден")
        return
    
    order_data = {
        'id': order_id,
        'item_id': int(row[1]) if row[1] else 0,
        'renter_id': int(row[2]) if row[2] else 0,
        'owner_id': int(row[3]) if row[3] else 0,
        'start_datetime': row[4],
        'end_datetime': row[5],
        'total_price': int(row[7]) if row[7] else 0,
    }
    
    # Обновляем статус
    orders_sheet.update_cell(order_id, 9, "В обсуждении")
    
    items = get_items_from_sheets()
    item = next((i for i in items if i['id'] == order_data['item_id']), {})
    
    await context.bot.send_message(
        chat_id=order_data['renter_id'],
        text=f"✅ Арендодатель готов обсуждать детали!\n\n📞 Его контакт: {item.get('contact', 'не указан')}\n\nОбсудите условия аренды напрямую."
    )
    
    renter_contact = f"@{query.from_user.username}" if query.from_user.username else f"ID: {query.from_user.id}"
    await query.message.reply_text(
        f"✅ Вы начали обсуждение!\n\n📞 Контакт арендатора: {renter_contact}\n\nПосле передачи техники нажмите ниже.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Техника выдана", callback_data=f"issued_{order_data['id']}")]])
    )

async def reject_order(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])
    
    all_rows = orders_sheet.get_all_values()
    if order_id < len(all_rows):
        renter_id = int(all_rows[order_id][2]) if len(all_rows[order_id]) > 2 else 0
        orders_sheet.update_cell(order_id, 9, "Отклонена")
        if renter_id:
            await context.bot.send_message(chat_id=renter_id, text="❌ Арендодатель отклонил вашу заявку.")
    
    await query.message.reply_text("❌ Заявка отклонена.")

async def mark_issued(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])
    orders_sheet.update_cell(order_id, 9, "Техника выдана")
    await query.message.reply_text(
        "✅ Техника выдана.\n\nПосле возврата нажмите:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Техника возвращена", callback_data=f"returned_{order_id}")]])
    )

async def mark_returned(update: Update, context):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])
    orders_sheet.update_cell(order_id, 9, "Завершён")
    await query.message.reply_text("✅ Техника возвращена. Спасибо!")

# ========== МОИ ОБЪЯВЛЕНИЯ (callback) ==========
async def my_ads_callback(update: Update, context):
    user_id = update.effective_user.id
    items = get_items_from_sheets()
    my_items = [item for item in items if item.get('owner_id') == user_id]
    
    if not my_items:
        await update.callback_query.message.reply_text("📋 У вас пока нет объявлений.")
        return
    
    for item in my_items:
        text = f"📷 *{item['name']}*\n💰 {item['price']} ₽/час\n⏰ Мин. аренда: {item.get('min_hours', 1)} час(ов)\n📍 {item['city']}"
        keyboard = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{item['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if item.get('photo'):
            try:
                await update.callback_query.message.reply_photo(photo=item['photo'], caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            except Exception:
                await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def delete_item(update: Update, context):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split('_')[1])
    try:
        items_sheet.delete_row(item_id)
        await query.edit_message_text("🗑 Объявление удалено.")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")

# ========== ПОМОЩЬ ==========
async def help_start(update: Update, context):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "🆘 Напишите ваш вопрос или проблему.\n\nЯ перешлю его менеджеру.\n\n✏️ Введите ваше сообщение:"
        )
    else:
        await update.message.reply_text(
            "🆘 Напишите ваш вопрос или проблему.\n\nЯ перешлю его менеджеру.\n\n✏️ Введите ваше сообщение:"
        )
    return HELP_MESSAGE

async def help_send(update: Update, context):
    user_message = update.message.text
    user = update.effective_user
    user_link = f"@{user.username}" if user.username else f"Пользователь {user.id}"
    
    if not MANAGER_IDS:
        await update.message.reply_text("🆘 Менеджер пока не назначен.")
        return ConversationHandler.END
    
    success_count = 0
    for manager_id in MANAGER_IDS:
        try:
            keyboard = [[InlineKeyboardButton(f"✏️ Ответить", callback_data=f"reply_{user.id}")]]
            await context.bot.send_message(
                chat_id=manager_id,
                text=f"📩 *Новое обращение*\n👤 {user_link}\n🆔 {user.id}\n📝 {user_message}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            success_count += 1
        except Exception as e:
            print(f"Ошибка: {e}")
    
    await update.message.reply_text(f"🆘 Сообщение отправлено {success_count} менеджер(ам).\n\nОтвет поступит в ближайшее время.")
    return ConversationHandler.END

async def help_cancel(update: Update, context):
    await update.message.reply_text("❌ Отправка отменена.")
    return ConversationHandler.END

# ========== ОТВЕТ МЕНЕДЖЕРА ==========
async def reply_button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in MANAGER_IDS:
        await query.message.reply_text("❌ У вас нет прав.")
        return
    
    user_id = int(query.data.split('_')[1])
    context.user_data['replying_to'] = user_id
    await query.message.reply_text(f"✏️ Введите ответ для пользователя {user_id}:")
    return AWAITING_REPLY_TEXT

async def send_reply_to_user(update: Update, context):
    user_id = context.user_data.get('replying_to')
    if not user_id:
        await update.message.reply_text("❌ Ошибка")
        return
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📩 *Ответ от поддержки:*\n\n{update.message.text}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Ответ отправлен.")
        context.user_data['replying_to'] = None
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    return ConversationHandler.END

async def cancel_reply(update: Update, context):
    context.user_data['replying_to'] = None
    await update.message.reply_text("❌ Ответ отменён.")
    return ConversationHandler.END

# ========== ДОБАВЛЕНИЕ ТЕХНИКИ ==========
async def add_item_start(update: Update, context):
    await update.callback_query.message.reply_text("Введите НАЗВАНИЕ техники:")
    return NAME

async def add_item_name(update: Update, context):
    context.user_data['new_name'] = update.message.text
    await update.message.reply_text("Отправьте ФОТО техники:")
    return PHOTO

async def add_item_photo(update: Update, context):
    context.user_data['new_photo'] = update.message.photo[-1].file_id
    await update.message.reply_text("Введите ЦЕНУ за час:")
    return PRICE

async def add_item_price(update: Update, context):
    context.user_data['new_price'] = update.message.text
    await update.message.reply_text("Введите минимальное количество часов (1-24):")
    return MIN_HOURS

async def add_item_min_hours(update: Update, context):
    context.user_data['new_min_hours'] = update.message.text
    await update.message.reply_text("Введите ГОРОД:")
    return CITY

async def add_item_city(update: Update, context):
    context.user_data['new_city'] = update.message.text
    await update.message.reply_text("Введите ОПИСАНИЕ:")
    return DESCRIPTION

async def add_item_description(update: Update, context):
    context.user_data['new_description'] = update.message.text
    await update.message.reply_text("Введите КОНТАКТ (телефон или @username):")
    return CONTACT

async def add_item_contact(update: Update, context):
    save_item_to_sheets(
        update.effective_user.id,
        context.user_data['new_name'],
        context.user_data.get('new_photo', ''),
        context.user_data['new_price'],
        context.user_data.get('new_min_hours', '1'),
        context.user_data['new_city'],
        context.user_data['new_description'],
        update.message.text
    )
    await update.message.reply_text("✅ Техника добавлена!")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

async def unknown(update: Update, context):
    await update.message.reply_text("❓ Напишите /start")

# ========== ЗАПУСК БОТА ==========
async def run_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("my_ads", my_ads_command))
    application.add_handler(CommandHandler("my_orders", my_orders_command))
    
    application.add_handler(CallbackQueryHandler(role_choice, pattern="^role_"))
    application.add_handler(CallbackQueryHandler(catalog, pattern="^catalog$"))
    application.add_handler(CallbackQueryHandler(my_ads_callback, pattern="^my_ads$"))
    application.add_handler(CallbackQueryHandler(my_orders_command, pattern="^my_orders$"))
    application.add_handler(CallbackQueryHandler(delete_item, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(discuss_order, pattern="^discuss_"))
    application.add_handler(CallbackQueryHandler(reject_order, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(mark_issued, pattern="^issued_"))
    application.add_handler(CallbackQueryHandler(mark_returned, pattern="^returned_"))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_booking, pattern="^book_")],
        states={SELECT_DAY: [CallbackQueryHandler(select_day, pattern="^day_")], SELECT_HOUR: [CallbackQueryHandler(select_hour, pattern="^hour_")], SELECT_DURATION: [CallbackQueryHandler(select_duration, pattern="^dur_")]},
        fallbacks=[],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_item_start, pattern="^add_item$")],
        states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_name)], PHOTO: [MessageHandler(filters.PHOTO, add_item_photo)], PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_price)], MIN_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_min_hours)], CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_city)], DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_description)], CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_contact)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(help_start, pattern="^help$"), CommandHandler("help", help_start)],
        states={HELP_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, help_send)]},
        fallbacks=[CommandHandler("cancel", help_cancel)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(reply_button_handler, pattern="^reply_")],
        states={AWAITING_REPLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_reply_to_user)]},
        fallbacks=[CommandHandler("cancel", cancel_reply)],
    ))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    print("🚀 Бот запущен!")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    while True:
        await asyncio.sleep(1)

# ========== FLASK ==========
@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    init_google_sheets()
    threading.Thread(target=lambda: asyncio.run(run_bot()), daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
