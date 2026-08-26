import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReactionTypeEmoji

import charts
import storage
from article import extract_text
from config import (
    ALWAYS_SHOW,
    BOT_TOKEN,
    CHECKS_TOPIC_ID,
    GROUP_ID,
    IMPORT_TOPIC_ID,
    STATS_TOPIC_ID,
    TZ,
)
from keyboards import PERIODS, charts_kb, main_menu, sites_kb, stats_kb
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


def render_stats(code: str) -> str:
    d_from, d_to, title = resolve_period(code)
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
        details.append(f"🧾 {r['shifts']} смен")
        out.append("   " + " · ".join(details))
        out.append("")

    cur = {row["site"]: row["follows"] for row in storage.current_followers()}
    if cur:
        out.append("👤 <b>Всего подписчиков сейчас:</b>")
        for site, n in cur.items():
            out.append(f"   {site} — {n}")
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

async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN в .env")

    storage.init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_routers(utils_router, checks_router, stats_router, debug_router)

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
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено вручную")
