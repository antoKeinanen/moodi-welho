"""Entry point: `uv run velho`."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from dotenv import load_dotenv

from .db import Database
from .handlers import router

COMMANDS = [
    ("start", "Päävalikko"),
    ("new", "Aloita uusi sauva"),
    ("my", "Omat sauvat ja tilastot"),
    ("gallery", "Selaa valmiita sauvoja"),
    ("stats", "Tilastot"),
    ("join", "Liity ryhmän tilastoihin"),
    ("leave", "Poistu ryhmän tilastoista"),
    ("help", "Ohje"),
]


async def run() -> None:
    load_dotenv()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        sys.exit("BOT_TOKEN puuttuu – kopioi .env.example tiedostoksi .env ja täytä se.")
    db = Database(os.environ.get("DB_PATH", "velho.db"))
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp["db"] = db
    dp.include_router(router)
    await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
    await dp.start_polling(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
