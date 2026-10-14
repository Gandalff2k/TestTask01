from aiogram import Router

from bot.handlers import common


def build_router() -> Router:
    router = Router()
    router.include_router(common.router)
    return router
