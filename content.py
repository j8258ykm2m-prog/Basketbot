"""Default workout catalogue.

Text changes made here are safely synchronized to PostgreSQL on startup.
User data and materials already added through the bot are never overwritten.
"""

CATEGORIES = {
    "skills": "🏀 Навыки",
    "tactics": "🧠 Командная тактика",
    "positions": "⛹️ Позиции",
    "fitness": "🏋️ ОФП и Кардио",
    "rehab": "🩹 Профилактика",
    "mental": "🧘 Ментальность и Фокус",
}

DEFAULT_WORKOUTS = (
    # --- НАВЫКИ ---
    {
        "workout_id": "skill_dribble",
        "category": "skills",
        "title": "Дриблинг",
        "exp": 50,
        "description": "Контроль мяча, кроссоверы, переводы, работа слабой рукой.",
        "sort_order": 10,
    },
    {
        "workout_id": "skill_shoot",
        "category": "skills",
        "title": "Бросок",
        "exp": 60,
        "description": "Бросковая механика, постановка кисти, штрафные, catch-and-shoot.",
        "sort_order": 20,
    },
    {
        "workout_id": "skill_iso",
        "category": "skills",
        "title": "Обыгрыш 1х1",
        "exp": 60,
        "description": "Работа ног, джебы, создание преимущества, игра на изоляции.",
        "sort_order": 30,
    },
    {
        "workout_id": "skill_def",
        "category": "skills",
        "title": "Индивидуальная защита",
        "exp": 50,
        "description": "Защитная стойка, перемещения, прессинг игрока с мячом.",
        "sort_order": 40,
    },

    # --- ТАКТИКА ---
    {
        "workout_id": "tac_5x5_off",
        "category": "tactics",
        "title": "Нападение 5х5",
        "exp": 80,
        "description": "Движение мяча, комбинации, транзитное нападение.",
        "sort_order": 50,
    },
    {
        "workout_id": "tac_5x5_def",
        "category": "tactics",
        "title": "Защита 5х5",
        "exp": 80,
        "description": "Зонная защита, ротация, правильная подстраховка.",
        "sort_order": 60,
    },
    {
        "workout_id": "tac_spacing",
        "category": "tactics",
        "title": "Пространство (Спейсинг)",
        "exp": 70,
        "description": "Понимание площадки, заполнение углов, как не мешать партнерам.",
        "sort_order": 70,
    },
    {
        "workout_id": "tac_2x2_screens",
        "category": "tactics",
        "title": "Взаимодействие 2х2 (Заслоны)",
        "exp": 70,
        "description": "Пик-н-ролл, пик-н-поп, хэндоффы и чтение защиты.",
        "sort_order": 80,
    },

    # --- ПОЗИЦИИ ---
    {
        "workout_id": "pos_pg",
        "category": "positions",
        "title": "Разыгрывающий (PG)",
        "exp": 100,
        "description": "Чтение игры, элитный пас, флоутеры, темп.",
        "sort_order": 90,
    },
    {
        "workout_id": "pos_wings",
        "category": "positions",
        "title": "Универсалы (SG/SF/PF)",
        "exp": 100,
        "description": "Игра без мяча, проходы, завершение через контакт, игра лицом к кольцу.",
        "sort_order": 100,
    },
    {
        "workout_id": "pos_c",
        "category": "positions",
        "title": "Центровой (C)",
        "exp": 100,
        "description": "Работа в усах (post-up), подборы на обоих щитах, блокшоты.",
        "sort_order": 110,
    },

    # --- ПРОФИЛАКТИКА ---
    {
        "workout_id": "reh_warmup",
        "category": "rehab",
        "title": "Общая разминка",
        "exp": 30,
        "description": "Активация мышц, суставная гимнастика, подготовка к нагрузке.",
        "sort_order": 120,
    },
    {
        "workout_id": "reh_knee",
        "category": "rehab",
        "title": "Колени",
        "exp": 40,
        "description": "Изометрия, закачка связок, профилактика «колена прыгуна».",
        "sort_order": 130,
    },
    {
        "workout_id": "reh_ankle",
        "category": "rehab",
        "title": "Голеностоп",
        "exp": 40,
        "description": "Укрепление связок стопы, баланс на полусфере, работа с резиной.",
        "sort_order": 140,
    },

    # --- МЕНТАЛЬНОСТЬ ---
    {
        "workout_id": "men_clutch",
        "category": "mental",
        "title": "Клатч-менталитет",
        "exp": 50,
        "description": "Как не бояться решающего броска. Психология победителя.",
        "sort_order": 150,
    },
    {
        "workout_id": "men_burnout",
        "category": "mental",
        "title": "Как не выгорать от тренировок",
        "exp": 50,
        "description": "Мотивация, преодоление плато, правильный баланс отдыха и работы.",
        "sort_order": 160,
    },

    # --- ОФП ---
    {
        "workout_id": "fit_cardio",
        "category": "fitness",
        "title": "Баскетбольное кардио",
        "exp": 60,
        "description": "Челночный бег, интервалы, выносливость.",
        "sort_order": 170,
    },
)


