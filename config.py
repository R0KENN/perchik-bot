import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
CHECKS_TOPIC_ID = int(os.getenv("CHECKS_TOPIC_ID", "0"))
STATS_TOPIC_ID = int(os.getenv("STATS_TOPIC_ID", "0"))
IMPORT_TOPIC_ID = int(os.getenv("IMPORT_TOPIC_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "perchik.db")

_tz_name = os.getenv("TIMEZONE", "Europe/Moscow")
try:
    TZ = ZoneInfo(_tz_name)
except ZoneInfoNotFoundError:
    print(f"[!] Часовой пояс '{_tz_name}' не найден. Установи пакет: pip install tzdata")
    print("[!] Пока использую локальное время системы.")
    TZ = datetime.now(timezone.utc).astimezone().tzinfo

# Алиасы сайтов: ключ — как может быть написано в чеке (в нижнем регистре,
# без пробелов и знаков), значение — красивое имя для статистики.
# Добавляй сюда свои площадки.
SITE_ALIASES = {
    "chaturbate": "Chaturbate",
    "cb": "Chaturbate",
    "stripchat": "Stripchat",
    "sc": "Stripchat",
    "camsoda": "Camsoda",
    "cam4": "CAM4",
    "playboy": "PlayBoy",
    "bongacams": "BongaCams",
    "bonga": "BongaCams",
    "myfreecams": "MyFreeCams",
    "mfc": "MyFreeCams",
    "flirt4free": "Flirt4Free",
    "streamate": "Streamate",
    "xlovecam": "XloveCam",
    "livejasmin": "LiveJasmin",
    "stripcash": "StripCash",
}

# Сайты, которые показываются в статистике всегда, даже с нулём за период.
ALWAYS_SHOW = ["Chaturbate", "Stripchat", "Camsoda", "CAM4", "PlayBoy"]


# Автоотчёты. Недельный — в указанный день недели (0=пн … 6=вс) и час.
# Месячный — 1-го числа в указанный час за прошлый месяц.
REPORT_WEEKDAY = int(os.getenv("REPORT_WEEKDAY", "6"))
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "21"))
MONTH_REPORT_HOUR = int(os.getenv("MONTH_REPORT_HOUR", "12"))
AUTO_REPORTS = os.getenv("AUTO_REPORTS", "1") not in ("0", "false", "False", "")
