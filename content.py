"""Default workout catalogue.

Text changes made here are safely synchronized to PostgreSQL on startup.
User data and materials already added through the bot are never overwritten.
"""

CATEGORIES = {
    "skills": "🏀 Базовые навыки",
    "tactics": "🧠 Командная тактика",
    "positions": "⛹️ Позиционная работа",
    "fitness": "🏋️ ОФП и Кардио",
    "rehab": "🩹 Профилактика (ТОП-10 травм)",
    "mental": "🧘 Ментальность и Фокус",
}


DEFAULT_WORKOUTS = (
    {
        "workout_id": "dribble_base",
        "category": "skills",
        "title": "Основы дриблинга",
        "exp": 50,
        "description": "Контроль мяча, кроссоверы, переводы.",
        "sort_order": 10,
    },
    {
        "workout_id": "shoot_base",
        "category": "skills",
        "title": "Бросковая механика",
        "exp": 60,
        "description": "Постановка кисти, штрафные, catch-and-shoot.",
        "sort_order": 20,
    },
    {
        "workout_id": "tac_3x3_off",
        "category": "tactics",
        "title": "Нападение 3х3",
        "exp": 70,
        "description": "Спейсинг, пик-н-ролл, изоляции.",
        "sort_order": 30,
    },
    {
        "workout_id": "tac_5x5_def",
        "category": "tactics",
        "title": "Защита 5х5",
        "exp": 80,
        "description": "Зонная защита, ротация, подстраховка.",
        "sort_order": 40,
    },
    {
        "workout_id": "pos_pg",
        "category": "positions",
        "title": "Разыгрывающий (PG)",
        "exp": 100,
        "description": "Чтение игры, элитный пас, флоутеры.",
        "sort_order": 50,
    },
    {
        "workout_id": "pos_c",
        "category": "positions",
        "title": "Центровой (C)",
        "exp": 100,
        "description": "Работа в усах (post-up), подборы, блокшоты.",
        "sort_order": 60,
    },
    {
        "workout_id": "fit_cardio",
        "category": "fitness",
        "title": "Баскетбольное кардио",
        "exp": 60,
        "description": "Челночный бег, интервалы, выносливость.",
        "sort_order": 70,
    },
    {
        "workout_id": "reh_ankle",
        "category": "rehab",
        "title": "Голеностоп (Растяжения)",
        "exp": 40,
        "description": "Закачка связок, баланс на полусфере.",
        "sort_order": 80,
    },
    {
        "workout_id": "reh_knee",
        "category": "rehab",
        "title": "Колено Прыгуна",
        "exp": 40,
        "description": "Изометрия, снятие воспаления с сухожилия.",
        "sort_order": 90,
    },
    {
        "workout_id": "reh_achill",
        "category": "rehab",
        "title": "Ахиллово сухожилие",
        "exp": 40,
        "description": "Эксцентрические подъемы, растяжка икр.",
        "sort_order": 100,
    },
    {
        "workout_id": "men_clutch",
        "category": "mental",
        "title": "Клатч-менталитет",
        "exp": 50,
        "description": "Как не бояться решающего броска. Психология победителя.",
        "sort_order": 110,
    },
)
