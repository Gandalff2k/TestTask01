from aiogram import Router

from bot.handlers import common, questions


def build_router() -> Router:
    router = Router()
    router.include_router(common.router)
    router.include_router(questions.router)
    return router
