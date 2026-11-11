"""Long-running mode for an always-on machine: scheduled booking checks plus Telegram commands."""
from __future__ import annotations

from datetime import datetime
import time

from . import cli
from .botcommands import COMMANDS, Commands
from .config import DEFAULT_MINUTES, interval_minutes
from .store import Store
from .telegram import TelegramBot, TelegramError

POLL_SECONDS = 25
ERROR_PAUSE_SECONDS = 20


def log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def check_interval(store: Store) -> int:
    try:
        return interval_minutes(store)
    except Exception:
        return DEFAULT_MINUTES


def handle_update(update: dict, config: dict, commands: Commands, bot: TelegramBot) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    # Only the chat paired during 'ate telegram' may control bookings.
    if chat.get("id") != config["chat_id"] or chat.get("type") != "private":
        return
    text = message.get("text")
    if isinstance(text, str):
        bot.send(config["chat_id"], commands.handle(text))


def serve(store: Store, *, cycles: int | None = None, clock=time.monotonic, sleep=time.sleep,
          bot_factory=TelegramBot) -> None:
    """Run until stopped. 'cycles' limits loop passes for tests."""
    commands = Commands(store)
    next_check = clock()
    offset = None
    bot = None
    bot_token = None
    log("Ate is running: booking checks and Telegram commands.")
    try:
        while cycles is None or cycles > 0:
            if cycles is not None:
                cycles -= 1
            if clock() >= next_check:
                code = cli.main(["--state-dir", str(store.directory), "run"])
                log(f"Booking check finished with code {code}.")
                next_check = clock() + check_interval(store) * 60
            try:
                config = store.read("telegram")
            except Exception as exc:
                log(f"Could not read Telegram settings: {exc}")
                config = None
            if not config:
                sleep(min(30, max(1, next_check - clock())))
                continue
            try:
                if bot is None or bot_token != config["token"]:
                    if bot:
                        bot.close()
                    bot, bot_token = bot_factory(config["token"]), config["token"]
                    try:
                        bot.call("setMyCommands", {"commands": [{"command": n, "description": d} for n, d in COMMANDS]})
                    except TelegramError as exc:
                        log(f"Could not publish the command menu: {exc}")
                wait = int(min(POLL_SECONDS, max(1, next_check - clock())))
                for update in bot.updates(offset, wait=wait):
                    offset = int(update["update_id"]) + 1
                    handle_update(update, config, commands, bot)
            except TelegramError as exc:
                log(f"Telegram problem: {exc}")
                sleep(ERROR_PAUSE_SECONDS)
            except Exception as exc:
                log(f"Unexpected error: {type(exc).__name__}")
                sleep(ERROR_PAUSE_SECONDS)
    finally:
        if bot:
            bot.close()
