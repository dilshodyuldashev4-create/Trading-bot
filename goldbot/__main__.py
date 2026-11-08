"""Запуск: python -m goldbot"""
import asyncio
import logging

from .config import config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.bot_token:
        raise SystemExit("BOT_TOKEN не задан: скопируйте .env.example в .env и заполните")
    from .bot import App
    asyncio.run(App().run())


if __name__ == "__main__":
    main()
