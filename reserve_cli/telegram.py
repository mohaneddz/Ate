"""Private booking alerts through a Telegram bot.

The bot token is a credential, so it only goes to api.telegram.org over HTTPS
and never appears in error text. Requests are never retried automatically.
"""
from pathlib import Path
import re
import time

import requests

ORIGIN = "https://api.telegram.org"
TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
TOKEN_KEYS = {"http", "token", "bottoken", "apitoken", "httpapi", "httpapitoken"}
MESSAGE_LIMIT = 4000


class TelegramError(Exception):
    pass


def load_bot_token(path: Path) -> str:
    """Read the token from a dotenv-style file; other keys such as a t.me link are ignored."""
    try:
        if path.stat().st_size > 65536:
            raise TelegramError("The bot file is too large; use a small file.")
        content = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise TelegramError("The bot file was not found.") from exc
    except (OSError, UnicodeError) as exc:
        raise TelegramError("Could not read the bot file as UTF-8 text.") from exc
    found = []
    for line in content.splitlines():
        line = line.strip().removeprefix("export ")
        if not line or line.startswith(("#", ";")):
            continue
        if TOKEN_PATTERN.match(line):
            found.append(line)
            continue
        separators = [line.index(mark) for mark in ("=", ":") if mark in line]
        if not separators:
            continue
        index = min(separators)
        key = "".join(ch for ch in line[:index].lower() if ch.isalnum())
        if key in TOKEN_KEYS:
            found.append(line[index + 1:].strip().strip("\"'`"))
    if len(set(found)) != 1:
        raise TelegramError("The bot file needs exactly one 'http=' token line.")
    return check_token(found[0])


def check_token(token: str) -> str:
    token = token.strip()
    if not TOKEN_PATTERN.match(token):
        raise TelegramError("That does not look like a bot token. It should look like 123456789:AA... from BotFather.")
    return token


class TelegramBot:
    def __init__(self, token: str):
        self.token = check_token(token)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "AteCLI/0.5"

    def close(self):
        self.session.close()

    def call(self, method: str, payload: dict | None = None, wait: int = 0):
        if not re.fullmatch(r"[A-Za-z]+", method):
            raise TelegramError("Unsupported Telegram method.")
        try:
            response = self.session.post(f"{ORIGIN}/bot{self.token}/{method}", json=payload or {},
                                         timeout=(10, wait + 15), allow_redirects=False)
        except requests.RequestException:
            raise TelegramError("Could not reach Telegram; no automatic retry was made.") from None
        if response.status_code == 401:
            raise TelegramError("Telegram rejected the bot token.")
        if response.status_code == 409:
            raise TelegramError("Telegram refused because this bot has a webhook or another listener.")
        try:
            body = response.json()
        except ValueError:
            body = None
        if not 200 <= response.status_code < 300 or not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramError(f"Telegram refused the request (HTTP {response.status_code}).")
        return body.get("result")

    def me(self) -> dict:
        result = self.call("getMe")
        if not isinstance(result, dict) or not result.get("username"):
            raise TelegramError("Telegram did not describe this bot.")
        return result

    def updates(self, offset: int | None = None, wait: int = 0) -> list:
        payload = {"timeout": wait, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self.call("getUpdates", payload, wait)
        return result if isinstance(result, list) else []

    def send(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat_id, "text": text[:MESSAGE_LIMIT],
                                  "disable_web_page_preview": True})


def find_private_chat(bot: TelegramBot, seconds: int = 120, clock=time.monotonic) -> dict | None:
    """Wait for someone to message the bot privately; return their chat id and first name."""
    deadline = clock() + seconds
    offset = None
    while True:
        remaining = int(deadline - clock())
        if remaining <= 0:
            return None
        for update in bot.updates(offset, wait=min(20, remaining)):
            offset = int(update["update_id"]) + 1
            message = update.get("message") or {}
            sender = message.get("from") or {}
            chat = message.get("chat") or {}
            if chat.get("type") == "private" and not sender.get("is_bot") and isinstance(chat.get("id"), int):
                bot.updates(offset)  # Mark the update as handled so it is not replayed.
                return {"chat_id": chat["id"], "name": sender.get("first_name") or "Telegram user"}


class Notifier:
    """Sends alerts to the chat saved by 'ate telegram'. Alerts never change a booking's outcome."""

    def __init__(self, store):
        self.store = store

    def deliver(self, messages: list[str], log=lambda text: None) -> None:
        if not messages:
            return
        try:
            config = self.store.read("telegram")
            if not config:
                return
            bot = TelegramBot(config["token"])
        except Exception:
            log("Telegram alerts could not be started; check 'ate telegram'.")
            return
        try:
            for text in messages:
                bot.send(config["chat_id"], text)
        except Exception as exc:
            log(f"Telegram alert was not delivered: {exc}")
        finally:
            bot.close()
