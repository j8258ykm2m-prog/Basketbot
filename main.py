import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ==========================================
# 1. КОНФИГУРАЦИЯ СТАРТАПА
# ==========================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
ADMIN_ID = 6400374873           
DB_NAME = "basket_startup.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ==========================================
# 2. БАЗА ДАННЫХ (aiosqlite)
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT,
                experience TEXT,
                goal TEXT,
                exp INTEGER DEFAULT 0,
                weekly_exp INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                last_workout TIMESTAMP
            )
        """)
        await db.commit()

# ==========================================
# 3. КОНТЕНТНАЯ БАЗА
# ==========================================
CATEGORIES = {
    "skills": "🏀 Базовые навыки",
    "tactics": "🧠 Командная тактика",
    "positions": "⛹️ Позиционная работа",
    "fitness": "🏋️ ОФП и Кардио",
    "rehab": "🩹 Профилактика (ТОП-10 травм)",
    "mental": "🧘 Ментальность и Фокус"
}

WORKOUTS = {
    "dribble_base": {"cat": "skills", "title": "Основы дриблинга", "exp": 50, "media": None, "desc": "Контроль мяча, кроссоверы, переводы."},
    "shoot_base": {"cat": "skills", "title": "Бросковая механика", "exp": 60, "media": None, "desc": "Постановка кисти, штрафные, catch-and-shoot."},
    "tac_3x3_off": {"cat": "tactics", "title": "Нападение 3х3", "exp": 70, "media": None, "desc": "Спейсинг, пик-н-ролл, изоляции."},
    "tac_5x5_def": {"cat": "tactics", "title": "Защита 5х5", "exp": 80, "media": None, "desc": "Зонная защита, ротация, подстраховка."},
    "pos_pg": {"cat": "positions", "title": "Разыгрывающий (PG)", "exp": 100, "media": None, "desc": "Чтение игры, элитный пас, флоутеры."},
    "pos_c": {"cat": "positions", "title": "Центровой (C)", "exp": 100, "media": None, "desc": "Работа в усах (post-up), подборы, блокшоты."},
    "fit_cardio": {"cat": "fitness", "title": "Баскетбольное кардио", "exp": 60, "media": None, "desc": "Челночный бег, интервалы, выносливость."},
    "reh_ankle": {"cat": "rehab", "title": "Голеностоп (Растяжения)", "exp": 40, "media": None, "desc": "Закачка связок, баланс на полусфере."},
    "reh_knee": {"cat": "rehab", "title": "Колено Прыгуна", "exp": 40, "media": None, "desc": "Изометрия, снятие воспаления с сухожилия."},
    "reh_achill": {"cat": "rehab", "title": "Ахиллово сухожилие", "exp": 40, "media": None, "desc": "Эксцентрические подъемы, растяжка икр."},
    "men_clutch": {"cat": "mental", "title": "Клатч-менталитет", "exp": 50, "media": None, "desc": "Как не бояться решающего броска. Психология победителя."}
}

# ==========================================
# 4. FSM: МАШИНА СОСТОЯНИЙ (ONBOARDING)
# ==========================================
class Onboarding(StatesGroup):
    waiting_for_name = State()
    waiting_for_exp = State()
    waiting_for_goal = State()

# ==========================================
# 5. КЛАВИАТУРЫ (ИНТЕРФЕЙСЫ)
# ==========================================
def kb_main_menu():
    kb = [
        [InlineKeyboardButton(text="🏀 База и Навыки", callback_data="cat_skills"),
         InlineKeyboardButton(text="🧠 Тактика", callback_data="cat_tactics")],
        [InlineKeyboardButton(text="⛹️ Позиции", callback_data="cat_positions"),
         InlineKeyboardButton(text="🏋️ ОФП и Кардио", callback_data="cat_fitness")],
        [InlineKeyboardButton(text="🩹 Профилактика травм", callback_data="cat_rehab"),
         InlineKeyboardButton(text="🧘 Ментал", callback_data="cat_mental")],
        [InlineKeyboardButton(text="🏆 Рейтинг Лиги", callback_data="menu_leaderboard"),
         InlineKeyboardButton(text="👤 Мой Профиль", callback_data="menu_profile")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_category(cat_id: str):
    kb = []
    for w_id, w_data in WORKOUTS.items():
        if w_data["cat"] == cat_id:
            kb.append([InlineKeyboardButton(text=w_data["title"], callback_data=f"work_{w_id}")])
    kb.append([InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_workout(w_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Выполнил тренировку (+EXP)", callback_data=f"done_{w_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

# ==========================================
# 6. ХЭНДЛЕРЫ: ONBOARDING И РЕГИСТРАЦИЯ
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
    if user:
        await message.answer(f"С возвращением на корт, {user[0]}! 🏀\nВыбирай план на сегодня:", reply_markup=kb_main_menu())
    else:
        await message.answer("👋 Привет! Я — твой цифровой баскетбольный тренер. Чтобы составить идеальную программу, давай познакомимся.\n\nКак мне к тебе обращаться?")
        await state.set_state(Onboarding.waiting_for_name)

@dp.message(Onboarding.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новичок", callback_data="exp_novice")],
        [InlineKeyboardButton(text="Любитель (Играю во дворе/зале)", callback_data="exp_amateur")],
        [InlineKeyboardButton(text="Спортшкола / Про", callback_data="exp_pro")]
    ])
    await message.answer("Отлично! Оцени свой текущий уровень игры:", reply_markup=kb)
    await state.set_state(Onboarding.waiting_for_exp)

@dp.callback_query(Onboarding.waiting_for_exp)
async def process_exp(callback: CallbackQuery, state: FSMContext):
    await state.update_data(experience=callback.data)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Дриблинг и бросок", callback_data="goal_skills")],
        [InlineKeyboardButton(text="Физика (Прыжок, скорость)", callback_data="goal_phys")],
        [InlineKeyboardButton(text="Восстановление и здоровье", callback_data="goal_health")]
    ])
    await callback.message.edit_text("Понял тебя. Какая твоя главная цель на ближайший месяц?", reply_markup=kb)
    await state.set_state(Onboarding.waiting_for_goal)

@dp.callback_query(Onboarding.waiting_for_goal)
async def process_goal(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    username = callback.from_user.username
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, name, experience, goal, last_workout) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, data['name'], data.get('experience'), callback.data, datetime.now()))
        await db.commit()
        
    await state.clear()
    await callback.message.edit_text(
        f"🔥 Профиль создан, {data['name']}!\n\nТвоя задача — тренироваться, копить EXP и подниматься в Рейтинге. Погнали!", 
        reply_markup=kb_main_menu()
    )

# ==========================================
# 7. ХЭНДЛЕРЫ: ОСНОВНОЙ ФУНКЦИОНАЛ
# ==========================================
@dp.callback_query(F.data.startswith("menu_"))
async def handle_main_menu(callback: CallbackQuery):
    action = callback.data.split("_")[1]
    
    if action == "main":
        await callback.message.edit_text("Выбирай раздел:", reply_markup=kb_main_menu())
        
    elif action == "profile":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT name, exp, streak FROM users WHERE user_id = ?", (callback.from_user.id,)) as cursor:
                user = await cursor.fetchone()
        if user:
            text = f"👤 **Профиль игрока: {user[0]}**\n\n🏆 Опыт (EXP): {user[1]}\n🔥 Стрик (дней подряд): {user[2]}\n\nПродолжай тренироваться, чтобы стать лучше!"
        else:
            text = "Профиль не найден. Введи /start"
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]]))
        
    elif action == "leaderboard":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT name, weekly_exp FROM users ORDER BY weekly_exp DESC LIMIT 10") as cursor:
                leaders = await cursor.fetchall()
        
        text = "🏆 **ЕЖЕНЕДЕЛЬНЫЙ РЕЙТИНГ ЛИГИ** 🏆\n(Топ-2 получают призы в воскресенье!)\n\n"
        for i, (name, exp) in enumerate(leaders, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏀"
            text += f"{medal} {i}. {name} — {exp} EXP\n"
            
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]]))

@dp.callback_query(F.data.startswith("cat_"))
async def handle_category(callback: CallbackQuery):
    cat_id = callback.data.replace("cat_", "")
    cat_name = CATEGORIES[cat_id]
    await callback.message.edit_text(f"**{cat_name}**\nВыбери тренировку:", reply_markup=kb_category(cat_id), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("work_"))
async def handle_workout(callback: CallbackQuery):
    w_id = callback.data.replace("work_", "")
    workout = WORKOUTS[w_id]
    
    text = f"⚡ **{workout['title']}**\n\n{workout['desc']}\n\n💎 Награда: +{workout['exp']} EXP"
    
    if workout['media']:
        await callback.message.delete()
        await callback.message.answer_video(video=workout['media'], caption=text, reply_markup=kb_workout(w_id), parse_mode="Markdown")
    else:
        text += "\n\n*(Видео-инструкция в процессе добавления)*"
        await callback.message.edit_text(text, reply_markup=kb_workout(w_id), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("done_"))
async def handle_done(callback: CallbackQuery):
    w_id = callback.data.replace("done_", "")
    exp_gain = WORKOUTS[w_id]["exp"]
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE users 
            SET exp = exp + ?, weekly_exp = weekly_exp + ?, streak = streak + 1, last_workout = ?
            WHERE user_id = ?
        """, (exp_gain, exp_gain, datetime.now(), user_id))
        await db.commit()
        
    await callback.answer(f"✅ Тренировка засчитана! Получено +{exp_gain} EXP", show_alert=True)
    await callback.message.delete()
    await bot.send_message(user_id, "Возврат в меню:", reply_markup=kb_main_menu())

# ==========================================
# 8. АДМИН ПАНЕЛЬ
# ==========================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return 
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
            
    text = f"👑 **ПАНЕЛЬ СТАРТАПА**\n\n👥 Всего пользователей: {total_users}\n\n_Здесь можно будет добавить кнопку массовой рассылки._"
    await message.answer(text, parse_mode="Markdown")

# ==========================================
# 9. ФОНОВЫЕ ЗАДАЧИ
# ==========================================
async def check_inactive_users():
    deadline = datetime.now() - timedelta(days=3)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, name FROM users WHERE last_workout < ?", (deadline,)) as cursor:
            inactive_users = await cursor.fetchall()
            
    for user_id, name in inactive_users:
        try:
            await bot.send_message(user_id, f"Эй, {name}! Кольцо скучает 🏀\nТы не тренировался уже 3 дня. Самое время сделать хотя бы ОФП!")
            async with aiosqlite.connect(DB_NAME) as db_update:
                await db_update.execute("UPDATE users SET streak = 0 WHERE user_id = ?", (user_id,))
                await db_update.commit()
        except Exception:
            pass 

async def weekly_leaderboard_rewards():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, name FROM users ORDER BY weekly_exp DESC LIMIT 2") as cursor:
            top_2 = await cursor.fetchall()
            
        if top_2:
            try:
                await bot.send_message(top_2[0][0], "🎉 Поздравляем! Ты занял 1 МЕСТО в лиге на этой неделе! Свяжись с нами для получения секретного приза!")
                if len(top_2) > 1:
                    await bot.send_message(top_2[1][0], "🔥 Отличная работа! 2 МЕСТО в лиге! У нас для тебя скидка.")
            except: pass
            
        await db.execute("UPDATE users SET weekly_exp = 0")
        await db.commit()

# ==========================================
# 10. FLASK-СЕРВЕР (Для Render)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Стартап-бот работает 24/7! 🏀"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ==========================================
# 11. ЗАПУСК БОТА И СЕРВЕРА
# ==========================================
async def main():
    await init_db() 
    
    # Запуск планировщика
    scheduler.add_job(check_inactive_users, "cron", hour=18, minute=0)
    scheduler.add_job(weekly_leaderboard_rewards, "cron", day_of_week="sun", hour=23, minute=59)
    scheduler.start()
    
    # Запуск Flask-сервера в фоновом режиме
    threading.Thread(target=run_web, daemon=True).start()
    
    print("🚀 Бот и веб-сервер успешно запущены!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
