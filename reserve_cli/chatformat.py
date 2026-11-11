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


def day_heading(iso: str) -> str:
    return "📅 " + date.fromisoformat(iso).strftime("%a %d %b")


def meals_block(entries: dict[str, list[str]]) -> str:
    """Render {'2026-11-12': ['breakfast', 'dinner']} as one line per day."""
    return "\n".join(f"{day_heading(day)}   " + "  ".join(meal_label(m) for m in meals)
                     for day, meals in entries.items())


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
        parts.append(meals_block(dict(sorted(grouped.items()))))
    parts.extend(unparsed)
    return "\n\n".join(parts)


def problem_alert(detail: str) -> str:
    return f"⚠️ Booking problem\n{detail.rstrip('.')}.\n🔁 Ate will keep retrying."


def suspended_alert(notice: str) -> str:
    return f"🛑 Booking suspended\n{notice}"


RECOVERED_ALERT = "✅ Booking is working again."
TEST_ALERT = "🔔 Test alert from Ate. Alerts are working."
CONNECTED_ALERT = ("👋 Ate is connected.\nYou will get a message here when meals are booked "
                   "or something needs attention.")
