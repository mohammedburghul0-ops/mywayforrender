import os
import re
import time
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import aiosqlite
import uvicorn
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from fastapi import FastAPI, Request

from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# 1. نظام حفظ حالة المستخدم (FSM Persistence) لضمان عدم ضياع مرحلة التسجيل
class JSONStorage(BaseStorage):
    def __init__(self, file_path: str = "fsm_data.json"):
        self.file_path = file_path
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: pass
        return {}

    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f)

    async def set_state(self, key: StorageKey, state: str = None) -> None:
        k = f"{key.bot_id}_{key.chat_id}_{key.user_id}"
        if k not in self.data: self.data[k] = {"state": None, "data": {}}
        self.data[k]["state"] = state.state if hasattr(state, 'state') else state
        self._save()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        k = f"{key.bot_id}_{key.chat_id}_{key.user_id}"
        return self.data.get(k, {}).get("state", None)

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        k = f"{key.bot_id}_{key.chat_id}_{key.user_id}"
        if k not in self.data: self.data[k] = {"state": None, "data": {}}
        self.data[k]["data"] = data
        self._save()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        k = f"{key.bot_id}_{key.chat_id}_{key.user_id}"
        return self.data.get(k, {}).get("data", {})

    async def close(self) -> None:
        pass

# ربط البوت بالذاكرة الدائمة
dp = Dispatcher(storage=JSONStorage())

class MenuState(StatesGroup):
    user_main = State()
    admin_main = State()
    admin_student_view = State()
    about_us = State()
    
    courses_categories = State()
    viewing_category = State()
    
    payment_methods = State()
    electronic_payment = State()
    waiting_for_payment_receipt = State()
    
    reg_q1_name = State()
    reg_q2_mother = State()
    reg_q3_address = State()
    reg_q4_birth = State()
    reg_q5_student_phone = State()
    reg_q6_parent_phone = State()
    reg_q7_first_time = State()
    reg_q8_student_type = State()
    reg_q9_branch = State()
    reg_q10_subjects = State()
    
    support_menu = State()
    viewing_numbers = State()
    waiting_for_inquiry = State()
    admin_replying_to_inquiry = State()
    
    admin_edit_prices_categories = State()
    admin_managing_category = State()
    admin_waiting_for_new_package = State()
    admin_waiting_for_edit_package = State()

async def init_db():
    try:
        async with aiosqlite.connect(Config.DB_NAME) as db:
            await db.execute('PRAGMA journal_mode=WAL;')
            await db.execute('PRAGMA synchronous=NORMAL;')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    is_admin INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    last_reg_time INTEGER DEFAULT 0,
                    last_inq_time INTEGER DEFAULT 0
                )
            ''')
            try: await db.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')
            except Exception: pass
            try: await db.execute('ALTER TABLE users ADD COLUMN last_reg_time INTEGER DEFAULT 0')
            except Exception: pass
            try: await db.execute('ALTER TABLE users ADD COLUMN last_inq_time INTEGER DEFAULT 0')
            except Exception: pass
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    button_name TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS package_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL, 
                    category TEXT NOT NULL,
                    package_id INTEGER,
                    old_button_name TEXT,
                    old_content TEXT,
                    new_button_name TEXT,
                    new_content TEXT
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS inquiries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    full_name TEXT,
                    username TEXT,
                    message_text TEXT NOT NULL
                )
            ''')
            
            await db.commit()
            
            async with db.execute('SELECT COUNT(*) FROM packages') as cursor:
                count = (await cursor.fetchone())[0]
                if count == 0:
                    await seed_default_packages(db)
                    
    except Exception as e:
        logger.error(f"Database initialization error: {e}")

async def seed_default_packages(db: aiosqlite.Connection):
    cat_science = "🔬 الفرع العلمي"
    defaults = [
        (cat_science, "☁️ الدورة الشتوية", "☁️ *الدورة الشتوية*:\nيتم فيها إعطاء كامل المنهاج من الكتاب المدرسي كاملاً وتبقى الدروس متاحة للطلاب حتى نهاية امتاحنه الأخير.\n\n*الرياضيات كاملة* 👈🏻 6500 ل.س\nالتحليل 👈🏻 4200 ل.س\nالأشعة 👈🏻1800 ل.س\nالجبر 👈🏻 2400 ل.س\n\n*الفيزياء كاملة* 👈🏻 5500 ل.س\nالميكانيك 👈🏻 3000 ل.س\nالكهرباء والإلكترونيات 👈🏻 3000 ل.س\n\nالأحياء 👈🏻 4500 ل.س\nالكيمياء 👈🏻 3500 ل.س\n\nاللغة العربية 👈🏻 3500 ل.س\nاللغة الإنجليزية 👈🏻 4000 ل.س\nاللغة الفرنسية 👈🏻 3500 ل.س\n\nالتربية الإسلامية 👈🏻 1500 ل.س\n\n🎯 *العرض*: اشترك بكامل الدورة الشتوية بـ29 ألف و 900 ليرة ‼️\n\n🎯 *باقة اللغات*: (انكليزي - عربي - فرنسي) بـ7500 ل.س ‼️"),
        (cat_science, "☀️ الدورة الصيفية", "☀️ *الدورة الصيفية*:\nتبدأ في 15/6 وحتى 1/9، يتم فيها تأسيس الطالب من الصفر بكل مادة ويأخذ فيها شرح 40% من المادة ويصبح جاهزاً للدخول للدورة الشتوية.\n\nاﻟﺮﻳﺎﺿﻴﺎت ﻛﺎﻣﻠﺔ 👈🏻 3500 ل.س\nاﻟﻔﻴﺰﻳﺎء ﻛﺎﻣﻠﺔ 👈🏻 2700 ل.س\nاﻷﺣﻴﺎء 👈🏻 2200 ل.س\nاﻟﻜﻴﻤﻴﺎء 👈🏻 1700 ل.س\nاﻟﻠﻐﺔ اﻟﻌﺮﺑﻴﺔ 👈🏻 1700 ل.س\nاﻟﻠﻐﺔ اﻻﻧﻜﻠﻴﺰﻳﺔ 👈🏻 2000 ل.س\nاﻟﻠﻐﺔ اﻟﻔﺮﻧﺴﻴﺔ 👈🏻 1700 ل.س\n\n🎯 *العرض*: اشترك بكامل المواد في الدورة الصيفية\nبسعر 9,900 بدل -15,500- ‼️\n\n🎯 *ﺑﺎﻗﺔ اﻟﻤﻮاد اﻟﻌﻠﻤﻴﺔ*: \nرياضيات + فيزياء + كيمياء\nبسعر 6,000 بدل -7,900- ‼️\n\n🎯 *ﺑﺎﻗﺔ اللغات*:\nعربي + انجليزي + فرنسي \nبسعر 4,500 بدل  -5400- ‼️"),
        (cat_science, "العرض الشامل 🔥", "*العرض الشامل* 🔥\n\nاشترك بكامل المواد *الدورة الصيفية والدورة الشتوية* \nلتحصل على عرض *35 ألف* بدل من -45 ألف- ⭐️\n\n*الأسعار كلها بالليرة السورية الجديدة*")
    ]
    for category, btn_name, content in defaults:
        await db.execute('INSERT INTO packages (category, button_name, content) VALUES (?, ?, ?)', (category, btn_name, content))
    await db.commit()

async def get_packages_by_category(category: str):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT id, button_name, content FROM packages WHERE category = ?', (category,)) as cursor:
            return await cursor.fetchall()

async def get_package_by_id(pkg_id: int):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT id, category, button_name, content FROM packages WHERE id = ?', (pkg_id,)) as cursor:
            return await cursor.fetchone()

async def record_history(db: aiosqlite.Connection, action: str, category: str, pkg_id: int=None, old_btn: str=None, old_content: str=None, new_btn: str=None, new_content: str=None):
    await db.execute('''
        INSERT INTO package_history (action, category, package_id, old_button_name, old_content, new_button_name, new_content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (action, category, pkg_id, old_btn, old_content, new_btn, new_content))

async def add_package(category: str, btn_name: str, content: str):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        cursor = await db.execute('INSERT INTO packages (category, button_name, content) VALUES (?, ?, ?)', (category, btn_name, content))
        pkg_id = cursor.lastrowid
        await record_history(db, 'ADD', category, pkg_id, new_btn=btn_name, new_content=content)
        await db.commit()

async def update_package(pkg_id: int, new_btn: str, new_content: str):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        pkg = await get_package_by_id(pkg_id)
        if pkg:
            _, category, old_btn, old_content = pkg
            await db.execute('UPDATE packages SET button_name = ?, content = ? WHERE id = ?', (new_btn, new_content, pkg_id))
            await record_history(db, 'EDIT', category, pkg_id, old_btn, old_content, new_btn, new_content)
            await db.commit()

async def delete_package(pkg_id: int):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        pkg = await get_package_by_id(pkg_id)
        if pkg:
            _, category, old_btn, old_content = pkg
            await db.execute('DELETE FROM packages WHERE id = ?', (pkg_id,))
            await record_history(db, 'DELETE', category, pkg_id, old_btn, old_content)
            await db.commit()

async def undo_last_action(category: str) -> bool:
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT id, action, package_id, old_button_name, old_content, new_button_name, new_content FROM package_history WHERE category = ? ORDER BY id DESC LIMIT 1', (category,)) as cursor:
            last_action = await cursor.fetchone()
            
        if not last_action:
            return False
            
        history_id, action, pkg_id, old_btn, old_content, new_btn, new_content = last_action
        
        if action == 'ADD':
            await db.execute('DELETE FROM packages WHERE id = ?', (pkg_id,))
        elif action == 'EDIT':
            await db.execute('UPDATE packages SET button_name = ?, content = ? WHERE id = ?', (old_btn, old_content, pkg_id))
        elif action == 'DELETE':
            await db.execute('INSERT INTO packages (category, button_name, content) VALUES (?, ?, ?)', (category, old_btn, old_content))
            
        await db.execute('DELETE FROM package_history WHERE id = ?', (history_id,))
        await db.commit()
        return True

async def get_ban_status(user_id: int) -> bool:
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False

async def set_ban_status(user_id: int, status: int):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        await db.execute('INSERT INTO users (user_id, is_banned) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET is_banned=excluded.is_banned', (user_id, status))
        await db.commit()

async def get_all_banned_users() -> list:
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT user_id FROM users WHERE is_banned = 1') as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def add_inquiry(user_id: int, full_name: str, username: str, message_text: str):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        await db.execute('INSERT INTO inquiries (user_id, full_name, username, message_text) VALUES (?, ?, ?, ?)', (user_id, full_name, username, message_text))
        await db.commit()

async def get_and_delete_oldest_inquiry():
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT id, user_id, full_name, username, message_text FROM inquiries ORDER BY id ASC LIMIT 1') as cursor:
            row = await cursor.fetchone()
        if row:
            await db.execute('DELETE FROM inquiries WHERE id = ?', (row[0],))
            await db.commit()
            return row
        return None

async def get_user_cooldowns(user_id: int):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        async with db.execute('SELECT last_reg_time, last_inq_time FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row: return row
            await db.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
            await db.commit()
            return (0, 0)

async def update_user_cooldown(user_id: int, col: str, val: int):
    async with aiosqlite.connect(Config.DB_NAME) as db:
        await db.execute(f'UPDATE users SET {col} = ? WHERE user_id = ?', (val, user_id))
        await db.commit()


# Middlewares
user_latest_msg = {}
class BurstDeduplicationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        user_id = event.from_user.id
        msg_id = event.message_id
        
        # حفظ رقم آخر رسالة أرسلها المستخدم لفلترة الانهمار أثناء إعادة التشغيل
        if user_id not in user_latest_msg or msg_id > user_latest_msg[user_id]:
            user_latest_msg[user_id] = msg_id
            
        await asyncio.sleep(0.7)
        
        # إذا تبين أن هذه الرسالة ليست الأخيرة، يتم تجاهلها
        if user_latest_msg[user_id] > msg_id:
            return 
            
        return await handler(event, data)

class PrivateChatMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        if event.chat.type != "private":
            return
        return await handler(event, data)

class BannedMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        user_id = event.from_user.id
        is_banned = await get_ban_status(user_id)
        if is_banned:
            return
        return await handler(event, data)

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1.2):
        self.limit = limit
        self.users_cache = {}

    async def __call__(self, handler, event: types.Message, data: dict):
        user_id = event.from_user.id
        now = asyncio.get_event_loop().time()
        last_time = self.users_cache.get(user_id, 0)
        if now - last_time < self.limit:
            return 
        self.users_cache[user_id] = now
        return await handler(event, data)

class DefaultStateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: dict):
        state: FSMContext = data.get("state")
        if state and getattr(event, "text", None):
            current_state = await state.get_state()
            if current_state is None:
                user_id = event.from_user.id
                is_admin = user_id in Config.ADMIN_IDS
                new_state = MenuState.admin_main if is_admin else MenuState.user_main
                await state.set_state(new_state)
                data["raw_state"] = new_state.state 
        return await handler(event, data)

dp.message.middleware(PrivateChatMiddleware())
dp.message.middleware(BannedMiddleware())
dp.message.middleware(BurstDeduplicationMiddleware())
dp.callback_query.middleware(BannedMiddleware())
dp.message.middleware(ThrottlingMiddleware())
dp.message.outer_middleware(DefaultStateMiddleware())

def parse_custom_markdown(text: str) -> str:
    text = re.sub(r'\*(.*?)\*', r'<b>\1</b>', text)
    text = re.sub(r'-(.*?)-', r'<s>\1</s>', text)
    return text

def extract_button_name(text: str) -> str:
    first_line = text.strip().split('\n')[0]
    clean_name = first_line.replace('*', '').replace('-', '')
    return clean_name.rstrip(':').strip()

def normalize_arabic_numbers(text: str) -> str:
    arabic_to_english = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(arabic_to_english)

async def safe_send(message: types.Message, text: str, reply_markup=None):
    try:
        await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await safe_send(message, text, reply_markup)
    except Exception as e:
        logger.error(f"Send Error: {e}")

def get_user_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="ℹ️ 1. من نحن؟"), KeyboardButton(text="📚 2. الدورات والعروض")],
        [KeyboardButton(text="👨‍🏫 3. كادرنا التدريسي"), KeyboardButton(text="💳 4. طرق الدفع والتسجيل")],
        [KeyboardButton(text="🏆 5. لوحة الشرف"), KeyboardButton(text="📞 6. الدعم الفني والمساعدة")],
        [KeyboardButton(text="📲 7. رابط تحميل التطبيق")]
    ], resize_keyboard=True)

def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✏️ تعديل الأسعار"), KeyboardButton(text="💬 اسئلة الطلاب")],
        [KeyboardButton(text="🚫 الطلاب المحظورين"), KeyboardButton(text="📱 أزرار الطالب")]
    ], resize_keyboard=True)

def get_admin_user_view_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔙 العودة إلى أزرار الأدمن")],
        [KeyboardButton(text="ℹ️ 1. من نحن؟"), KeyboardButton(text="📚 2. الدورات والعروض")],
        [KeyboardButton(text="👨‍🏫 3. كادرنا التدريسي"), KeyboardButton(text="💳 4. طرق الدفع والتسجيل")],
        [KeyboardButton(text="🏆 5. لوحة الشرف"), KeyboardButton(text="📞 6. الدعم الفني والمساعدة")],
        [KeyboardButton(text="📲 7. رابط تحميل التطبيق")]
    ], resize_keyboard=True)

def get_categories_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔬 الفرع العلمي"), KeyboardButton(text="🎧 علمي (مستمع)")],
        [KeyboardButton(text="📖 الفرع الأدبي"), KeyboardButton(text="🎓 الصف التاسع الأساسي")],
        [KeyboardButton(text="🎒 الصفوف الانتقالية")],
        [KeyboardButton(text="🔙 رجوع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_dynamic_items_kb(packages):
    kb = []
    for i in range(0, len(packages), 2):
        row = [KeyboardButton(text=pkg[1]) for pkg in packages[i:i+2]]
        kb.append(row)
    kb.append([KeyboardButton(text="🔙 رجوع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_manage_category_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="↩️ التراجع عن آخر تعديل"), KeyboardButton(text="➕ إضافة زر جديد")],
        [KeyboardButton(text="🔙 رجوع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_payment_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 دمشق (مباشر)"), KeyboardButton(text="💸 حوالات مالية")],
        [KeyboardButton(text="📱 دفع إلكتروني"), KeyboardButton(text="🗺 المحافظات الشرقية")],
        [KeyboardButton(text="🧾 إرسال إشعار الدفع والتسجيل")],
        [KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_electronic_payment_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔴 سريتيل كاش"), KeyboardButton(text="MTN كاش 🟡")],
        [KeyboardButton(text="🟢 شام كاش")],
        [KeyboardButton(text="🏦 بنك سورية الدولي الإسلامي"), KeyboardButton(text="🏦 بنك الشام")],
        [KeyboardButton(text="🔙 الرجوع لطرق الدفع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_receipt_upload_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔙 الرجوع لطرق الدفع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_reg_back_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]], resize_keyboard=True)

def get_back_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]], resize_keyboard=True)

def get_support_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 أرقام منصة طريقي")],
        [KeyboardButton(text="إرسال استفسار عبر البوت 💬")],
        [KeyboardButton(text="🔙 رجوع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_support_back_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔙 رجوع"), KeyboardButton(text="🏠 عودة للقائمة الرئيسية")]
    ], resize_keyboard=True)

def get_inline_manage_item_kb(pkg_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ تعديل", callback_data=f"edit_{pkg_id}"), InlineKeyboardButton(text="🗑️ حذف", callback_data=f"del_{pkg_id}")]
    ])

def get_inline_confirm_del_kb(pkg_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأكيد الحذف", callback_data=f"confdel_{pkg_id}"), InlineKeyboardButton(text="❌ إلغاء", callback_data=f"cancel_{pkg_id}")]
    ])

def get_inline_submit_receipt_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="اضغط هنا إذا قمت بالتحويل 🧾", callback_data="submit_receipt")]
    ])

def get_inline_payment_shortcut_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 طرق الدفع والتسجيل", callback_data="shortcut_payment")]
    ])

def get_q7_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ لا", callback_data="q7_no"), InlineKeyboardButton(text="✅ نعم", callback_data="q7_yes")]
    ])

def get_q8_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 حر", callback_data="q8_free"), InlineKeyboardButton(text="🏫 نظامي", callback_data="q8_regular")]
    ])

def get_q9_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔬 بكالوريا علمي", callback_data="q9_sci"), InlineKeyboardButton(text="📖 بكالوريا أدبي", callback_data="q9_lit")],
        [InlineKeyboardButton(text="🎧 علمي مستمع", callback_data="q9_listen"), InlineKeyboardButton(text="🎓 تاسع", callback_data="q9_ninth")],
        [InlineKeyboardButton(text="🎒 صف انتقالي", callback_data="q9_trans")]
    ])

# استخراج الـ file_id مسموح فقط للأدمن لتفادي التقاط صور الطلاب
@dp.message(F.photo, lambda msg: msg.from_user.id in Config.ADMIN_IDS)
async def get_photo_file_id(message: types.Message):
    file_id = message.photo[-1].file_id
    await message.answer(f"✅ تم التقاط الـ File ID بنجاح:\n\n<code>{file_id}</code>\n\nقم بنسخه ووضعه في ملف .env")

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_admin = user_id in Config.ADMIN_IDS
    await state.clear()
    
    welcome_text = "<b>بعد المسافة لا يهم الخطوة الأولى هي الأكثر صعوبة لكنها بدأت الآن .. \nأهلاً بك عزيزي الطالب في عالم الشغف والطموح معنا في منصة طريقي التعليمية.</b> 🩵"
    new_state = MenuState.admin_main if is_admin else MenuState.user_main
    await state.set_state(new_state)
    await safe_send(message, welcome_text, reply_markup=get_admin_kb() if is_admin else get_user_kb())

@dp.message(F.text == "🏠 عودة للقائمة الرئيسية")
async def cmd_home(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_admin = user_id in Config.ADMIN_IDS
    await state.clear()
    
    new_state = MenuState.admin_main if is_admin else MenuState.user_main
    await state.set_state(new_state)
    await safe_send(message, "<b>القائمة الرئيسية 🏠:</b>", reply_markup=get_admin_kb() if is_admin else get_user_kb())

@dp.message(F.text == "ℹ️ 1. من نحن؟")
async def about_us_handler(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.about_us)
    about_text = (
        f"<b>منصة طريقي</b> | أول منصة تعليمية افتراضية في سوريا 📲✨\n\n"
        f"ليش تجيب علامات عادية إذا فيك تجيب علامات تامّة بتحققلك حلمك وبتخلي أهلك فخورين فيك؟!🔥\n"
        f"لكل طلاب البكالوريا والتاسع في سوريا (وجميع صفوف الإعدادي والثانوي) تأكدوا أنو.. المستقبل بيبدأ بطريقي...\n\n"
        f"📘 فيسبوك 👈🏻 <a href='{Config.FB_PAGE}'>منصة طريقي التعليمية</a>\n\n"
        f"👥 مجموعة الفيسبوك 👈🏻 <a href='{Config.FB_GROUP}'>طالب بكالوريا 2025✓</a>\n\n"
        f"📸 انستغرام 👈🏻 <a href='{Config.INSTA}'>منصة طريقي التعليمية الافتراضية</a>\n\n"
        f"✈️ تلغرام 👈🏻 <a href='{Config.TELEGRAM}'>منصة طريقي التعليمية الافتراضية</a>"
    )
    await safe_send(message, about_text, reply_markup=get_back_kb())

@dp.message(F.text == "📲 7. رابط تحميل التطبيق")
async def app_download_handler(message: types.Message, state: FSMContext):
    await safe_send(message, "جاري إعداد الروابط...", reply_markup=get_back_kb())
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 أندرويد", callback_data="app_android"),
         InlineKeyboardButton(text="🍎 آيفون", callback_data="app_ios")]
    ])
    await safe_send(message, "هل جهازك أندرويد أم آيفون؟", reply_markup=ikb)

@dp.callback_query(F.data.in_(["app_android", "app_ios"]))
async def app_selection_cb(callback: CallbackQuery, state: FSMContext):
    is_ios = callback.data == "app_ios"
    
    title = "روابط تطبيقات الآيفون 🍎:" if is_ios else "روابط تطبيقات الأندرويد 📱:"
    link_student = "https://apps.apple.com/us/app/منصة-طريقي-التعليمية/id6468575211" if is_ios else "https://play.google.com/store/apps/details?id=com.icr.mywayedu"
    link_parent = "https://apps.apple.com/us/app/طريقي-ولي-الأمر/id6757636501" if is_ios else "https://play.google.com/store/apps/details?id=com.icr.mywayguardian"
    
    text = (
        f"التطبيق الخاص بالطالب:\n"
        f"👈🏻 <a href='{link_student}'>اضغط هنا لتحميل التطبيق الخاص بالطالب</a>\n\n"
        f"التطبيق الخاص بولي الأمر:\n"
        f"👈🏻 <a href='{link_parent}'>اضغط هنا لتحميل التطبيق الخاص بولي الأمر</a>"
    )
    
    await callback.message.edit_text(title)
    await safe_send(callback.message, text)
    
    await asyncio.sleep(0.5)
    
    user_id = callback.from_user.id
    is_admin = user_id in Config.ADMIN_IDS
    new_state = MenuState.admin_main if is_admin else MenuState.user_main
    await state.set_state(new_state)
    await safe_send(callback.message, "<b>القائمة الرئيسية 🏠:</b>", reply_markup=get_admin_kb() if is_admin else get_user_kb())
    await callback.answer()

@dp.message(F.text == "📞 6. الدعم الفني والمساعدة", StateFilter(MenuState.user_main, MenuState.admin_student_view))
async def support_menu_handler(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.support_menu)
    await safe_send(message, "📞 <b>قسم الدعم الفني والمساعدة:</b>\nاختر من القائمة أدناه:", reply_markup=get_support_kb())

@dp.message(MenuState.support_menu)
async def process_support_menu(message: types.Message, state: FSMContext):
    if message.text == "📱 أرقام منصة طريقي":
        await state.set_state(MenuState.viewing_numbers)
        text = (
            "<b>أرقام منصة طريقي التعليمية:</b>\n\n"
            "يجب حفظها لديكم ولسنا مسؤولين عن أي أرقام اخرى❕\n\n"
            "<b>رقم المتابعة والاستفسار (مكالمات فقط 📞):</b>\n"
            "<code>0947050592</code>\n\n"
            "<b>رقم خاص بقسم التسجيل:</b>\n"
            "<code>0947545492</code>\n\n"
            "<b>رقم القسم المالي (المحاسبة):</b>\n"
            "<code>0983161668</code>\n\n"
            "<b>رقم خاص بالإدارة (للضرورة فقط):</b>\n"
            "<code>0937267466</code>\n\n"
            "في النهاية نحن موجودون لخدمتكم لإيصالكم إلى  أحلامكم، ونحن معكم حتى اخر يوم في الامتحانات ونعد من يلتزم معنا ويبتعد عن التراكم أنه سيصل بإذن الله تعالى إلى حلمه، الآن المستقبل يبدأ بطريقي.. 😊"
        )
        await safe_send(message, text, reply_markup=get_support_back_kb())
    elif message.text == "إرسال استفسار عبر البوت 💬":
        cooldowns = await get_user_cooldowns(message.from_user.id)
        if time.time() - cooldowns[1] < 86400:
            await safe_send(message, "⏳ <b>عذراً، يمكنك إرسال استفسار واحد فقط كل 24 ساعة.</b>\n(يمكنك إرسال استفسار جديد في حال تم الرد عليك أو تم رفض استفسارك السابق).")
            return
        await state.set_state(MenuState.waiting_for_inquiry)
        await safe_send(message, "💬 <b>اكتب استفسارك الآن في رسالة واحدة وسيقوم الدعم الفني بالرد عليك في أقرب وقت:</b>", reply_markup=get_support_back_kb())
    elif message.text == "🔙 رجوع":
        await cmd_home(message, state)
    elif message.text == "🏠 عودة للقائمة الرئيسية":
        await cmd_home(message, state)
    else:
        await catch_all_unrecognized(message, state)

@dp.message(MenuState.viewing_numbers)
async def process_viewing_numbers(message: types.Message, state: FSMContext):
    if message.text == "🔙 رجوع":
        await support_menu_handler(message, state)
    elif message.text == "🏠 عودة للقائمة الرئيسية":
        await cmd_home(message, state)
    else:
        await catch_all_unrecognized(message, state)

@dp.message(MenuState.waiting_for_inquiry)
async def process_inquiry_submission(message: types.Message, state: FSMContext):
    if message.text in ["🔙 رجوع", "🏠 عودة للقائمة الرئيسية"]:
        if message.text == "🔙 رجوع":
            await support_menu_handler(message, state)
        else:
            await cmd_home(message, state)
        return
        
    if not message.text:
        await safe_send(message, "⚠️ يرجى إرسال الاستفسار كنص مكتوب.")
        return

    full_name = message.from_user.full_name
    username = message.from_user.username or "بدون_معرف"
    await add_inquiry(message.from_user.id, full_name, username, message.text)
    
    await update_user_cooldown(message.from_user.id, 'last_inq_time', int(time.time()))
    
    user_id = message.from_user.id
    is_admin = user_id in Config.ADMIN_IDS
    new_state = MenuState.admin_main if is_admin else MenuState.user_main
    await state.set_state(new_state)
    
    await safe_send(message, "✅ <b>تم إرسال استفسارك بنجاح للإدارة. وسيتم الرد عليك عبر هذا البوت قريباً.</b>", reply_markup=get_admin_kb() if is_admin else get_user_kb())

@dp.message(F.text == "💬 اسئلة الطلاب", MenuState.admin_main)
async def admin_view_inquiries(message: types.Message, state: FSMContext):
    inq = await get_and_delete_oldest_inquiry()
    if not inq:
        await safe_send(message, "✅ <b>لا توجد استفسارات جديدة حالياً.</b>")
        return
        
    inq_id, u_id, fname, uname, text = inq
    
    uname_part = f" (@{uname})" if uname != "بدون_معرف" else ""
    
    report = (
        f"📩 <b>استفسار جديد من طالب!</b>\n\n"
        f"👤 <b>الطالب:</b> {fname}{uname_part}\n"
        f"🆔 <b>الآيدي:</b> <code>{u_id}</code>\n\n"
        f"📝 <b>الاستفسار:</b>\n{text}"
    )
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 رد", callback_data=f"reply_inq_{u_id}"),
         InlineKeyboardButton(text="❌ رفض", callback_data=f"rej_inq_{u_id}")],
        [InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={u_id}")],
        [InlineKeyboardButton(text="🚫 حظر الطالب", callback_data=f"ban_inq_{u_id}")]
    ])
    
    await safe_send(message, report, reply_markup=ikb)

@dp.callback_query(F.data.startswith("reply_inq_"), MenuState.admin_main)
async def admin_reply_inquiry_cb(callback: CallbackQuery, state: FSMContext):
    u_id = int(callback.data.split("_")[2])
    await state.update_data(reply_to_user_id=u_id, reply_msg_id=callback.message.message_id, reply_msg_text=callback.message.html_text)
    await state.set_state(MenuState.admin_replying_to_inquiry)
    
    await safe_send(callback.message, f"✍️ <b>اكتب ردك الآن ليتم إرساله للطالب صاحب الآيدي ({u_id}):</b>\n(أو اضغط 🔙 إلغاء للعودة)", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 إلغاء")]], resize_keyboard=True))
    await callback.answer()

@dp.message(MenuState.admin_replying_to_inquiry)
async def admin_process_reply_inquiry(message: types.Message, state: FSMContext):
    if message.text == "🔙 إلغاء":
        await state.set_state(MenuState.admin_main)
        await safe_send(message, "تم الإلغاء.", reply_markup=get_admin_kb())
        return
        
    data = await state.get_data()
    u_id = data.get("reply_to_user_id")
    
    if u_id:
        try:
            await bot.send_message(u_id, f"📩 <b>رد من الدعم الفني لاستفسارك:</b>\n\n{message.text}")
            await update_user_cooldown(u_id, 'last_inq_time', 0)
            await safe_send(message, "✅ <b>تم إرسال الرد للطالب بنجاح.</b>", reply_markup=get_admin_kb())
            
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={u_id}")]])
                await bot.edit_message_text(chat_id=message.chat.id, message_id=data.get('reply_msg_id'), text=data.get('reply_msg_text') + "\n\n✅ <b>تم الرد على الطالب.</b>", reply_markup=kb)
            except Exception: pass
            
        except Exception as e:
            logger.error(f"Failed to send reply to user: {e}")
            await safe_send(message, "⚠️ <b>فشل إرسال الرد للطالب (قد يكون قام بحظر البوت).</b>", reply_markup=get_admin_kb())
    
    await state.set_state(MenuState.admin_main)

@dp.callback_query(F.data.startswith("rej_inq_"), MenuState.admin_main)
async def admin_reject_inquiry_cb(callback: CallbackQuery):
    u_id = int(callback.data.split("_")[2])
    await update_user_cooldown(u_id, 'last_inq_time', 0)
    try:
        await bot.send_message(u_id, "❌ <b>تم رفض استفسارك من قبل الإدارة، يرجى التأكد من صياغته بشكل صحيح أو مراجعة الأسئلة الشائعة.</b>")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={u_id}")]])
        await callback.message.edit_text(callback.message.html_text + "\n\n❌ <b>تم رفض الاستفسار وإبلاغ الطالب.</b>", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("ban_inq_"), MenuState.admin_main)
async def admin_ban_inquiry_cb(callback: CallbackQuery):
    u_id = int(callback.data.split("_")[2])
    await set_ban_status(u_id, 1)
    await callback.message.edit_text(callback.message.html_text + "\n\n🚫 <b>تم حظر الطالب.</b>")
    await callback.answer()

@dp.message(F.text == "💳 4. طرق الدفع والتسجيل")
async def payment_menu_handler(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.payment_methods)
    await safe_send(message, "💳 <b>يرجى اختيار طريقة الدفع المناسبة لك:</b>", reply_markup=get_payment_kb())

@dp.message(MenuState.payment_methods)
async def process_payment_method(message: types.Message, state: FSMContext):
    if message.text == "📍 دمشق (مباشر)":
        text = "📍 <b>دمشق (مباشر)</b>: يمكنك الدفع المباشر في مركزنا في دمشق: ﻣﺮﻛﺰ ﻣﻨﺼﺔ ﻃﺮﻳﻘﻲ دﻣﺸﻖ ﻣﻨﻄﻘﺔ اﻟﺼﺎﻟﺤﻴﺔ ﻣﻘﺎﺑﻞ ﺟﺎﻣﻊ اﻟﺸﻬﺪاء بين اﻟﺴﺎﻋﺔ اﻟﺤﺎدﻳﺔ ﻋﺸﺮ ﺻﺒﺎﺣﺎً واﻟﺨﺎﻣﺴﺔ ﻣﺴﺎءً."
        await safe_send(message, text)
    elif message.text == "💸 حوالات مالية":
        text = (
            "💸 <b>حوالات مالية</b>:\n\n"
            "<b>معلومات الهرم:</b>\n"
            "يرجى تزويد موظف الهرم بالمعلومات التالية:\n"
            f"(<b>خدمة وليس حوالة</b>) لصالح منصة طريقي التعليمية، رقم مرجعي : <code>{Config.ALHARAM_REF}</code>\n\n"
            "<b>معلومات الفؤاد:</b>\n"
            "يرجى تزويد موظف الفؤاد بالمعلومات التالية:\n"
            "حوالة صادر فوري لحساب منصة طريقي.\n\n"
            "إذا قمت بالتحويل، يرجى تصوير وصل التحويل.\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text, reply_markup=get_inline_submit_receipt_kb())
    elif message.text == "📱 دفع إلكتروني":
        await state.set_state(MenuState.electronic_payment)
        await safe_send(message, "📱 <b>الدفع الإلكتروني:</b>", reply_markup=get_electronic_payment_kb())
    elif message.text == "🗺 المحافظات الشرقية":
        wa_number = Config.EAST_WA
        wa_link = f"https://wa.me/+963{wa_number.lstrip('0')}"
        text = (
            "🗺 <b>المحافظات الشرقية:</b>\n"
            "يمكن التسجيل للطلاب في مناطق الجزيرة (الحسكة - الرقة - دير الزور - القامشلي - منبج) في حال عدم توفر شركة الهرم أو الفؤاد في مناطقهم، وذلك عن طريق مركزنا المعتمد <b>دفوشكا</b>.\n"
            f"للتسجيل من فضلك تواصل على واتساب على الرقم 👈🏻 <code>{wa_number}</code>\n"
            f"🟢 للانتقال لواتساب مباشرة 👈🏻 <a href='{wa_link}'>اضغط هنا</a>\n\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text)
    elif message.text == "🧾 إرسال إشعار الدفع والتسجيل":
        cooldowns = await get_user_cooldowns(message.from_user.id)
        if time.time() - cooldowns[0] < 86400:
            await safe_send(message, "⏳ <b>لقد قمت بإرسال طلب تسجيل مسبقاً خلال الـ 24 ساعة الماضية. يرجى الانتظار لحين معالجته.</b>")
            return
        await state.set_state(MenuState.waiting_for_payment_receipt)
        await safe_send(message, "🧾 <b>يرجى إرسال صورة إشعار الدفع (صورة أو ملف):</b>", reply_markup=get_receipt_upload_kb())
    else:
        await catch_all_unrecognized(message, state)

@dp.message(MenuState.electronic_payment)
async def process_electronic_payment(message: types.Message, state: FSMContext):
    if message.text == "🔴 سريتيل كاش":
        text = (
            "🔴 <b>سريتيل كاش:</b>\n"
            "من فضلك اختر <b>الدفع اليدوي</b> وليس الدفع الإلكتروني\n"
            f"ثم حول مبلغ الاشتراك إلى الرقم 👈🏻 <code>{Config.SYRIATEL_CASH}</code>\n\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text, reply_markup=get_inline_submit_receipt_kb())
    elif message.text == "MTN كاش 🟡":
        text = (
            "🟡 <b>MTN كاش:</b>\n"
            "من فضلك، ادخل تطبيق كاش موبايل،\n"
            "نختار <b>الدفع</b> ثم <b>أدخل رقم نقطة البيع</b>\n"
            f"ثم ضع رقم نقطة البيع التالية 👈🏻 <code>{Config.MTN_CASH}</code>\n\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text, reply_markup=get_inline_submit_receipt_kb())
    elif message.text == "🟢 شام كاش":
        text = (
            "🟢 <b>شام كاش:</b>\n\n"
            "امسح الكود التالي من فضلك\n"
            "<b>أو</b>\n"
            "اضغط على الرمز التالي ليتم نسخه 👇🏻\n"
            f"<code>{Config.CHAM_CASH}</code>\n"
            "ثم افتح تطبيق شام كاش\n"
            "اضغط على <b>إرسال</b>\n"
            "اضغط على <b>اضغط لإلصاق العنوان</b>\n"
            "ثم <b>أظهر الحساب</b>.\n\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text)
        if hasattr(Config, 'CHAM_CASH_QR_FILE_ID') and Config.CHAM_CASH_QR_FILE_ID:
            try:
                await message.answer_photo(photo=Config.CHAM_CASH_QR_FILE_ID, reply_markup=get_inline_submit_receipt_kb())
            except Exception as e:
                logger.error(f"Failed to send QR via File ID: {e}")
                await safe_send(message, "⚠️ تعذر تحميل صورة QR، يرجى استخدام الرمز النصي أعلاه.", reply_markup=get_inline_submit_receipt_kb())
        else:
            await safe_send(message, "⚠️ صورة الـ QR غير متوفرة حالياً، يرجى نسخ الرمز النصي أعلاه.", reply_markup=get_inline_submit_receipt_kb())
    elif message.text == "🏦 بنك سورية الدولي الإسلامي":
        text = (
            "🏦 <b>بنك سورية الدولي الإسلامي:</b>\n"
            "اسم صاحب الحساب: <b>مؤسسة أنس أحمد التجارية</b>\n"
            f"الهاتف: <code>{Config.SIIB_PHONE}</code>\n"
            f"رقم الحساب: <code>{Config.SIIB_ACCOUNT}</code>\n\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text, reply_markup=get_inline_submit_receipt_kb())
    elif message.text == "🏦 بنك الشام":
        text = (
            "🏦 <b>بنك الشام:</b>\n"
            f"اسم صاحب الحساب: <b>{Config.CHAM_NAME}</b>\n"
            f"رقم الملف: <code>{Config.CHAM_FILE}</code>\n\n"
            "ملاحظة: <b>لا يحق للطالب استرداد قيمة الوصل بعد إنشاء الحساب لأي سبب كان</b>"
        )
        await safe_send(message, text, reply_markup=get_inline_submit_receipt_kb())
    elif message.text == "🔙 الرجوع لطرق الدفع":
        await payment_menu_handler(message, state)
    else:
        await catch_all_unrecognized(message, state)

@dp.callback_query(F.data == "submit_receipt")
async def inline_submit_receipt_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cooldowns = await get_user_cooldowns(user_id)
    if time.time() - cooldowns[0] < 86400:
        await callback.answer("⏳ لقد قمت بإرسال طلب تسجيل مسبقاً خلال الـ 24 ساعة الماضية.", show_alert=True)
        return
    await state.set_state(MenuState.waiting_for_payment_receipt)
    await safe_send(callback.message, "🧾 <b>يرجى إرسال صورة إشعار الدفع (صورة أو ملف):</b>", reply_markup=get_receipt_upload_kb())
    await callback.answer()

@dp.callback_query(F.data == "shortcut_payment")
async def inline_shortcut_payment_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MenuState.payment_methods)
    await safe_send(callback.message, "💳 <b>يرجى اختيار طريقة الدفع المناسبة لك:</b>", reply_markup=get_payment_kb())
    await callback.answer()

@dp.message(MenuState.waiting_for_payment_receipt)
async def process_receipt_submission(message: types.Message, state: FSMContext):
    if message.text == "🔙 الرجوع لطرق الدفع":
        await payment_menu_handler(message, state)
        return
    if message.text == "🏠 عودة للقائمة الرئيسية":
        await cmd_home(message, state)
        return

    if message.photo or message.document:
        if message.photo:
            file_id = message.photo[-1].file_id
            rtype = "photo"
        else:
            file_id = message.document.file_id
            rtype = "document"
            
        await state.update_data(receipt_file_id=file_id, receipt_type=rtype)
        
        await safe_send(message, "تم استلام صورة الوصل بنجاح!\nالآن، يرجى الإجابة على الأسئلة التالية لإتمام التسجيل:", reply_markup=get_reg_back_kb())
        await asyncio.sleep(0.5)
        await state.set_state(MenuState.reg_q1_name)
        await safe_send(message, "1. اسم الطالب الثلاثي: ✍️")
    else:
        await safe_send(message, "⚠️ <b>عذراً، يرجى إرسال الإشعار كصورة أو ملف حصراً.</b>")

@dp.message(StateFilter(MenuState.reg_q1_name))
async def reg_q1(message: types.Message, state: FSMContext):
    await state.update_data(q1=message.text)
    await state.set_state(MenuState.reg_q2_mother)
    await safe_send(message, "2.اسم الام: ✍️")

@dp.message(StateFilter(MenuState.reg_q2_mother))
async def reg_q2(message: types.Message, state: FSMContext):
    await state.update_data(q2=message.text)
    await state.set_state(MenuState.reg_q3_address)
    await safe_send(message, "3.مكان السكن مع المحافظة: ✍️")

@dp.message(StateFilter(MenuState.reg_q3_address))
async def reg_q3(message: types.Message, state: FSMContext):
    await state.update_data(q3=message.text)
    await state.set_state(MenuState.reg_q4_birth)
    await safe_send(message, "4.تاريخ ومكان الميلاد: ✍️")

@dp.message(StateFilter(MenuState.reg_q4_birth))
async def reg_q4(message: types.Message, state: FSMContext):
    await state.update_data(q4=message.text)
    await state.set_state(MenuState.reg_q5_student_phone)
    await safe_send(message, "5.رقم للطالب عليه واتساب: ✍️")

@dp.message(StateFilter(MenuState.reg_q5_student_phone))
async def reg_q5(message: types.Message, state: FSMContext):
    norm_phone = normalize_arabic_numbers(message.text.strip())
    if re.match(r'^\d{10}$', norm_phone):
        await state.update_data(q5=norm_phone)
        await state.set_state(MenuState.reg_q6_parent_phone)
        await safe_send(message, "6.رقم ولي الأمر عليه واتساب: ✍️")
    else:
        await safe_send(message, "⚠️ من فضلك أدخل رقماً صحيحاً مؤلفاً من 10 أرقام:")

@dp.message(StateFilter(MenuState.reg_q6_parent_phone))
async def reg_q6(message: types.Message, state: FSMContext):
    norm_phone = normalize_arabic_numbers(message.text.strip())
    if re.match(r'^\d{10}$', norm_phone):
        await state.update_data(q6=norm_phone)
        await state.set_state(MenuState.reg_q7_first_time)
        await safe_send(message, "7.هذه أول مرة تسجل لدى منصتنا؟ ✍️", reply_markup=get_q7_kb())
    else:
        await safe_send(message, "⚠️ من فضلك أدخل رقماً صحيحاً مؤلفاً من 10 أرقام:")

@dp.callback_query(StateFilter(MenuState.reg_q7_first_time), F.data.startswith("q7_"))
async def q7_cb(callback: CallbackQuery, state: FSMContext):
    answer = "نعم" if callback.data == "q7_yes" else "لا"
    await state.update_data(q7=answer)
    await callback.message.edit_text(f"7.هذه أول مرة تسجل لدى منصتنا؟ ✍️\n<b>الإجابة:</b> {answer}")
    await state.set_state(MenuState.reg_q8_student_type)
    await asyncio.sleep(0.5)
    await safe_send(callback.message, "8.هل تقديمك حر أو نظامي؟ ✍️", reply_markup=get_q8_kb())
    await callback.answer()

@dp.message(StateFilter(MenuState.reg_q7_first_time))
async def q7_text(message: types.Message, state: FSMContext):
    ans = message.text.strip()
    if ans in ["نعم", "لا"]:
        await state.update_data(q7=ans)
        await safe_send(message, f"7.هذه أول مرة تسجل لدى منصتنا؟ ✍️\n<b>الإجابة:</b> {ans}")
        await state.set_state(MenuState.reg_q8_student_type)
        await asyncio.sleep(0.5)
        await safe_send(message, "8.هل تقديمك حر أو نظامي؟ ✍️", reply_markup=get_q8_kb())
    else:
        await safe_send(message, "من فضلك اختر أحد أزرار الرسالة التالية:")
        await asyncio.sleep(0.5)
        await safe_send(message, "7.هذه أول مرة تسجل لدى منصتنا؟ ✍️", reply_markup=get_q7_kb())

@dp.callback_query(StateFilter(MenuState.reg_q8_student_type), F.data.startswith("q8_"))
async def q8_cb(callback: CallbackQuery, state: FSMContext):
    answer = "حر" if callback.data == "q8_free" else "نظامي"
    await state.update_data(q8=answer)
    await callback.message.edit_text(f"8.هل تقديمك حر أو نظامي؟ ✍️\n<b>الإجابة:</b> {answer}")
    await state.set_state(MenuState.reg_q9_branch)
    await asyncio.sleep(0.5)
    await safe_send(callback.message, "9.هل أنت طالب علمي - ادبي - تاسع - صف انتقالي؟ ✍️\n(يرجى الضغط على الزر المناسب 👇)", reply_markup=get_q9_kb())
    await callback.answer()

@dp.message(StateFilter(MenuState.reg_q8_student_type))
async def q8_text(message: types.Message, state: FSMContext):
    ans = message.text.strip()
    if ans in ["حر", "نظامي"]:
        await state.update_data(q8=ans)
        await safe_send(message, f"8.هل تقديمك حر أو نظامي؟ ✍️\n<b>الإجابة:</b> {ans}")
        await state.set_state(MenuState.reg_q9_branch)
        await asyncio.sleep(0.5)
        await safe_send(message, "9.هل أنت طالب علمي - ادبي - تاسع - صف انتقالي؟ ✍️\n(يرجى الضغط على الزر المناسب 👇)", reply_markup=get_q9_kb())
    else:
        await safe_send(message, "من فضلك اختر أحد أزرار الرسالة التالية:")
        await asyncio.sleep(0.5)
        await safe_send(message, "8.هل تقديمك حر أو نظامي؟ ✍️", reply_markup=get_q8_kb())

@dp.callback_query(StateFilter(MenuState.reg_q9_branch), F.data.startswith("q9_"))
async def q9_cb(callback: CallbackQuery, state: FSMContext):
    mapping = {
        "q9_sci": "بكالوريا علمي", "q9_lit": "بكالوريا أدبي", 
        "q9_listen": "علمي مستمع", "q9_ninth": "تاسع", "q9_trans": "صف انتقالي"
    }
    answer = mapping[callback.data]
    await state.update_data(q9=answer)
    await callback.message.edit_text(f"9.هل أنت طالب علمي - ادبي - تاسع - صف انتقالي؟ ✍️\n<b>الإجابة:</b> {answer}")
    await state.set_state(MenuState.reg_q10_subjects)
    await asyncio.sleep(0.5)
    await safe_send(callback.message, "10. اكتب لنا المواد التي تريد تسجيلها: ✍️")
    await callback.answer()

@dp.message(StateFilter(MenuState.reg_q9_branch))
async def q9_text(message: types.Message, state: FSMContext):
    ans = message.text.strip()
    valid = ["بكالوريا علمي", "بكالوريا أدبي", "علمي مستمع", "تاسع", "صف انتقالي"]
    if ans in valid:
        await state.update_data(q9=ans)
        await safe_send(message, f"9.هل أنت طالب علمي - ادبي - تاسع - صف انتقالي؟ ✍️\n<b>الإجابة:</b> {ans}")
        await state.set_state(MenuState.reg_q10_subjects)
        await asyncio.sleep(0.5)
        await safe_send(message, "10. اكتب لنا المواد التي تريد تسجيلها: ✍️")
    else:
        await safe_send(message, "من فضلك اختر أحد أزرار الرسالة التالية:")
        await asyncio.sleep(0.5)
        await safe_send(message, "9.هل أنت طالب علمي - ادبي - تاسع - صف انتقالي؟ ✍️\n(يرجى الضغط على الزر المناسب 👇)", reply_markup=get_q9_kb())

@dp.message(StateFilter(MenuState.reg_q10_subjects))
async def q10_text(message: types.Message, state: FSMContext):
    await state.update_data(q10=message.text)
    data = await state.get_data()
    user_id = message.from_user.id
    
    await update_user_cooldown(user_id, 'last_reg_time', int(time.time()))
    
    is_admin = user_id in Config.ADMIN_IDS
    await safe_send(message, "✅ <b>تم تسجيل إجاباتك وإرسالها للإدارة بنجاح. يرجى الانتظار لحين معالجة الطلب.</b>", reply_markup=get_admin_kb() if is_admin else get_user_kb())
    await state.set_state(MenuState.admin_main if is_admin else MenuState.user_main)
    
    acc_group_id = Config.ACCOUNTING_GROUP_ID
    if not acc_group_id:
        return
        
    full_name = message.from_user.full_name
    username_part = f"\nالمعرف: @{message.from_user.username}" if message.from_user.username else ""
    
    report = (
        f"🧾 <b>طلب تسجيل مالي جديد!</b>\n\n"
        f"👤 <b>حساب التلغرام:</b>\n"
        f"الآيدي: <code>{user_id}</code>\n"
        f"الاسم: {full_name}{username_part}\n\n"
        f"📝 <b>البيانات المدخلة:</b>\n"
        f"1️⃣ <b>الاسم الثلاثي:</b> {data.get('q1')}\n"
        f"2️⃣ <b>اسم الأم:</b> {data.get('q2')}\n"
        f"3️⃣ <b>السكن:</b> {data.get('q3')}\n"
        f"4️⃣ <b>الميلاد:</b> {data.get('q4')}\n"
        f"5️⃣ رقم الطالب: <code>{data.get('q5')}</code>\n"
        f"6️⃣ رقم الولي: <code>{data.get('q6')}</code>\n"
        f"7️⃣ <b>أول مرة؟:</b> {data.get('q7')}\n"
        f"8️⃣ <b>نوع التقديم:</b> {data.get('q8')}\n"
        f"9️⃣ <b>الصف:</b> {data.get('q9')}\n"
        f"🔟 <b>المواد:</b> {data.get('q10')}"
    )

    try:
        sent_media = None
        if data.get("receipt_type") == "photo":
            sent_media = await bot.send_photo(acc_group_id, data.get("receipt_file_id"))
        else:
            sent_media = await bot.send_document(acc_group_id, data.get("receipt_file_id"))
        
        media_msg_id = sent_media.message_id if sent_media else 0
        
        acc_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ قبول", callback_data=f"acc_acc_{user_id}"), InlineKeyboardButton(text="❌ رفض", callback_data=f"acc_rej_{user_id}")],
            [InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={user_id}")],
            [InlineKeyboardButton(text="🚫 حظر الطالب", callback_data=f"ask_ban_{user_id}_{media_msg_id}")]
        ])
        
        await asyncio.sleep(0.5)
        await bot.send_message(acc_group_id, report, reply_markup=acc_kb)
    except Exception as e:
        logger.error(f"Failed to forward to accounting: {e}")

@dp.callback_query(F.data.startswith("acc_acc_"))
async def acc_accept_student(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    await update_user_cooldown(user_id, 'last_reg_time', 0)
    try:
        msg_base = "✅ <b>تم قبول إشعار الدفع الخاص بك بنجاح! أهلاً بك في منصة طريقي التعليمية.</b>\n❗️<b>الرجاء قراءة رسائل إخلاء المسؤولية التالية بعناية:</b>"
        await bot.send_message(user_id, msg_base)
        await asyncio.sleep(1.0)
        
        msg1 = (
            "<b>هام جداً</b> 🔥\n\n"
            "‼️<b>تعليمات وقوانين المنصة</b>‼️\n\n"
            "👈 يجب على الطالب قراءة كامل هذه الرسالة والتقيد بها\n"
            "وفي حال عدم التقيد بها يعني حصول الطالب على إنذارات ويؤدي ذلك إلى فصله التام من المنصة دون إرجاع قسطه.\n\n"
            "1️⃣  كل طالب يحصل عند تسجيله على اسم مستخدم وكلمة سر خاصة به يمنع منعا\" باتا\" إرسال أو مشاركة تلك المعلومات لأي طالب أخر تحت عقوبة الفصل التام وفي حال أراد الطالب فتح حسابه من أي جهاز أخر يجب إعلامنا مسبقا\"\n\n"
            "2️⃣ إن محتوى المنصة من دروس مصورة أو نوطات في مكتبة المنصة الإلكترونية أو أوراق عمل هي ملكية خاصة لمنصة طريقي التعليمية ولطلابها ويمنع منعا\" باتا\" مشاركتها أو إرسالها عبر مواقع التواصل الاجتماعي وذلك تحت بنود حقوق الملكية لمنصة طريقي وتحت إطار القوانين النافذة المنصوص عليها في قوانين الجرائم المعلوماتية\n\n"
            "3️⃣ إن كل رابط تلغرام خاص بأي مدرس أو رابط تلغرام خاص بأي مجموعة هو ملكية خاصة لمنصة طريقي التعليمية يمنع نشره أو إرساله أو إضافة أي طالب إليه تحت عقوبة الفصل التام من المنصة"
        )
        await bot.send_message(user_id, msg1)
        await asyncio.sleep(1.0)
        
        msg2 = (
            "4️⃣ في حال اكتشف قسم المتابعة في المنصة أن رقم ولي أمر الطالب هو رقم  خاطئ يفصل الطالب لحين اتصال ولي أمره بنا والتأكد منه\n\n"
            "5️⃣ على الطالب إبلاغنا في حال حذف أو تغير رقمه المعطى لنا مسبقا\"( الواتساب) وتزودينا برقمه الجديد\n\n"
            "6️⃣ على الطالب الإلتزام التام بالبرنامج الدراسي المعطى وعدم التراكم وفي حال راكم الطالب مواده خلال أكثر من أسبوع فإنه يحصل على إنذار ويتم الاتصال بولي أمره وإن ثلاثة إنذارات تؤدي إلى فصل الطالب من المنصة\n\n"
            "7️⃣ يجب على الطالب التحلي بالأدب والاحترام مع جميع كوادر المنصة من إداريين ومدرسين وفنينين ومبرمجين وقبل إرسال أي سؤال لأي مدرس أو إداري لذلك يجب على الطالب التعريف عن نفسه وعدم إرسال الرسائل أو الاتصال بعد الساعة التاسعة مساءً."
        )
        await bot.send_message(user_id, msg2)
        await asyncio.sleep(1.0)
        
        msg3 = (
            "والآن: \n\n"
            "🌟<b>بعض الميزات الهامة لدراسة الطالب في منصة طريقي التعليمية الافتراضية:</b>🌟\n\n"
            "1️⃣ يمكن للطالب الدخول إلى مكتبة المنصة الالكترونية وتحميل كافة النوط والكتب الدراسية بصيغة pdf\n\n"
            "2️⃣ يستطيع الطالب من خلال تطبيق المنصة تحميل الدروس بأكثر من دقة ومن ثم متابعتها لاحقاً بدون انترنيت وتكون تلك الدروس محملة في مكانها نفسه وليس في المعرض\n\n"
            "3️⃣ على الدروس تظهر إشارات (لم يحن وقت فتح الدرس ) لأن جميع الدروس مجدولة وفق البرنامج الأسبوعي الموجود على مجموعتكم في التلغرام وتفتح تلك الدروس وفق البرنامج كل يوم سبت الساعة الثالثة فجراً، ويستطيع الطالب إعادة الدرس متى شاء والعودة إليه ومراجعته في أي وقت كان وتبقى الدروس متاحة للطالب ولديه إلى آخر يوم في الامتحان الأخير\n\n"
            "4️⃣ إن الدروس التي عليها إشارات(؟) تحتوي على اختبارات في نهايتها ولا يستطيع الطالب الانتقال للدرس الذي يليه حتى يتم اختبار الدرس الحالي والحصول على درجة 80% وما فوق\n\n"
            "5️⃣ قبل البدء بالاختبار يجب على الطالب التحضير الجيد والتركيز في الدرس بالملاحظات الدرس ومن ثم البدء بذلك الاختبار"
        )
        await bot.send_message(user_id, msg3)
        await asyncio.sleep(1.0)
        
        msg4 = (
            "6️⃣ كل إختبار صحيح للطالب يحصل مقابله على نقطة ويعمل الطالب طيلة العام الدراسي على تجميع تلك النقاط ،وفي آخر الدورة يتم استبدال تلك النقاط بدورة آخر او بحسم من دورة من احدى دورات المنصة\n\n"
            "7️⃣ ان كل مرفق من مرفقات الدروس إن كان ملف pdf او صورة سيكون هناك لها إشارة على الدرس على شكل ( يوجد مرفقات )\n\n"
            "8️⃣حتى ينتقل الطالب من درس إلى درس يجب عليه الضغط على رمز ( الانتقال للدرس الذي يليه ) إذا لم يكن هناك اختبار\n\n"
            "9️⃣حتى ينتقل الطالب من وحدة إلى وحدة يجب عليه انهاء تلك الوحدة والضغط على رمز (طلب تأشيرة خروج) وإذا كان متماً للوحدة بكاملها فإننا فوراً سوف نفتح له الوحدة التي تليها\n\n"
            "🔟 يجب على الطالب مشاهدة فيديو طريقة الدراسة في منصة طريقي التعليمية قبل البدء في الدراسة وضغط على الرابط التالي 👈🏻 <a href='https://youtu.be/9AiTNBqc-jQ'>فيديو شرح طريقة العمل والاستخدام وميزات منصة طريقي التعليمية</a>\n\n"
            "⏸️ يجب على الطالب عدم مغادرة مجموعته على تلغرام"
        )
        await bot.send_message(user_id, msg4, disable_web_page_preview=True)

        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={user_id}")]])
        await callback.message.edit_text(callback.message.html_text + "\n\n✅ <b>تم قبول الطالب.</b>", reply_markup=kb)
    except Exception as e:
        logger.error(f"Error sending acceptance: {e}")
    await callback.answer()

@dp.callback_query(F.data.startswith("acc_rej_"))
async def acc_reject_student(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    try:
        await bot.send_message(user_id, "❌ <b>عذراً، تم رفض طلب التسجيل الخاص بك. يرجى مراجعة الدعم الفني للاستفسار.</b>")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={user_id}")]])
        await callback.message.edit_text(callback.message.html_text + "\n\n❌ <b>تم رفض الطالب.</b>", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("ask_ban_"))
async def ask_ban_student(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    media_msg_id = int(parts[3])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ تأكيد الحظر", callback_data=f"conf_ban_{user_id}_{media_msg_id}"),
         InlineKeyboardButton(text="🔙 عودة", callback_data=f"cancel_ban_{user_id}_{media_msg_id}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_ban_"))
async def cancel_ban_student(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    media_msg_id = int(parts[3])
    
    acc_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ قبول", callback_data=f"acc_acc_{user_id}"), InlineKeyboardButton(text="❌ رفض", callback_data=f"acc_rej_{user_id}")],
        [InlineKeyboardButton(text="💬 التحدث مع الطالب", url=f"tg://user?id={user_id}")],
        [InlineKeyboardButton(text="🚫 حظر الطالب", callback_data=f"ask_ban_{user_id}_{media_msg_id}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=acc_kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("conf_ban_"))
async def conf_ban_student(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    media_msg_id = int(parts[3])
    
    await set_ban_status(user_id, 1)
    
    if media_msg_id:
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=media_msg_id)
        except Exception:
            pass

    original_text = callback.message.html_text
    if "📝 <b>البيانات المدخلة:</b>" in original_text:
        account_info = original_text.split("📝 <b>البيانات المدخلة:</b>")[0].strip()
    else:
        account_info = original_text

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تم حظر هذا الطالب، اضغط للفك 🔓", callback_data=f"do_unban_{user_id}")]
    ])
    
    await callback.message.edit_text(account_info, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("do_unban_"))
async def do_unban_student(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    await set_ban_status(user_id, 0)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تم فك حظر هذا الطالب ✅", callback_data="dummy_btn")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "dummy_btn")
async def dummy_btn_handler(callback: CallbackQuery):
    await callback.answer()

@dp.message(F.text == "🚫 الطلاب المحظورين", MenuState.admin_main)
async def admin_banned_list(message: types.Message, state: FSMContext):
    banned = await get_all_banned_users()
    if not banned:
        await safe_send(message, "✅ <b>لا يوجد طلاب محظورين حالياً.</b>")
        return
        
    await safe_send(message, "🚫 <b>قائمة الطلاب المحظورين:</b>")
    await asyncio.sleep(0.5)
    for uid in banned:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ فك الحظر", callback_data=f"sys_unban_{uid}")]
        ])
        await safe_send(message, f"الطالب صاحب الآيدي: <code>{uid}</code>", reply_markup=kb)
        await asyncio.sleep(0.2)

@dp.callback_query(F.data.startswith("sys_unban_"))
async def sys_unban_student(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    await set_ban_status(user_id, 0)
    await callback.message.edit_text(f"✅ <b>تم فك الحظر عن الطالب:</b> <code>{user_id}</code>")
    await callback.answer()

@dp.message(F.text == "📚 2. الدورات والعروض", StateFilter(MenuState.user_main, MenuState.admin_student_view))
async def user_courses_menu(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.courses_categories)
    await safe_send(message, "📂 <b>يرجى اختيار الفرع أو المرحلة الدراسية:</b>", reply_markup=get_categories_kb())

@dp.message(F.text.in_(["🔬 الفرع العلمي", "🎧 علمي (مستمع)", "📖 الفرع الأدبي", "🎓 الصف التاسع الأساسي", "🎒 الصفوف الانتقالية"]), MenuState.courses_categories)
async def show_category_items_user(message: types.Message, state: FSMContext):
    category = message.text
    packages = await get_packages_by_category(category)
    await state.set_state(MenuState.viewing_category)
    await state.update_data(current_category=category)
    
    if not packages:
        await safe_send(message, f"⚠️ لا توجد باقات متاحة حالياً في <b>{category}</b>.", reply_markup=get_dynamic_items_kb([]))
    elif len(packages) == 1:
        await safe_send(message, "جاري العرض...", reply_markup=get_dynamic_items_kb([]))
        await asyncio.sleep(0.2)
        formatted_text = parse_custom_markdown(packages[0][2])
        await safe_send(message, formatted_text, reply_markup=get_inline_payment_shortcut_kb())
    else:
        await safe_send(message, f"اختر العرض المناسب لك من <b>{category}</b>:", reply_markup=get_dynamic_items_kb(packages))

@dp.message(MenuState.viewing_category)
async def handle_dynamic_course_btn(message: types.Message, state: FSMContext):
    if message.text == "🔙 رجوع":
        await user_courses_menu(message, state)
        return

    data = await state.get_data()
    category = data.get("current_category")
    packages = await get_packages_by_category(category)
    
    for pkg in packages:
        if message.text == pkg[1]:
            formatted_text = parse_custom_markdown(pkg[2])
            await safe_send(message, formatted_text, reply_markup=get_inline_payment_shortcut_kb())
            return
            
    await catch_all_unrecognized(message, state)

@dp.message(F.text == "🔙 رجوع", MenuState.courses_categories)
async def back_to_user_main(message: types.Message, state: FSMContext):
    await cmd_home(message, state)

@dp.message(F.text == "📱 أزرار الطالب", MenuState.admin_main)
async def show_student_buttons(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.admin_student_view)
    await safe_send(message, "تم التبديل إلى واجهة الطالب:", reply_markup=get_admin_user_view_kb())

@dp.message(F.text == "🔙 العودة إلى أزرار الأدمن", MenuState.admin_student_view)
async def return_to_admin_view(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.admin_main)
    await safe_send(message, "تمت العودة إلى واجهة الإدارة:", reply_markup=get_admin_kb())

@dp.message(F.text == "✏️ تعديل الأسعار", MenuState.admin_main)
async def admin_edit_prices(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.admin_edit_prices_categories)
    await safe_send(message, "🛠️ <b>اختر القسم الذي تريد تعديل أسعاره وأزراره:</b>", reply_markup=get_categories_kb())

@dp.message(F.text.in_(["🔬 الفرع العلمي", "🎧 علمي (مستمع)", "📖 الفرع الأدبي", "🎓 الصف التاسع الأساسي", "🎒 الصفوف الانتقالية"]), MenuState.admin_edit_prices_categories)
async def show_category_items_admin(message: types.Message, state: FSMContext):
    category = message.text
    packages = await get_packages_by_category(category)
    await state.set_state(MenuState.admin_managing_category)
    await state.update_data(current_category=category)
    
    await safe_send(message, f"⚙️ <b>إدارة: {category}</b>\n\nاختر الإجراء المناسب من الأسفل، أو استخدم الأزرار المرفقة مع كل باقة للتعديل أو الحذف.", reply_markup=get_admin_manage_category_kb())
    await asyncio.sleep(0.5)
    
    for pkg in packages:
        text_preview = parse_custom_markdown(pkg[2])
        await safe_send(message, text_preview, reply_markup=get_inline_manage_item_kb(pkg[0]))
        await asyncio.sleep(0.2)

@dp.message(F.text == "➕ إضافة زر جديد", MenuState.admin_managing_category)
async def prompt_add_new_package(message: types.Message, state: FSMContext):
    await state.set_state(MenuState.admin_waiting_for_new_package)
    instructions = (
        "✍️ <b>أرسل محتوى الزر الجديد الآن.</b>\n\n"
        "💡 <b>قواعد هامة:</b>\n"
        "1. السطر الأول سيصبح تلقائياً <b>اسم الزر</b>.\n"
        "2. استخدم *نص* لجعله <b>غامق</b>.\n"
        "3. استخدم -نص- لوضع <s>خط في منتصف الكلمة</s>.\n"
        "4. لا تنسَ إضافة الإيموجيات المناسبة! ✨"
    )
    await safe_send(message, instructions, reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 إلغاء الإضافة")]], resize_keyboard=True))

@dp.message(MenuState.admin_waiting_for_new_package)
async def process_new_package(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("current_category")

    if message.text == "🔙 إلغاء الإضافة":
        await state.set_state(MenuState.admin_managing_category)
        message.text = category
        await show_category_items_admin(message, state)
        return

    btn_name = extract_button_name(message.text)
    await add_package(category, btn_name, message.text)
    
    await state.set_state(MenuState.admin_managing_category)
    await safe_send(message, f"✅ <b>تم إضافة الزر بنجاح:</b> {btn_name}", reply_markup=get_admin_manage_category_kb())
    await asyncio.sleep(0.5)
    
    packages = await get_packages_by_category(category)
    for pkg in packages:
        text_preview = parse_custom_markdown(pkg[2])
        await safe_send(message, text_preview, reply_markup=get_inline_manage_item_kb(pkg[0]))
        await asyncio.sleep(0.2)

@dp.message(F.text == "↩️ التراجع عن آخر تعديل", MenuState.admin_managing_category)
async def undo_admin_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("current_category")
    
    success = await undo_last_action(category)
    if success:
        await safe_send(message, "✅ <b>تم التراجع عن الإجراء الأخير بنجاح.</b>")
    else:
        await safe_send(message, "⚠️ <b>لا يوجد إجراءات سابقة للتراجع عنها في هذا القسم.</b>")
        
    await asyncio.sleep(0.5)
    message.text = category
    await state.set_state(MenuState.admin_edit_prices_categories)
    await show_category_items_admin(message, state)

@dp.message(F.text == "🔙 رجوع", MenuState.admin_edit_prices_categories)
async def back_to_admin_main(message: types.Message, state: FSMContext):
    await cmd_home(message, state)

@dp.message(F.text == "🔙 رجوع", MenuState.admin_managing_category)
async def back_to_categories_admin(message: types.Message, state: FSMContext):
    await admin_edit_prices(message, state)

@dp.callback_query(F.data.startswith("edit_"), MenuState.admin_managing_category)
async def inline_edit_package(callback: CallbackQuery, state: FSMContext):
    pkg_id = int(callback.data.split("_")[1])
    await state.update_data(editing_pkg_id=pkg_id)
    await state.set_state(MenuState.admin_waiting_for_edit_package)
    
    instructions = (
        "✏️ <b>أرسل المحتوى الجديد الآن.</b>\n\n"
        "💡 سيتم استبدال الزر القديم ومحتواه بالكامل بناءً على رسالتك الجديدة.\n"
        "(تذكر: السطر الأول هو اسم الزر، واستخدم *نص* للغامق و -نص- للمشطوب)."
    )
    await safe_send(callback.message, instructions, reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 إلغاء التعديل")]], resize_keyboard=True))
    await callback.answer()

@dp.message(MenuState.admin_waiting_for_edit_package)
async def process_edit_package(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("current_category")
    
    if message.text == "🔙 إلغاء التعديل":
        await state.set_state(MenuState.admin_managing_category)
        message.text = category
        await show_category_items_admin(message, state)
        return

    pkg_id = data.get("editing_pkg_id")
    btn_name = extract_button_name(message.text)
    
    await update_package(pkg_id, btn_name, message.text)
    
    await state.set_state(MenuState.admin_managing_category)
    await safe_send(message, f"✅ <b>تم تحديث الزر بنجاح:</b> {btn_name}", reply_markup=get_admin_manage_category_kb())
    await asyncio.sleep(0.5)
    
    packages = await get_packages_by_category(category)
    for pkg in packages:
        text_preview = parse_custom_markdown(pkg[2])
        await safe_send(message, text_preview, reply_markup=get_inline_manage_item_kb(pkg[0]))
        await asyncio.sleep(0.2)

@dp.callback_query(F.data.startswith("del_"), MenuState.admin_managing_category)
async def inline_del_package(callback: CallbackQuery):
    pkg_id = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=get_inline_confirm_del_kb(pkg_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_"), MenuState.admin_managing_category)
async def inline_cancel_del(callback: CallbackQuery):
    pkg_id = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=get_inline_manage_item_kb(pkg_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("confdel_"), MenuState.admin_managing_category)
async def inline_confirm_del(callback: CallbackQuery, state: FSMContext):
    pkg_id = int(callback.data.split("_")[1])
    await delete_package(pkg_id)
    await callback.message.delete()
    await callback.answer()

@dp.message()
async def catch_all_unrecognized(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    
    kb = get_user_kb()
    if current_state == MenuState.admin_main.state:
        kb = get_admin_kb()
    elif current_state == MenuState.admin_student_view.state:
        kb = get_admin_user_view_kb()
    elif current_state == MenuState.about_us.state:
        kb = get_back_kb()
    elif current_state == MenuState.courses_categories.state:
        kb = get_categories_kb()
    elif current_state == MenuState.viewing_category.state:
        data = await state.get_data()
        category = data.get("current_category")
        if category:
            packages = await get_packages_by_category(category)
            kb = get_dynamic_items_kb(packages)
    elif current_state == MenuState.admin_edit_prices_categories.state:
        kb = get_categories_kb()
    elif current_state == MenuState.admin_managing_category.state:
        kb = get_admin_manage_category_kb()
    elif current_state == MenuState.payment_methods.state:
        kb = get_payment_kb()
    elif current_state == MenuState.electronic_payment.state:
        kb = get_electronic_payment_kb()
    elif current_state == MenuState.waiting_for_payment_receipt.state:
        kb = get_receipt_upload_kb()
    elif current_state == MenuState.support_menu.state:
        kb = get_support_kb()
    elif current_state == MenuState.viewing_numbers.state:
        kb = get_support_back_kb()
    elif current_state == MenuState.waiting_for_inquiry.state:
        kb = get_support_back_kb()

    await safe_send(message, "<b>من فضلك، اختر أحد الأوامر المتاحة من القائمة 👇:</b>", reply_markup=kb)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if Config.WEBHOOK_URL:
        await bot.set_webhook(Config.WEBHOOK_URL)
        logger.info(f"Webhook connected: {Config.WEBHOOK_URL}")
    yield
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        update = types.Update(**update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"Webhook Update Error: {e}")
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("bot:app", host="127.0.0.1", port=8000, reload=True)