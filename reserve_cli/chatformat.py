"""Emoji and layout for Telegram messages. Terminal output and the log stay plain text."""
from __future__ import annotations

from datetime import date
import re

MEAL_ICONS = {"breakfast": "🍳", "lunch": "🍽️", "dinner": "🌙"}
COMMAND_ICONS = {
    "status": "📊", "today": "📆", "plan": "🗓️", "sync": "🔄", "log": "📜", "date": "📅", "days": "🔢",
    "until": "⏳", "pause": "⏸️", "resume": "▶️", "interval": "⏱️", "config": "⚙️", "depots": "🏠",
    "doctor": "🩺", "help": "❓",
}
CONFIRMED = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\w+) \(#(\d+)\)$")


def meal_label(name: str) -> str:
    return f"{MEAL_ICONS.get(name, '•')} {name}"


def meal_icons(meals: list[str]) -> str:
    return "".join(icon for name, icon in MEAL_ICONS.items() if name in meals)


def date_span(first: date, last: date) -> str:
    if first == last:
        return first.strftime("%a %d %b")
    if first.month == last.month:
        return f"{first:%d}–{last:%d %b}"
    return f"{first:%d %b}–{last:%d %b}"


def meals_block(entries: dict[str, list[str]]) -> str:
    """Render {'2026-11-12': ['breakfast', 'dinner']} with one line per run of days that share the same meals."""
    runs: list[list] = []
    for iso in sorted(entries):
        day, icons = date.fromisoformat(iso), meal_icons(entries[iso])
        if runs and runs[-1][2] == icons and (day - runs[-1][1]).days == 1:
            runs[-1][1] = day
        else:
            runs.append([day, day, icons])
    return "\n".join(f"📅 {date_span(first, last)}  {icons}" for first, last, icons in runs)


def short_order(order: dict | None) -> str:
    if not order:
        return "no order"
    if order.get("paused"):
        return "⏸️ paused"
    if order.get("kind") == "days":
        return f"{order['days']}d rolling"
    return "until " + date.fromisoformat(order["until"]).strftime("%d %b")


def booked_alert(confirmed: list[str]) -> str:
    """confirmed holds lines like '2026-11-12 breakfast (#123)'."""
    grouped: dict[str, list[str]] = {}
    unparsed = []
    for line in confirmed:
        match = CONFIRMED.match(line)
        if match:
            grouped.setdefault(match[1], []).append(match[2])
        else:
            unparsed.append(line)
    count = sum(len(meals) for meals in grouped.values()) + len(unparsed)
    parts = [f"✅ Booked {count} meal{'s' if count != 1 else ''}"]
    if grouped:
        parts.append(meals_block(grouped))
    parts.extend(unparsed)
    return "\n".join(parts)


def problem_alert(detail: str) -> str:
    return f"⚠️ Booking problem\n{detail.rstrip('.')}.\n🔁 Ate will keep retrying."


def suspended_alert(notice: str) -> str:
    return f"🛑 Booking suspended\n{notice}"


def updated_alert(old: str, new: str) -> str:
    return f"⬆️ Ate updated\n{old} → {new}"


RECOVERED_ALERT = "✅ Booking is working again."
TEST_ALERT = "🔔 Test alert from Ate. Alerts are working."
CONNECTED_ALERT = ("👋 Ate is connected.\nYou will get a message here when meals are booked "
                   "or something needs attention.")
