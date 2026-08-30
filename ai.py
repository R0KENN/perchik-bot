"""Короткий комментарий от ИИ после смены."""

import logging
import random

import aiohttp

from config import AI_BASE_URL, AI_ENABLED, AI_KEY, AI_MODEL, AI_PROVIDER, AI_TIMEOUT

log = logging.getLogger("perchik.ai")

SYSTEM = (
    "Ты — Перчик, бот-напарник, который ведёт учёт смен. "
    "По сухим цифрам смены пиши ОДНО-ДВА коротких предложения на русском: "
    "что заметил в цифрах и лёгкая поддержка. "
    "Без пафоса, без коучинга, без восклицательных знаков подряд, без хэштегов. "
    "Живой разговорный тон, можно с иронией. Максимум один эмодзи. "
    "Не выдумывай цифры, которых нет во вводных."
)

FALLBACK = [
    "Смена записана. Идём дальше.",
    "Записал. Хорошая работа сегодня.",
    "Готово. Цифры в базе, отдыхай.",
    "Учёл. Завтра посмотрим динамику.",
    "Записано. Стабильность — тоже результат.",
]


async def _anthropic(facts: str, system: str = SYSTEM) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": AI_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "max_tokens": 200,
        "system": system,
        "messages": [{"role": "user", "content": facts}],
    }
    timeout = aiohttp.ClientTimeout(total=AI_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(url, headers=headers, json=payload) as r:
            data = await r.json()
    if "content" not in data:
        raise RuntimeError(str(data)[:300])
    return "".join(b.get("text", "") for b in data["content"]).strip()


async def _openai(facts: str, system: str = SYSTEM) -> str:
    url = f"{AI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_KEY}", "content-type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": facts},
        ],
    }
    timeout = aiohttp.ClientTimeout(total=AI_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(url, headers=headers, json=payload) as r:
            data = await r.json()
    if "choices" not in data:
        raise RuntimeError(str(data)[:300])
    return data["choices"][0]["message"]["content"].strip()


async def shift_comment(facts: str) -> str:
    """Возвращает текст комментария. Никогда не бросает исключение."""
    if not (AI_ENABLED and AI_KEY):
        return random.choice(FALLBACK)
    try:
        text = await (_openai(facts) if AI_PROVIDER == "openai" else _anthropic(facts))
        text = text.strip().strip('"')
        return text[:400] if text else random.choice(FALLBACK)
    except Exception as e:
        log.warning("ИИ не ответил (%s), беру запасную фразу", e)
        return random.choice(FALLBACK)



CHAT_SYSTEM = (
    "Ты — Перчик, бот-напарник в рабочем чате. Ведёшь учёт смен и заработка. "
    "Отвечай коротко: одно-два предложения, по-русски, живым разговорным тоном, "
    "можно с лёгкой иронией. Без канцелярита, без коучинга, без списков. "
    "Максимум один эмодзи. Если спрашивают про цифры — отвечай только по тем данным, "
    "что тебе дали, ничего не выдумывай. Если данных нет, так и скажи."
)

CHAT_FALLBACK = [
    "Я тут, но мозги сейчас offline. Спроси попозже.",
    "Слышу тебя. Правда, ответить умного нечего.",
    "Тут я. Цифры смотри через /stats.",
]


async def chat_reply(prompt: str) -> str:
    """Свободный ответ в чате. Никогда не бросает исключение."""
    if not (AI_ENABLED and AI_KEY):
        return random.choice(CHAT_FALLBACK)
    try:
        if AI_PROVIDER == "openai":
            text = await _openai(prompt, CHAT_SYSTEM)
        else:
            text = await _anthropic(prompt, CHAT_SYSTEM)
        text = text.strip().strip('"')
        return text[:600] if text else random.choice(CHAT_FALLBACK)
    except Exception as e:
        log.warning("ИИ не ответил в чате (%s)", e)
        return random.choice(CHAT_FALLBACK)
