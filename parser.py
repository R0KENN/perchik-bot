import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from config import SITE_ALIASES

MONEY_RE = re.compile(r"\$\s*(\d[\d\s]*(?:[.,]\d+)?)|(\d[\d\s]*(?:[.,]\d+)?)\s*(?:\$|usd|долл)", re.I)
TOKENS_RE = re.compile(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(?:tk\b|tkn|tokens?|ток)", re.I)
FOLLOWS_RE = re.compile(r"(?:follows?|followers?|fans?|подписч\w*|подписки|subs?)\s*[:\-]?\s*(\d+)", re.I)
LIKES_RE = re.compile(r"(?:likes?|лайк\w*)\s*[:\-]?\s*(\d+)", re.I)
SCORE_RE = re.compile(r"(?:stripscore|score|скор\w*)\s*[:\-]?\s*(\d+)", re.I)
TOTAL_RE = re.compile(r"^\s*(?:total|итого|тотал|всего|итог)\b", re.I)
DATE_RE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?")
TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})")

STOPWORDS = {
    "смена", "shift", "total", "итого", "всего", "тотал", "tokens", "tips",
    "follows", "likes", "score", "stripscore", "чек", "отчет", "отчёт",
}


def _norm(text: str) -> str:
    """Оставляем только буквы и цифры в нижнем регистре."""
    return re.sub(r"[^a-zа-я0-9]", "", text.lower())


def _num(raw: str) -> float:
    return float(raw.replace(" ", "").replace(",", "."))


def find_money(line: str) -> float | None:
    m = MONEY_RE.search(line)
    if not m:
        return None
    return _num(m.group(1) or m.group(2))


def detect_site(line: str) -> str | None:
    norm = _norm(line)
    if not norm or norm in STOPWORDS:
        return None
    if norm in SITE_ALIASES:
        return SITE_ALIASES[norm]
    # строка вида "CAM4 $10.40" / "Chaturbate:" — начинается с известного сайта
    for alias in sorted(SITE_ALIASES, key=len, reverse=True):
        if len(alias) >= 5 and norm.startswith(alias):
            return SITE_ALIASES[alias]
    # эвристика: короткая строка-заголовок без цифр, двоеточий и денег
    clean = line.strip(" -•—▪️*_")
    if (
        len(clean) <= 24
        and clean
        and ":" not in clean
        and "$" not in clean
        and not any(ch.isdigit() for ch in clean)
        and _norm(clean) not in STOPWORDS
    ):
        return clean
    return None


@dataclass
class SiteEntry:
    site: str
    tokens: float = 0.0
    usd: float = 0.0
    follows: int = 0
    likes: int = 0
    score: int = 0

    def is_empty(self) -> bool:
        return not (self.tokens or self.usd or self.follows or self.likes or self.score)


@dataclass
class ParsedShift:
    shift_date: date
    time_start: str | None = None
    time_end: str | None = None
    hours: float | None = None
    total_usd: float = 0.0
    entries: list[SiteEntry] = field(default_factory=list)
    raw_text: str = ""

    @property
    def follows(self) -> int:
        return sum(e.follows for e in self.entries)

    @property
    def tokens(self) -> float:
        return sum(e.tokens for e in self.entries)


def _parse_header(lines: list[str], fallback: date):
    """Возвращает (дата, начало, конец, часы, индекс_строки_заголовка)."""
    shift_date, t_start, t_end, hours, header_idx = fallback, None, None, None, -1

    for i, line in enumerate(lines[:3]):
        d = DATE_RE.search(line)
        t = TIME_RE.search(line)
        if not d and not t:
            continue
        header_idx = i
        if d:
            day, month, year = int(d.group(1)), int(d.group(2)), d.group(3)
            if year:
                year = int(year)
                if year < 100:
                    year += 2000
            else:
                year = fallback.year
            try:
                shift_date = date(year, month, day)
                if shift_date > fallback + timedelta(days=1):
                    shift_date = date(year - 1, month, day)
            except ValueError:
                shift_date = fallback
        if t:
            h1, m1, h2, m2 = (int(x) for x in t.groups())
            t_start, t_end = f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}"
            delta = (h2 * 60 + m2) - (h1 * 60 + m1)
            if delta <= 0:
                delta += 24 * 60
            hours = round(delta / 60, 2)
        break

    return shift_date, t_start, t_end, hours, header_idx


def parse_check(text: str, fallback_date: date) -> ParsedShift | None:
    if not text:
        return None

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None

    shift_date, t_start, t_end, hours, header_idx = _parse_header(lines, fallback_date)

    entries: dict[str, SiteEntry] = {}
    current: str | None = None
    total: float | None = None

    for i, line in enumerate(lines):
        if i == header_idx:
            continue

        if TOTAL_RE.match(line):
            money = find_money(line)
            if money is not None:
                total = money
            continue

        site = detect_site(line)
        if site:
            current = site
            entries.setdefault(site, SiteEntry(site))

        if current is None:
            continue

        e = entries[current]
        money = find_money(line)
        if money is not None:
            e.usd += money
        tk = TOKENS_RE.search(line)
        if tk:
            e.tokens += _num(tk.group(1))
        f = FOLLOWS_RE.search(line)
        if f:
            e.follows += int(f.group(1))
        lk = LIKES_RE.search(line)
        if lk:
            e.likes += int(lk.group(1))
        sc = SCORE_RE.search(line)
        if sc:
            e.score = max(e.score, int(sc.group(1)))

    real = [e for e in entries.values() if not e.is_empty()]
    if total is None:
        total = round(sum(e.usd for e in real), 2)
    if not real and not total:
        return None

    return ParsedShift(
        shift_date=shift_date,
        time_start=t_start,
        time_end=t_end,
        hours=hours,
        total_usd=round(total, 2),
        entries=real,
        raw_text=text,
    )
