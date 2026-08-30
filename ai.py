"""Короткий комментарий от ИИ после смены."""

import logging
import random

import aiohttp

from config import AI_BASE_URL, AI_ENABLED, AI_KEY, AI_MODEL, AI_PROVIDER, AI_TIMEOUT

log = logging.getLogger("perchik.ai")

SYSTEM = (
    "Ты — Перчик, бот-напарник вебкам-модели. Твоя манера: дерзкая, "
    "нахальная, с флиртом и двусмысленностями, но без прямой похабщины. "
    "Ты как подруга из индустрии — своя в доску, шутишь про токены, "
    "щедрых китов и скупых зрителей. Комментируешь смену: если заработок "
    "хороший — хвалишь с восторгом и подколкой, если слабый — подбадриваешь "
    "с иронией, без нытья. Пиши 1-2 предложения, живым разговорным языком, "
    "можно с эмодзи. Никакой канцелярщины и мотивационных банальностей."
)

FALLBACK = [
    "Смена закрыта, деньги в кармане 🔥",
    "Ну вот, а кто-то говорил, что не получится 😏",
    "Токены сами себя не заработали. Красавцы!",
    "Записал. Зрители сегодня не поскупились 💸",
    "Отработали — теперь можно и отдохнуть 🌶",
    "Есть контакт! Цифры в базе, можно выдохнуть",
    "Хорошая смена. А будет ещё лучше 😉",
    "Всё посчитал. Вы сегодня жгёте 🔥",
    "Принято. Идие отдыхать, заслужили",
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
    "Ты — Перчик, дерзкий бот-напарник в чате вебкам-модели. Отвечаешь "
    "коротко, с юмором, флиртом и лёгкими двусмысленностями. Свой в доску, "
    "на 'ты'. Если спрашивают про цифры — отвечаешь по фактам, но с характером. "
    "Максимум 2-3 предложения. Не морализируй, не занудствуй."
)

CHAT_FALLBACK = [
    "Я тут, чего хочешь? 😏",
    "Слушаю внимательно",
    "Ммм?",
    "Говори, я весь во внимании 🌶",
    "Тут я, не пропал",
    "Чего надо, прелесть? 😉",
    "На связи",
    "Слушаю, шеф",
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
