import io
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")  # без GUI, обязательно до pyplot
import matplotlib.pyplot as plt

ACCENT = "#ff6b57"
ACCENT2 = "#4dd4ac"
BG = "#17212b"


def _days(d_from: date, d_to: date) -> list[date]:
    out, cur = [], d_from
    while cur <= d_to:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _finish(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _style(ax, fig, title: str):
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_title(title, color="white", fontsize=13, pad=14)
    ax.tick_params(colors="#a8b8c8", labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color("#3a4a5a")
    ax.grid(axis="y", color="#2b3a4a", linewidth=0.8)
    ax.set_axisbelow(True)


def _xticks(ax, days: list[date]):
    step = max(1, len(days) // 15)
    idx = list(range(0, len(days), step))
    ax.set_xticks(idx)
    ax.set_xticklabels([days[i].strftime("%d.%m") for i in idx], rotation=45, ha="right")


def income_chart(series: dict, d_from: date, d_to: date, title: str) -> bytes:
    days = _days(d_from, d_to)
    values = [series.get(d.isoformat(), 0.0) for d in days]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    _style(ax, fig, f"Доход · {title} · итого {sum(values):.2f}$")
    ax.bar(range(len(days)), values, color=ACCENT, width=0.65)
    _xticks(ax, days)
    ax.set_ylabel("$", color="#a8b8c8")
    return _finish(fig)


def follows_chart(series: dict, d_from: date, d_to: date, title: str) -> bytes:
    days = _days(d_from, d_to)
    values = [series.get(d.isoformat(), 0) for d in days]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    _style(ax, fig, f"Прирост подписчиков · {title} · всего +{int(sum(values))}")
    ax.plot(range(len(days)), values, color=ACCENT2, marker="o", markersize=4, linewidth=2)
    ax.fill_between(range(len(days)), values, color=ACCENT2, alpha=0.15)
    _xticks(ax, days)
    return _finish(fig)


def sites_pie(rows, title: str) -> bytes:
    data = [(r["site"], r["usd"]) for r in rows if r["usd"] and r["usd"] > 0]
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    if not data:
        ax.text(0.5, 0.5, "Нет данных", color="white", ha="center")
        ax.axis("off")
        return _finish(fig)
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    colors = plt.cm.plasma([i / max(len(values), 1) for i in range(len(values))])
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct=lambda p: f"{p:.1f}%",
        colors=colors, startangle=90, wedgeprops={"edgecolor": BG, "linewidth": 2},
    )
    for t in texts:
        t.set_color("white")
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(9)
    ax.set_title(f"Доли сайтов · {title}", color="white", fontsize=13, pad=16)
    return _finish(fig)

def followers_total_chart(series: dict, title: str) -> bytes:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    _style(ax, fig, f"Всего подписчиков · {title}")
    if not series:
        ax.text(0.5, 0.5, "Нет данных", color="white", ha="center", transform=ax.transAxes)
        return _finish(fig)
    palette = plt.cm.plasma([i / max(len(series), 1) for i in range(len(series))])
    for color, (site, pts) in zip(palette, series.items()):
        ax.plot([p[0] for p in pts], [p[1] for p in pts],
                marker="o", markersize=3, linewidth=2, label=site, color=color)
    leg = ax.legend(facecolor=BG, edgecolor="#3a4a5a", labelcolor="white", fontsize=8)
    leg.get_frame().set_alpha(0.9)
    fig.autofmt_xdate(rotation=45)
    return _finish(fig)
