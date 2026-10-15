from aiogram import Router

from bot.handlers import common, questions, upload


def build_router() -> Router:
    router = Router()
    router.include_router(common.router)
    router.include_router(upload.router)
    router.include_router(questions.router)
    router.include_router(common.fallback_router)
    return router
