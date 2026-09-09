from aiogram import F # Убедись, что F импортирован в начале файла
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncpg import Pool

import database
from content import CATEGORIES

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("basketbot")

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DATABASE_PROBE_INTERVAL_SECONDS = 20 * 60
DATABASE_PROBE_MAX_AGE_SECONDS = 30 * 60
LOOP_HEARTBEAT_MAX_AGE_SECONDS = 30


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    database_url: str
    admin_id: int
    port: int


@dataclass
class RuntimeState:
    started_at: datetime
    last_loop_tick: float
    database_ok: bool = False
    last_database_check: datetime | None = None
    bot_username: str | None = None
    polling_task: asyncio.Task[None] | None = None


def load_settings() -> Settings:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    try:
        admin_id = int(os.environ.get("ADMIN_ID", "6400374873"))
        port = int(os.environ.get("PORT", "10000"))
    except ValueError as exc:
        raise RuntimeError("ADMIN_ID and PORT must be integers") from exc

    return Settings(
        telegram_bot_token=token,
        database_url=database_url,
        admin_id=admin_id,
        port=port,
    )


dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
runtime = RuntimeState(
    started_at=datetime.now(timezone.utc),
    last_loop_tick=time.monotonic(),
)
bot: Bot | None = None
db_pool: Pool | None = None
settings: Settings | None = None


def get_bot() -> Bot:
    if bot is None:
        raise RuntimeError("Bot is not initialized")
    return bot


def get_pool() -> Pool:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized")
    return db_pool


def is_admin(user_id: int) -> bool:
    return settings is not None and user_id == settings.admin_id


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Onboarding(StatesGroup):
    waiting_for_name = State()
    waiting_for_exp = State()
    waiting_for_goal = State()


def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏀 База и Навыки", callback_data="cat_skills"
                ),
                InlineKeyboardButton(text="🧠 Тактика", callback_data="cat_tactics"),
            ],
            [
                InlineKeyboardButton(text="⛹️ Позиции", callback_data="cat_positions"),
                InlineKeyboardButton(
                    text="🏋️ ОФП и Кардио", callback_data="cat_fitness"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🩹 Профилактика травм", callback_data="cat_rehab"
                ),
                InlineKeyboardButton(text="🧘 Ментал", callback_data="cat_mental"),
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Рейтинг Лиги", callback_data="menu_leaderboard"
                ),
                InlineKeyboardButton(
                    text="👤 Мой Профиль", callback_data="menu_profile"
                ),
            ],
        ]
    )


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
        ]
    )


def kb_category(workouts: Any) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=workout["title"],
                callback_data=f"work_{workout['workout_id']}",
            )
        ]
        for workout in workouts
    ]
    rows.append(
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_main")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_workout(workout_id: str, link_materials: Any) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for material in link_materials[:8]:
        label = (material["label"] or "🔗 Открыть материал").strip()[:64]
        rows.append([InlineKeyboardButton(text=label, url=material["value"])])
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="🔥 Выполнил тренировку (+EXP)",
                    callback_data=f"done_{workout_id}",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    name = await database.fetch_user_name(get_pool(), user_id)

    if name:
        await state.clear()
        await message.answer(
            f"С возвращением на корт, {escape(name)}! 🏀\nВыбирай план на сегодня:",
            reply_markup=kb_main_menu(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        "👋 Привет! Я — твой цифровой баскетбольный тренер. "
        "Чтобы составить идеальную программу, давай познакомимся.\n\n"
        "Как мне к тебе обращаться?"
    )
    await state.set_state(Onboarding.waiting_for_name)


@dp.message(Onboarding.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши, пожалуйста, имя текстом.")
        return

    await state.update_data(name=name[:100])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новичок", callback_data="exp_novice")],
            [
                InlineKeyboardButton(
                    text="Любитель (Играю во дворе/зале)",
                    callback_data="exp_amateur",
                )
            ],
            [InlineKeyboardButton(text="Спортшкола / Про", callback_data="exp_pro")],
        ]
    )
    await message.answer(
        "Отлично! Оцени свой текущий уровень игры:", reply_markup=keyboard
    )
    await state.set_state(Onboarding.waiting_for_exp)


@dp.callback_query(Onboarding.waiting_for_exp, F.data.startswith("exp_"))
async def process_exp(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(experience=callback.data)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Дриблинг и бросок", callback_data="goal_skills"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Физика (Прыжок, скорость)",
                    callback_data="goal_phys",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Восстановление и здоровье",
                    callback_data="goal_health",
                )
            ],
        ]
    )
    await callback.message.edit_text(
        "Понял тебя. Какая твоя главная цель на ближайший месяц?",
        reply_markup=keyboard,
    )
    await state.set_state(Onboarding.waiting_for_goal)


@dp.callback_query(Onboarding.waiting_for_goal, F.data.startswith("goal_"))
async def process_goal(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    name = data.get("name") or "Игрок"
    await database.save_profile(
        get_pool(),
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        name=name,
        experience=data.get("experience"),
        goal=callback.data,
        now=utc_now(),
    )
    await state.clear()
    await callback.message.edit_text(
        f"🔥 Профиль создан, {escape(name)}!\n\n"
        "Твоя задача — тренироваться, копить EXP и подниматься в Рейтинге. Погнали!",
        reply_markup=kb_main_menu(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("menu_"))
async def handle_main_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    action = callback.data.removeprefix("menu_")

    if action == "main":
        await callback.message.edit_text("Выбирай раздел:", reply_markup=kb_main_menu())
        return

    if action == "profile":
        user = await database.fetch_profile(get_pool(), callback.from_user.id)
        if user:
            text = (
                f"👤 <b>Профиль игрока: {escape(user['name'])}</b>\n\n"
                f"🏆 Опыт (EXP): {user['exp']}\n"
                f"🔥 Стрик (дней подряд): {user['streak']}\n\n"
                "Продолжай тренироваться, чтобы стать лучше!"
            )
        else:
            text = "Профиль не найден. Введи /start"
        await callback.message.edit_text(
            text, reply_markup=kb_back(), parse_mode="HTML"
        )
        return

    if action == "leaderboard":
        leaders = await database.fetch_leaderboard(get_pool())
        lines = [
            "🏆 <b>ЕЖЕНЕДЕЛЬНЫЙ РЕЙТИНГ ЛИГИ</b> 🏆",
            "(Топ-2 получают призы в воскресенье!)",
            "",
        ]
        if not leaders:
            lines.append("Пока рейтинг пуст. Стань первым!")
        for index, leader in enumerate(leaders, 1):
            medal = (
                "🥇"
                if index == 1
                else "🥈"
                if index == 2
                else "🥉"
                if index == 3
                else "🏀"
            )
            lines.append(
                f"{medal} {index}. {escape(leader['name'])} — {leader['weekly_exp']} EXP"
            )
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=kb_back(),
            parse_mode="HTML",
        )


@dp.callback_query(F.data.startswith("cat_"))
async def handle_category(callback: CallbackQuery) -> None:
    await callback.answer()
    category_id = callback.data.removeprefix("cat_")
    category_name = CATEGORIES.get(category_id)
    if category_name is None:
        await callback.message.edit_text(
            "Раздел не найден.", reply_markup=kb_main_menu()
        )
        return

    workouts = await database.fetch_workouts_by_category(get_pool(), category_id)
    await callback.message.edit_text(
        f"<b>{escape(category_name)}</b>\nВыбери тренировку:",
        reply_markup=kb_category(workouts),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("work_"))
async def handle_workout(callback: CallbackQuery) -> None:
    await callback.answer()
    workout_id = callback.data.removeprefix("work_")
    workout = await database.fetch_workout(get_pool(), workout_id)
    if workout is None:
        await callback.message.edit_text(
            "Эта тренировка временно недоступна.",
            reply_markup=kb_main_menu(),
        )
        return

    materials = await database.fetch_materials(get_pool(), workout_id)
    media_materials = [
        item for item in materials if item["material_type"] in {"photo", "video"}
    ]
    link_materials = [item for item in materials if item["material_type"] == "link"]

    with contextlib.suppress(TelegramBadRequest):
        await callback.message.delete()

    unavailable_materials = 0
    for material in media_materials[:10]:
        try:
            if material["material_type"] == "photo":
                await get_bot().send_photo(callback.from_user.id, material["value"])
            else:
                await get_bot().send_video(callback.from_user.id, material["value"])
        except TelegramAPIError:
            unavailable_materials += 1
            logger.exception(
                "Unable to send material_id=%s for workout=%s",
                material["material_id"],
                workout_id,
            )

    text = (
        f"⚡ <b>{escape(workout['title'])}</b>\n\n"
        f"{escape(workout['description'])}\n\n"
        f"💎 Награда: +{workout['exp']} EXP"
    )
    if not materials:
        text += "\n\n<i>Видео, фото и ссылки пока не добавлены.</i>"
    elif unavailable_materials:
        text += "\n\n<i>Один из материалов временно недоступен.</i>"

    await get_bot().send_message(
        callback.from_user.id,
        text,
        reply_markup=kb_workout(workout_id, link_materials),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("done_"))
async def handle_done(callback: CallbackQuery) -> None:
    workout_id = callback.data.removeprefix("done_")
    workout = await database.fetch_workout(get_pool(), workout_id)
    if workout is None:
        await callback.answer("Тренировка не найдена.", show_alert=True)
        return

    updated = await database.add_experience(
        get_pool(),
        user_id=callback.from_user.id,
        amount=workout["exp"],
        now=utc_now(),
    )
    if not updated:
        await callback.answer("Сначала создай профиль командой /start", show_alert=True)
        return

    await callback.answer(
        f"✅ Тренировка засчитана! Получено +{workout['exp']} EXP",
        show_alert=True,
    )
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.delete()
    await get_bot().send_message(
        callback.from_user.id,
        "Возврат в меню:",
        reply_markup=kb_main_menu(),
    )


@dp.message(Command("sssadminpotent"))
async def cmd_admin(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    total_users = await database.count_users(get_pool())
    await message.answer(
        "👑 <b>ПАНЕЛЬ СТАРТАПА</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n\n"
        "<b>Управление материалами</b>\n"
        "• Ответь на фото или видео: <code>/addmedia dribble_base</code>\n"
        "• Добавь ссылку: <code>/addlink dribble_base https://example.com Название</code>\n"
        "• Посмотри материалы: <code>/materials dribble_base</code>\n"
        "• Удали материал: <code>/delmaterial 123</code>\n"
        "• Список пользователей: /users\n"
        "• Резервная копия данных: /backup",
        parse_mode="HTML",
    )


@dp.message(Command("myid"))
async def cmd_my_id(message: types.Message) -> None:
    await message.answer(
        f"Твой Telegram ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )


@dp.message(Command("users"))
async def cmd_users(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    users = await database.fetch_users(get_pool())
    if not users:
        await message.answer("Пользователей пока нет.")
        return

    lines = ["<b>Пользователи</b>", ""]
    for user in users:
        username = (
            f"@{escape(user['username'])}" if user["username"] else "без username"
        )
        lines.append(
            f"<code>{user['user_id']}</code> — {escape(user['name'])} "
            f"({username}); EXP {user['exp']}, неделя {user['weekly_exp']}, "
            f"стрик {user['streak']}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("addmedia"))
async def cmd_add_media(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            "Ответь этой командой на фото или видео:\n"
            "<code>/addmedia dribble_base</code>",
            parse_mode="HTML",
        )
        return

    workout_id = parts[1].strip()
    workout = await database.fetch_workout(get_pool(), workout_id)
    if workout is None:
        await message.answer(
            "Неизвестный ID тренировки. Открой /materials для проверки."
        )
        return

    reply = message.reply_to_message
    if reply is None:
        await message.answer("Команду нужно отправить ответом на фото или видео.")
        return

    if reply.video:
        material_type = "video"
        value = reply.video.file_id
    elif reply.photo:
        material_type = "photo"
        value = reply.photo[-1].file_id
    else:
        await message.answer("Поддерживаются фото и видео. Для URL используй /addlink.")
        return

    material_id = await database.add_material(
        get_pool(),
        workout_id=workout_id,
        material_type=material_type,
        value=value,
    )
    await message.answer(
        f"✅ Материал #{material_id} сохранён в постоянной базе для «{escape(workout['title'])}».",
        parse_mode="HTML",
    )


@dp.message(Command("addlink"))
async def cmd_add_link(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            "Формат:\n<code>/addlink dribble_base https://example.com Название кнопки</code>",
            parse_mode="HTML",
        )
        return

    workout_id, url = parts[1], parts[2]
    label = parts[3].strip() if len(parts) == 4 else "🔗 Открыть материал"
    if not is_http_url(url) or len(url) > 2048:
        await message.answer("Нужна полная ссылка, начинающаяся с https:// или http://")
        return

    workout = await database.fetch_workout(get_pool(), workout_id)
    if workout is None:
        await message.answer("Неизвестный ID тренировки.")
        return

    material_id = await database.add_material(
        get_pool(),
        workout_id=workout_id,
        material_type="link",
        value=url,
        label=label[:64],
    )
    await message.answer(f"✅ Ссылка сохранена как материал #{material_id}.")


@dp.message(Command("materials"))
async def cmd_materials(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            "Формат: <code>/materials dribble_base</code>", parse_mode="HTML"
        )
        return

    workout_id = parts[1].strip()
    workout = await database.fetch_workout(get_pool(), workout_id)
    if workout is None:
        await message.answer("Неизвестный ID тренировки.")
        return

    materials = await database.fetch_materials(get_pool(), workout_id)
    lines = [
        f"<b>{escape(workout['title'])}</b> (<code>{escape(workout_id)}</code>)",
        "",
    ]
    if not materials:
        lines.append("Материалов пока нет.")
    for item in materials:
        kind = {"photo": "Фото", "video": "Видео", "link": "Ссылка"}[
            item["material_type"]
        ]
        label = f" — {escape(item['label'])}" if item["label"] else ""
        lines.append(f"#{item['material_id']}: {kind}{label}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("delmaterial"))
async def cmd_delete_material(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    try:
        material_id = int(parts[1])
    except (IndexError, ValueError):
        await message.answer("Формат: <code>/delmaterial 123</code>", parse_mode="HTML")
        return

    deleted = await database.delete_material(get_pool(), material_id)
    await message.answer(
        "✅ Материал удалён." if deleted else "Материал с таким номером не найден."
    )


@dp.message(Command("backup"))
async def cmd_backup(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    snapshot = await database.export_snapshot(get_pool())
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    document = BufferedInputFile(payload, filename=f"basketbot_backup_{timestamp}.json")
    await message.answer_document(
        document,
        caption="Резервная копия пользователей, тренировок и материалов.",
    )


async def check_inactive_users() -> None:
    now = utc_now()
    deadline = now - timedelta(days=3)
    inactive_users = await database.fetch_inactive_users(get_pool(), deadline)

    for user in inactive_users:
        try:
            await get_bot().send_message(
                user["user_id"],
                f"Эй, {escape(user['name'])}! Кольцо скучает 🏀\n"
                "Ты не тренировался уже 3 дня. Самое время сделать хотя бы ОФП!",
                parse_mode="HTML",
            )
        except TelegramForbiddenError:
            logger.info("User %s blocked the bot", user["user_id"])
        except TelegramAPIError:
            logger.exception("Inactive reminder failed for user %s", user["user_id"])
            continue
        await database.mark_inactive_notice(get_pool(), user["user_id"], now)


async def weekly_leaderboard_rewards() -> None:
    local_date = datetime.now(MOSCOW_TZ).date()
    week_start = local_date - timedelta(days=local_date.weekday())
    reward_run = await database.prepare_weekly_reward_run(get_pool(), week_start)

    rewards = (
        (
            1,
            reward_run["first_user_id"],
            reward_run["first_notified"],
            (
                "🎉 Поздравляем! Ты занял 1 МЕСТО в лиге на этой неделе! "
                "Свяжись с нами для получения секретного приза!"
            ),
        ),
        (
            2,
            reward_run["second_user_id"],
            reward_run["second_notified"],
            "🔥 Отличная работа! 2 МЕСТО в лиге! У нас для тебя скидка.",
        ),
    )
    for position, user_id, already_notified, text in rewards:
        if user_id is None or already_notified:
            continue
        try:
            await get_bot().send_message(user_id, text)
        except TelegramForbiddenError:
            logger.info("Weekly winner %s blocked the bot", user_id)
        except TelegramAPIError:
            logger.exception("Weekly reward message failed for user %s", user_id)
            continue
        await database.mark_reward_notified(get_pool(), week_start, position)


async def guarded_job(name: str, function: Any) -> None:
    try:
        await function()
    except Exception:
        logger.exception("Scheduled job %s failed", name)


def polling_is_alive() -> bool:
    return runtime.polling_task is not None and not runtime.polling_task.done()


def loop_is_alive() -> bool:
    return time.monotonic() - runtime.last_loop_tick < LOOP_HEARTBEAT_MAX_AGE_SECONDS


def database_is_ready() -> bool:
    if not runtime.database_ok or runtime.last_database_check is None:
        return False
    age = (utc_now() - runtime.last_database_check).total_seconds()
    return age < DATABASE_PROBE_MAX_AGE_SECONDS


async def root_handler(_: web.Request) -> web.Response:
    return web.json_response(
        {
            "service": "basketbot",
            "status": "running",
            "health": "/health/ready",
        }
    )


async def live_health_handler(_: web.Request) -> web.Response:
    healthy = polling_is_alive() and loop_is_alive()
    return web.json_response(
        {
            "status": "ok" if healthy else "error",
            "process": healthy,
        },
        status=200 if healthy else 503,
    )


async def ready_health_handler(_: web.Request) -> web.Response:
    checks = {
        "event_loop": loop_is_alive(),
        "polling": polling_is_alive(),
        "database": database_is_ready(),
        "scheduler": scheduler.running,
    }
    healthy = all(checks.values())
    return web.json_response(
        {
            "status": "ok" if healthy else "error",
            "checks": checks,
            "bot": runtime.bot_username,
            "database_checked_at": (
                runtime.last_database_check.isoformat()
                if runtime.last_database_check is not None
                else None
            ),
        },
        status=200 if healthy else 503,
    )


async def start_web_server(port: int) -> web.AppRunner:
    application = web.Application()
    application.router.add_get("/", root_handler)
    application.router.add_get("/health/live", live_health_handler)
    application.router.add_get("/health/ready", ready_health_handler)

    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    return runner


async def heartbeat_loop() -> None:
    while True:
        runtime.last_loop_tick = time.monotonic()
        await asyncio.sleep(5)


async def database_probe_loop() -> None:
    while True:
        await asyncio.sleep(DATABASE_PROBE_INTERVAL_SECONDS)
        runtime.database_ok = await database.ping_database(get_pool())
        runtime.last_database_check = utc_now()
        if not runtime.database_ok:
            logger.error("Periodic database health check failed")


@dp.error()
async def handle_update_error(event: ErrorEvent) -> bool:
    error = event.exception
    logger.error(
        "Unhandled update error: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    return True


async def cancel_task(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def main() -> None:
    global bot, db_pool, settings

    settings = load_settings()
    bot = Bot(token=settings.telegram_bot_token)
    db_pool = await database.create_pool(settings.database_url)

    web_runner: web.AppRunner | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    database_probe_task: asyncio.Task[None] | None = None

    try:
        await database.initialize_database(db_pool)
        runtime.database_ok = await database.ping_database(db_pool)
        runtime.last_database_check = utc_now()
        if not runtime.database_ok:
            raise RuntimeError("Initial database health check failed")

        bot_info = await bot.get_me()
        runtime.bot_username = bot_info.username

        scheduler.add_job(
            guarded_job,
            "cron",
            id="inactive_users",
            kwargs={"name": "inactive_users", "function": check_inactive_users},
            hour=18,
            minute=0,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60 * 60,
            replace_existing=True,
        )
        scheduler.add_job(
            guarded_job,
            "cron",
            id="weekly_rewards",
            kwargs={"name": "weekly_rewards", "function": weekly_leaderboard_rewards},
            day_of_week="sun",
            hour=23,
            minute=59,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60 * 60,
            replace_existing=True,
        )
        scheduler.start()

        runtime.polling_task = asyncio.create_task(
            dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                close_bot_session=False,
                tasks_concurrency_limit=50,
            ),
            name="telegram-polling",
        )
        heartbeat_task = asyncio.create_task(heartbeat_loop(), name="loop-heartbeat")
        database_probe_task = asyncio.create_task(
            database_probe_loop(),
            name="database-probe",
        )
        await asyncio.sleep(0)
        if runtime.polling_task.done():
            await runtime.polling_task

        web_runner = await start_web_server(settings.port)
        logger.info(
            "Bot @%s, scheduler and health server started",
            runtime.bot_username,
        )
        await runtime.polling_task
    finally:
        await cancel_task(database_probe_task)
        await cancel_task(heartbeat_task)
        await cancel_task(runtime.polling_task)
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if web_runner is not None:
            await web_runner.cleanup()
        if bot is not None:
            await bot.session.close()
        if db_pool is not None:
            await db_pool.close()

# Этот код нужно вставить в самом конце списка обработчиков (handlers)
@dp.message(F.text) # Если у тебя используется router, то @router.message(F.text)
async def handle_any_text(message: types.Message):
    # Здесь мы вызываем ту же функцию, что и при команде /start.
    # Посмотри в коде выше, как называется твоя функция для /start, 
    # обычно это cmd_start(message) или что-то подобное.
    await cmd_start(message) 
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Basketbot stopped because of a fatal error")
        raise
       



