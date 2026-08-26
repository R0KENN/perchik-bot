from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

PERIODS = {
    "today": "Сегодня",
    "7": "7 дней",
    "30": "30 дней",
    "90": "90 дней",
    "cur": "Этот месяц",
    "prev": "Прошлый месяц",
    "365": "Год",
    "all": "Всё время",
}


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Сегодня", callback_data="st:today")
    kb.button(text="🗓 Неделя", callback_data="st:7")
    kb.button(text="🗓 30 дней", callback_data="st:30")
    kb.button(text="📆 Этот месяц", callback_data="st:cur")
    kb.button(text="♾ Всё время", callback_data="st:all")
    kb.button(text="🎯 Цель месяца", callback_data="goal:cur")
    kb.button(text="🌐 По сайтам", callback_data="sites:30")
    kb.button(text="📊 Графики", callback_data="charts:30")
    kb.button(text="🕒 Когда лучше", callback_data="when:30")
    kb.button(text="⚡ Эффективность", callback_data="eff:30")
    kb.adjust(2, 2, 1, 1, 2, 2)
    return kb.as_markup()


def stats_kb(period: str) -> InlineKeyboardMarkup:
    return back_kb([
        period_row("st", period),
        [
            InlineKeyboardButton(text="🌐 По сайтам", callback_data=f"sites:{period}"),
            InlineKeyboardButton(text="📊 Графики", callback_data=f"charts:{period}"),
        ],
        [
            InlineKeyboardButton(text="🕒 Когда лучше", callback_data=f"when:{period}"),
            InlineKeyboardButton(text="⚡ Эффективность", callback_data=f"eff:{period}"),
        ],
        [
            InlineKeyboardButton(text="🎯 Цель месяца", callback_data="goal:cur"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"st:{period}"),
        ],
    ])


def back_kb(extra_rows: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    rows = extra_rows or []
    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def period_row(prefix: str, active: str, codes=("7", "30", "cur", "all")) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=("• " if c == active else "") + PERIODS[c],
            callback_data=f"{prefix}:{c}",
        )
        for c in codes
    ]


def sites_kb(period: str) -> InlineKeyboardMarkup:
    return back_kb([
        period_row("sites", period),
        [InlineKeyboardButton(text="🥧 Диаграмма", callback_data=f"chart:pie:{period}")],
    ])


def charts_kb(period: str) -> InlineKeyboardMarkup:
    return back_kb([
        period_row("charts", period),
        [
            InlineKeyboardButton(text="💰 Доход", callback_data=f"chart:money:{period}"),
            InlineKeyboardButton(text="📈 Прирост", callback_data=f"chart:fans:{period}"),
        ],
        [
            InlineKeyboardButton(text="👥 Всего подписчиков", callback_data=f"chart:total:{period}"),
            InlineKeyboardButton(text="🥧 Доли", callback_data=f"chart:pie:{period}"),
        ],
    ])


def simple_kb(prefix: str, period: str) -> InlineKeyboardMarkup:
    """Клавиатура для экранов «когда лучше» / «эффективность»."""
    return back_kb([
        period_row(prefix, period),
        [InlineKeyboardButton(text="📈 Сводка", callback_data=f"st:{period}")],
    ])


def goal_kb() -> InlineKeyboardMarkup:
    return back_kb([
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="goal:cur"),
            InlineKeyboardButton(text="📆 Месяц", callback_data="st:cur"),
        ],
    ])
