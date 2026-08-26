import asyncio
import calendar
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ChatMemberUpdated,
    Message,
    ReactionTypeEmoji,
)

import charts
import storage
from article import extract_text
from config import (
    ALWAYS_SHOW,
    AUTO_REPORTS,
    BOT_TOKEN,
    CHECKS_TOPIC_ID,
    GROUP_ID,
    IMPORT_TOPIC_ID,
    MONTH_REPORT_HOUR,
    REPORT_HOUR,
    REPORT_WEEKDAY,
    STATS_TOPIC_ID,
    TZ,
)
from keyboards import PERIODS, charts_kb, goal_kb, main_menu, simple_kb, sites_kb, stats_kb
from parser import parse_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("perchik")

utils_router = Router(name="utils")
checks_router = Router(name="checks")
stats_router = Router(name="stats")
debug_router = Router(name="debug")

guard_router = Router(name="guard")

# ---------- доступ ----------
# Бот работает только в GROUP_ID. Всем остальным — от ворот поворот.

DENY_TEXT = "Ты че стучишься ?? Тебя не звали"
_denied_at: dict[int, float] = {}


def foreign_chat(event) -> bool:
    """True для любого чата, кроме нашей группы."""
    return event.chat.id != GROUP_ID


def foreign_callback(call: CallbackQuery) -> bool:
    return call.message is None or call.message.chat.id != GROUP_ID


@guard_router.message(foreign_chat)
async def deny_message(message: Message) -> None:
    u = message.from_user
    log.info(
        "Чужой чат %s (%s) от %s (@%s)",
        message.chat.id, message.chat.type,
        u.id if u else "?", u.username if u else "?",
    )
    # отвечаем не чаще раза в 10 минут на чат, чтобы не кормить спамеров
    now = datetime.now(TZ).timestamp()
    if now - _denied_at.get(message.chat.id, 0) < 600:
        return
    _denied_at[message.chat.id] = now
    try:
        await message.answer(DENY_TEXT)
    except Exception as e:
        log.info("Ответить не смог: %s", e)


@guard_router.edited_message(foreign_chat)
async def deny_edited(message: Message) -> None:
    return


@guard_router.callback_query(foreign_callback)
async def deny_callback(call: CallbackQuery) -> None:
    await call.answer(DENY_TEXT, show_alert=True)


@guard_router.my_chat_member(foreign_chat)
async def leave_foreign(event: ChatMemberUpdated, bot: Bot) -> None:
    """Если добавили в посторонний чат — выходим."""
    if event.chat.type in ("group", "supergroup", "channel"):
        log.warning("Добавили в чужой чат %s — выхожу", event.chat.id)
        try:
            await bot.leave_chat(event.chat.id)
        except Exception as e:
            log.info("Выйти не смог: %s", e)


# ---------- вспомогательное ----------

def today() -> date:
    return datetime.now(TZ).date()


def money(v: float) -> str:
    return f"{v:,.2f}$".replace(",", " ")


def resolve_period(code: str) -> tuple[date, date, str]:
    t = today()
    if code == "today":
        return t, t, "Сегодня"
    if code == "7":
        return t - timedelta(days=6), t, "7 дней"
    if code == "30":
        return t - timedelta(days=29), t, "30 дней"
    if code == "90":
        return t - timedelta(days=89), t, "90 дней"
    if code == "365":
        return t - timedelta(days=364), t, "Год"
    if code == "cur":
        return t.replace(day=1), t, "Текущий месяц"
    if code == "prev":
        first = t.replace(day=1)
        prev_end = first - timedelta(days=1)
        return prev_end.replace(day=1), prev_end, "Прошлый месяц"
    start = storage.first_date() or t
    return start, t, "Всё время"


def site_rows(d_from: date, d_to: date) -> list[dict]:
    """Все площадки за период + те, что должны быть видны всегда."""
    rows = [dict(r) for r in storage.by_site(d_from, d_to)]
    known = {r["site"] for r in rows}
    for site in ALWAYS_SHOW:
        if site not in known:
            rows.append({"site": site, "usd": 0.0, "tokens": 0, "shifts": 0})
    rows.sort(key=lambda r: (-r["usd"], r["site"]))
    return rows

def shifts_word(n: int) -> str:
    """1 смена / 2 смены / 5 смен."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} смена"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} смены"
    return f"{n} смен"

WEEKDAYS = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
WEEKDAYS_SHORT = ["ВС", "ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ"]
MONTHS_RU = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
             "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def month_ru(d: date) -> str:
    return f"{MONTHS_RU[d.month].capitalize()} {d.year}"

PREV_LABEL = {
    "today": "вчера",
    "7": "прошлой неделе",
    "30": "прошлым 30 дням",
    "90": "прошлым 90 дням",
    "365": "прошлому году",
    "cur": "прошлому месяцу",
    "prev": "позапрошлому месяцу",
}


def prev_range(code: str, d_from: date, d_to: date) -> tuple[date, date] | None:
    """Предыдущий сопоставимый период."""
    if code == "all":
        return None
    if code in ("cur", "prev"):
        prev_last = d_from - timedelta(days=1)
        p_from = prev_last.replace(day=1)
        p_to = min(prev_last, p_from + timedelta(days=(d_to - d_from).days))
        return p_from, p_to
    n = (d_to - d_from).days + 1
    return d_from - timedelta(days=n), d_from - timedelta(days=1)


def delta_line(cur_usd: float, code: str, d_from: date, d_to: date) -> str | None:
    rng = prev_range(code, d_from, d_to)
    if not rng:
        return None
    prev = storage.period_summary(rng[0], rng[1])
    if not prev["shifts"] or not prev["usd"]:
        return None
    label = PREV_LABEL.get(code, "прошлому периоду")
    diff = cur_usd - prev["usd"]
    pct = diff / prev["usd"] * 100
    arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "▪️")
    return f"{arrow} <b>{pct:+.0f}%</b> к {label} ({money(prev['usd'])})"


def render_stats(code: str) -> str:
    d_from, d_to, title = resolve_period(code)
    return render_stats_range(d_from, d_to, title, code)


def render_stats_range(d_from: date, d_to: date, title: str, code: str = "") -> str:
    s = storage.period_summary(d_from, d_to)
    if not s["shifts"]:
        return f"🌶 <b>{title}</b>\nПока нет ни одного чека за этот период."

    gains = storage.gains_by_site(d_from, d_to)
    total_gain = sum(gains.values())
    avg = s["usd"] / s["shifts"]

    lines = [
        f"🌶 <b>Статистика · {title}</b>",
        f"<i>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</i>",
        "",
        f"💰 Заработано: <b>{money(s['usd'])}</b>",
    ]
    d = delta_line(s["usd"], code, d_from, d_to)
    if d:
        lines.append(d)
    lines += [
        f"🧾 Смен: <b>{s['shifts']}</b>" + (f" ({s['hours']:.1f} ч)" if s["hours"] else ""),
        f"📈 Средняя смена: <b>{money(avg)}</b>",
    ]
    if s["hours"]:
        lines.append(f"⏱ В час: <b>{money(s['usd'] / s['hours'])}</b>")
    if total_gain:
        lines.append(f"👥 Прирост подписчиков: <b>+{total_gain}</b>")
    if s["tokens"]:
        lines.append(f"🪙 Токенов: <b>{int(s['tokens'])}</b>")

    rows = site_rows(d_from, d_to)
    if rows:
        lines += ["", "<b>По сайтам:</b>"]
        for r in rows:
            if not r["usd"]:
                lines.append(f"• {r['site']} — <i>нет данных</i>")
                continue
            share = (r["usd"] / s["usd"] * 100) if s["usd"] else 0
            g = gains.get(r["site"], 0)
            suffix = f" · +{g} 👥" if g else ""
            lines.append(f"• {r['site']} — <b>{money(r['usd'])}</b> ({share:.0f}%){suffix}")

    cur = storage.current_followers()
    if cur:
        parts = ", ".join(f"{r['site']} {r['follows']}" for r in cur)
        lines += ["", f"👤 <b>Сейчас всего:</b> {parts}"]

    if s["best_date"]:
        best = date.fromisoformat(s["best_date"])
        lines += ["", f"🏆 Лучшая смена: {best.strftime('%d.%m')} — {money(s['best_usd'])}"]

    goal_hint = goal_progress_line()
    if goal_hint:
        lines += ["", goal_hint]
    return "\n".join(lines)

def render_sites(code: str) -> str:
    d_from, d_to, title = resolve_period(code)
    rows = site_rows(d_from, d_to)
    if not rows:
        return f"🌐 <b>{title}</b>\nДанных нет."

    gains = storage.gains_by_site(d_from, d_to)
    total = sum(r["usd"] for r in rows) or 1
    out = [
        f"🌐 <b>Разбивка по сайтам · {title}</b>",
        f"<i>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</i>",
        "",
    ]
    for r in rows:
        if not r["usd"]:
            out.append(f"<b>{r['site']}</b> — <i>нет данных за период</i>")
            out.append("")
            continue
        share = r["usd"] / total * 100
        bar = "█" * max(1, round(share / 5))
        out.append(f"<b>{r['site']}</b> — {money(r['usd'])} ({share:.1f}%)")
        out.append(f"<code>{bar}</code>")

        details = []
        if r["tokens"]:
            details.append(f"🪙 {int(r['tokens'])} tk")
        if gains.get(r["site"]):
            details.append(f"👥 +{gains[r['site']]}")
        details.append(f"🧾 {shifts_word(r['shifts'])}")
        out.append("   " + " · ".join(details))
        out.append("")

    cur = {row["site"]: row["follows"] for row in storage.current_followers()}
    if cur:
        out.append("👤 <b>Всего подписчиков сейчас:</b>")
        for site, n in cur.items():
            out.append(f"   {site} — {n}")
    return "\n".join(out)

# ---------- цель на месяц ----------

def _month_bounds(d: date) -> tuple[date, date, int]:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=1), d.replace(day=last_day), last_day


def goal_progress_line() -> str | None:
    """Короткая строчка про цель — подмешивается в сводку."""
    t = today()
    goal = storage.get_goal(t.strftime("%Y-%m"))
    if not goal:
        return None
    first, _, _ = _month_bounds(t)
    earned = storage.period_summary(first, t)["usd"]
    pct = earned / goal * 100
    return f"🎯 Цель месяца: {money(earned)} / {money(goal)} ({pct:.0f}%)"


def render_goal() -> str:
    t = today()
    ym = t.strftime("%Y-%m")
    goal = storage.get_goal(ym)
    first, last, days_in_month = _month_bounds(t)
    s = storage.period_summary(first, t)
    earned = s["usd"]

    if not goal:
        return (
            "🎯 <b>Цель на месяц не задана</b>\n\n"
            f"Заработано с 1-го числа: <b>{money(earned)}</b>\n\n"
            "Задать цель: <code>/goal 3000</code>\n"
            "Снять цель: <code>/goal 0</code>"
        )

    pct = earned / goal * 100
    left = max(0.0, goal - earned)
    days_passed = t.day
    days_left = days_in_month - days_passed
    pace = earned / days_passed if days_passed else 0
    forecast = pace * days_in_month

    filled = min(20, round(pct / 5))
    bar = "█" * filled + "░" * (20 - filled)

    lines = [
        f"🎯 <b>Цель на {month_ru(t)}</b>",
        "",
        f"<code>{bar}</code> {pct:.0f}%",
        f"💰 {money(earned)} из {money(goal)}",
    ]
    if left:
        lines.append(f"📌 Осталось добить: <b>{money(left)}</b>")
    else:
        lines.append("✅ Цель выполнена!")

    lines += [
        "",
        f"📆 Прошло дней: {days_passed} из {days_in_month} (осталось {days_left})",
        f"⚡ Текущий темп: {money(pace)} в день",
        f"🔮 Прогноз на месяц: <b>{money(forecast)}</b>"
        + (" ✅" if forecast >= goal else " ⚠️"),
    ]
    if left and days_left:
        lines.append(f"🏃 Нужно по <b>{money(left / days_left)}</b> в день")
    elif left and not days_left:
        lines.append("⏳ Сегодня последний день месяца.")
    return "\n".join(lines)


# ---------- когда работать выгоднее ----------

def render_when(code: str) -> str:
    d_from, d_to, title = resolve_period(code)
    dows = storage.by_weekday(d_from, d_to)
    if not dows:
        return f"🕒 <b>{title}</b>\nДанных нет."

    out = [
        f"🕒 <b>Когда смены прибыльнее · {title}</b>",
        f"<i>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</i>",
        "",
        "<b>По дням недели</b> (средняя смена):",
    ]
    ordered = sorted(dows, key=lambda r: -(r["usd"] / r["shifts"] if r["shifts"] else 0))
    top = ordered[0]["usd"] / ordered[0]["shifts"] if ordered[0]["shifts"] else 1
    for r in ordered:
        avg = r["usd"] / r["shifts"] if r["shifts"] else 0
        bar = "█" * max(1, round(avg / top * 12))
        out.append(
            f"<b>{WEEKDAYS_SHORT[r['dow']]}</b> <code>{bar}</code> "
            f"{money(avg)} · {shifts_word(r['shifts'])}"
        )

    hours = storage.by_hour(d_from, d_to)
    if hours:
        out += ["", "<b>По времени начала смены:</b>"]
        for r in sorted(hours, key=lambda x: -(x["usd"] / x["shifts"] if x["shifts"] else 0)):
            avg = r["usd"] / r["shifts"] if r["shifts"] else 0
            out.append(f"• {r['h']:02d}:00 — {money(avg)} за смену ({shifts_word(r['shifts'])})")

    best = ordered[0]
    if best["shifts"]:
        out += [
            "",
            f"🏆 Лучший день: <b>{WEEKDAYS[best['dow']]}</b> — "
            f"{money(best['usd'] / best['shifts'])} в среднем",
        ]
    return "\n".join(out)


# ---------- эффективность площадок ----------

def render_eff(code: str) -> str:
    d_from, d_to, title = resolve_period(code)
    rows = [r for r in storage.site_efficiency(d_from, d_to) if r["usd"]]
    if not rows:
        return f"⚡ <b>{title}</b>\nДанных нет."

    ranked = []
    for r in rows:
        per_hour = r["usd"] / r["hours"] if r["hours"] else None
        ranked.append((r["site"], r["usd"], r["shifts"], per_hour,
                       r["usd"] / r["shifts"] if r["shifts"] else 0))
    ranked.sort(key=lambda x: -(x[3] or 0))

    out = [
        f"⚡ <b>Эффективность площадок · {title}</b>",
        f"<i>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</i>",
        "",
    ]
    top = ranked[0][3] or 0
    for site, usd, shifts, per_hour, per_shift in ranked:
        if per_hour:
            bar = "█" * max(1, round(per_hour / top * 12)) if top else ""
            out.append(f"<b>{site}</b> — {money(per_hour)}/час")
            out.append(f"<code>{bar}</code>")
        else:
            out.append(f"<b>{site}</b> — <i>нет данных о часах</i>")
        out.append(f"   💰 {money(usd)} · 🧾 {shifts_word(shifts)} · {money(per_shift)} за смену")
        out.append("")

    weak = [r for r in ranked if r[3] is not None]
    if len(weak) > 1:
        out.append(
            f"🐌 Слабее всех: <b>{weak[-1][0]}</b> — {money(weak[-1][3])}/час "
            f"против {money(weak[0][3])}/час у {weak[0][0]}."
        )
    out.append("<i>Часы смены засчитываются каждому сайту, где был доход.</i>")
    return "\n".join(out)

# ---------- служебные команды ----------

@utils_router.message(Command("id"))
async def cmd_id(message: Message):
    await message.reply(
        "🆔 <b>ID для .env</b>\n"
        f"GROUP_ID = <code>{message.chat.id}</code>\n"
        f"TOPIC_ID = <code>{message.message_thread_id or 0}</code>",
        parse_mode=ParseMode.HTML,
    )


@utils_router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🌶 Привет, я <b>Перчик</b>.\n"
        "Читаю топик с чеками и считаю статистику.\n"
        "Напиши в моём топике «<b>Перчик дай стату</b>» или /stats.",
        parse_mode=ParseMode.HTML,
    )


@utils_router.message(Command("dump"))
async def cmd_dump(message: Message):
    target = message.reply_to_message
    if not target:
        await message.reply("Ответь этой командой на чек — покажу, что я из него вижу.")
        return

    text = extract_text(target)
    if not text:
        filled = [
            k for k, v in target.model_dump(exclude_none=True).items()
            if k not in ("message_id", "date", "chat", "from_user", "message_thread_id")
        ]
        await message.reply(
            "❌ Текст извлечь не удалось.\n"
            f"Поля сообщения: <code>{', '.join(filled) or '—'}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    parsed = parse_check(text, target.date.astimezone(TZ).date())
    head = f"<b>Извлечённый текст:</b>\n<pre>{text[:2500]}</pre>"
    if parsed:
        sites = "\n".join(
            f"  {e.site}: {e.usd}$ / {int(e.tokens)} tk / +{e.follows}" for e in parsed.entries
        )
        head += (
            f"\n\n<b>Распознано:</b>\nДата: {parsed.shift_date}\n"
            f"Итого: {parsed.total_usd}$\n{sites}"
        )
    else:
        head += "\n\n❌ Как чек не распознано."
    await message.reply(head, parse_mode=ParseMode.HTML)

@utils_router.message(Command("dedupe"))
async def cmd_dedupe(message: Message):
    n = storage.dedupe()
    await message.reply(f"🧹 Удалено дублей: {n}")


@utils_router.message(Command("sites"))
async def cmd_sites(message: Message):
    rows = storage.all_sites()
    if not rows:
        await message.reply("В базе пока нет площадок.")
        return
    body = "\n".join(
        f"• <b>{r['site']}</b> — {r['n']} записей, {money(r['usd'] or 0)}" for r in rows
    )
    await message.reply(
        f"🌐 <b>Все площадки в базе</b>\n{body}\n\n"
        "<i>Если название криво или площадки не хватает — добавь её "
        "в SITE_ALIASES в config.py.</i>",
        parse_mode=ParseMode.HTML,
    )

@utils_router.message(Command("goal"))
async def cmd_goal(message: Message, command: CommandObject):
    arg = (command.args or "").strip().replace(",", ".").replace("$", "")
    if arg:
        try:
            amount = float(arg)
        except ValueError:
            await message.reply("Не понял сумму. Пример: <code>/goal 3000</code>",
                                parse_mode=ParseMode.HTML)
            return
        ym = today().strftime("%Y-%m")
        storage.set_goal(ym, amount)
        if amount <= 0:
            await message.reply("🎯 Цель на этот месяц снята.")
            return
        await message.reply(f"🎯 Цель на месяц: <b>{money(amount)}</b>", parse_mode=ParseMode.HTML)
    await message.answer(render_goal(), reply_markup=goal_kb(), parse_mode=ParseMode.HTML)


@utils_router.message(Command("when"))
async def cmd_when(message: Message):
    await message.answer(render_when("30"), reply_markup=simple_kb("when", "30"),
                         parse_mode=ParseMode.HTML)


@utils_router.message(Command("eff"))
async def cmd_eff(message: Message):
    await message.answer(render_eff("30"), reply_markup=simple_kb("eff", "30"),
                         parse_mode=ParseMode.HTML)


@utils_router.message(Command("report_week"))
async def cmd_report_week(message: Message, bot: Bot):
    await weekly_report(bot)
    await message.reply("📨 Недельный отчёт отправлен.")


@utils_router.message(Command("report_month"))
async def cmd_report_month(message: Message, bot: Bot):
    await monthly_report(bot)
    await message.reply("📨 Месячный отчёт отправлен.")


# ---------- сбор чеков ----------

CHECK_TOPICS = {CHECKS_TOPIC_ID}
if IMPORT_TOPIC_ID:
    CHECK_TOPICS.add(IMPORT_TOPIC_ID)

checks_router.message.filter(F.chat.id == GROUP_ID, F.message_thread_id.in_(CHECK_TOPICS))
checks_router.edited_message.filter(F.chat.id == GROUP_ID, F.message_thread_id.in_(CHECK_TOPICS))


async def handle_check(message: Message, bot: Bot, edited: bool = False):
    text = extract_text(message)
    if not text:
        return
    fallback = message.date.astimezone(TZ).date()
    parsed = parse_check(text, fallback)
    if not parsed:
        log.info("Сообщение %s не похоже на чек", message.message_id)
        return

    storage.upsert_shift(message.chat.id, message.message_id, message.message_thread_id, parsed)
    log.info(
        "%s чек: %s | %s$ | сайтов: %d",
        "Обновлён" if edited else "Записан",
        parsed.shift_date, parsed.total_usd, len(parsed.entries),
    )
    try:
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji="👌")],
        )
    except Exception as e:
        log.debug("Реакция не поставилась: %s", e)


@checks_router.message(Command("forget"))
async def cmd_forget(message: Message):
    if not message.reply_to_message:
        await message.reply("Ответь этой командой на чек, который надо забыть.")
        return
    ok = storage.delete_shift(message.chat.id, message.reply_to_message.message_id)
    await message.reply("🗑 Забыл этот чек." if ok else "Такого чека нет в базе.")


@checks_router.message()
async def on_check(message: Message, bot: Bot):
    await handle_check(message, bot)


@checks_router.edited_message()
async def on_check_edited(message: Message, bot: Bot):
    await handle_check(message, bot, edited=True)


# ---------- статистика ----------

async def show(call: CallbackQuery, text: str, kb) -> None:
    """Правит текст сообщения; под фото — присылает новое."""
    if call.message.photo or call.message.text is None:
        await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return
        await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@stats_router.message(Command("stats"))
@stats_router.message(F.text.regexp(r"(?i)^\s*(перчик|перец|перчику|стат[ауы]?|статистика)\b"))
async def cmd_stats(message: Message):
    text = (message.text or "").lower()
    code = "30"
    if "недел" in text or " 7" in text:
        code = "7"
    elif "месяц" in text:
        code = "cur"
    elif "всё" in text or "все врем" in text or "всего" in text:
        code = "all"
    elif "сегодня" in text or "смена" in text:
        code = "today"
    elif "год" in text:
        code = "365"

    await message.answer(
        render_stats(code),
        reply_markup=stats_kb(code),
        parse_mode=ParseMode.HTML,
    )


@stats_router.message(Command("last"))
async def cmd_last(message: Message):
    rows = storage.last_shifts(7)
    if not rows:
        await message.reply("База пустая.")
        return

    lines = []
    for r in rows:
        d = date.fromisoformat(r["shift_date"]).strftime("%d.%m")
        if r["time_start"] and r["time_end"]:
            when = f"{d} ({r['time_start']}–{r['time_end']})"
        else:
            when = d
        lines.append(f"• {when} — {money(r['total_usd'])}")

    await message.reply(
        "🧾 <b>Последние чеки</b>\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


@stats_router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    await show(
        call,
        "🌶 <b>Перчик · меню статистики</b>\nВыбери период или раздел:",
        main_menu(),
    )
    await call.answer()


@stats_router.callback_query(F.data.startswith("st:"))
async def cb_stats(call: CallbackQuery):
    code = call.data.split(":")[1]
    await show(call, render_stats(code), stats_kb(code))
    await call.answer(PERIODS.get(code, ""))


@stats_router.callback_query(F.data.startswith("sites:"))
async def cb_sites(call: CallbackQuery):
    code = call.data.split(":")[1]
    await show(call, render_sites(code), sites_kb(code))
    await call.answer()


@stats_router.callback_query(F.data.startswith("charts:"))
async def cb_charts_menu(call: CallbackQuery):
    code = call.data.split(":")[1]
    _, _, title = resolve_period(code)
    await show(call, f"📊 <b>Графики · {title}</b>\nВыбери, что нарисовать:", charts_kb(code))
    await call.answer()

@stats_router.callback_query(F.data.startswith("goal:"))
async def cb_goal(call: CallbackQuery):
    await show(call, render_goal(), goal_kb())
    await call.answer()


@stats_router.callback_query(F.data.startswith("when:"))
async def cb_when(call: CallbackQuery):
    code = call.data.split(":")[1]
    await show(call, render_when(code), simple_kb("when", code))
    await call.answer()


@stats_router.callback_query(F.data.startswith("eff:"))
async def cb_eff(call: CallbackQuery):
    code = call.data.split(":")[1]
    await show(call, render_eff(code), simple_kb("eff", code))
    await call.answer()

@stats_router.callback_query(F.data.startswith("chart:"))
async def cb_chart(call: CallbackQuery):
    _, kind, code = call.data.split(":")
    d_from, d_to, title = resolve_period(code)
    await call.answer("Рисую…")

    def build() -> tuple[bytes, str]:
        if kind == "money":
            return (charts.income_chart(storage.daily_money(d_from, d_to), d_from, d_to, title),
                    f"💰 Доход · {title}")
        if kind == "fans":
            return (charts.follows_chart(storage.gains_daily(d_from, d_to), d_from, d_to, title),
                    f"📈 Прирост подписчиков · {title}")
        if kind == "total":
            return (charts.followers_total_chart(storage.followers_series(d_from, d_to), title),
                    f"👥 Всего подписчиков · {title}")
        return charts.sites_pie(storage.by_site(d_from, d_to), title), f"🥧 Доли сайтов · {title}"

    png, caption = await asyncio.to_thread(build)
    await call.message.answer_photo(
        BufferedInputFile(png, filename="perchik.png"),
        caption=caption,
        reply_markup=charts_kb(code),
    )


@debug_router.message()
async def any_message(message: Message):
    log.info(
        "Необработанное: chat=%s thread=%s type=%s rich=%s",
        message.chat.id,
        message.message_thread_id,
        message.content_type,
        getattr(message, "rich_message", None) is not None,
    )

# ---------- автоотчёты ----------

async def send_report(bot: Bot, d_from: date, d_to: date, title: str,
                      code: str, head: str) -> None:
    if not GROUP_ID:
        log.warning("Автоотчёт пропущен: не задан GROUP_ID")
        return
    kw = {"message_thread_id": STATS_TOPIC_ID} if STATS_TOPIC_ID else {}
    text = head + "\n\n" + render_stats_range(d_from, d_to, title, code)
    await bot.send_message(GROUP_ID, text, reply_markup=stats_kb(code),
                           parse_mode=ParseMode.HTML, **kw)
    try:
        png = await asyncio.to_thread(
            charts.income_chart, storage.daily_money(d_from, d_to), d_from, d_to, title
        )
        await bot.send_photo(
            GROUP_ID, BufferedInputFile(png, filename="report.png"),
            caption=f"💰 Доход · {title}", **kw
        )
    except Exception as e:
        log.warning("График к автоотчёту не построился: %s", e)


async def weekly_report(bot: Bot) -> None:
    t = today()
    d_from, d_to = t - timedelta(days=6), t
    await send_report(bot, d_from, d_to, "Неделя", "7", "📅 <b>Итоги недели</b>")


async def monthly_report(bot: Bot) -> None:
    prev_end = today().replace(day=1) - timedelta(days=1)
    d_from = prev_end.replace(day=1)
    title = month_ru(prev_end)
    await send_report(bot, d_from, prev_end, title, "prev", "📆 <b>Итоги месяца</b>")


async def scheduler(bot: Bot) -> None:
    """Каждые 5 минут проверяет, не пора ли слать отчёт. Дубли режет через meta."""
    await asyncio.sleep(10)
    while True:
        try:
            now = datetime.now(TZ)
            if now.weekday() == REPORT_WEEKDAY and now.hour >= REPORT_HOUR:
                iso = now.isocalendar()
                key = f"week:{iso[0]}-{iso[1]}"
                if storage.meta_get(key) is None:
                    storage.meta_set(key, now.isoformat())
                    log.info("Отправляю недельный автоотчёт")
                    await weekly_report(bot)

            if now.day == 1 and now.hour >= MONTH_REPORT_HOUR:
                prev_end = now.date().replace(day=1) - timedelta(days=1)
                key = f"month:{prev_end.strftime('%Y-%m')}"
                if storage.meta_get(key) is None:
                    storage.meta_set(key, now.isoformat())
                    log.info("Отправляю месячный автоотчёт")
                    await monthly_report(bot)
        except Exception:
            log.exception("Ошибка планировщика")
        await asyncio.sleep(300)


async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN в .env")

    storage.init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_routers(guard_router, utils_router, stats_router, checks_router, debug_router)

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        log.error("Telegram отклонил токен (401). Проверь BOT_TOKEN в .env")
        await bot.session.close()
        return

    try:
        log.info("🌶 Перчик запущен: @%s", me.username)
        log.info(
            "Группа: %s | чеки: %s | импорт: %s | стата: %s",
            GROUP_ID, CHECKS_TOPIC_ID, IMPORT_TOPIC_ID or "—", STATS_TOPIC_ID,
        )
        await bot.delete_webhook(drop_pending_updates=True)
        if AUTO_REPORTS:
            report_task = asyncio.create_task(scheduler(bot))
            report_task.add_done_callback(lambda t: t.exception())
            log.info(
                "Автоотчёты включены: %s %02d:00 (неделя), 1-е число %02d:00 (месяц)",
                WEEKDAYS[(REPORT_WEEKDAY + 1) % 7], REPORT_HOUR, MONTH_REPORT_HOUR,
            )
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено вручную")
