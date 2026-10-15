import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message, TelegramObject

TOO_FAST = "Не так швидко  Зачекай, будь ласка, кілька секунд і спробуй ще раз."


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, seconds: float):
        self._seconds = seconds
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not get_flag(data, "throttle") or event.from_user is None:
            return await handler(event, data)
        now = time.monotonic()
        user_id = event.from_user.id
        if now - self._last.get(user_id, 0.0) < self._seconds:
            if isinstance(event, CallbackQuery):
                await event.answer(TOO_FAST, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(TOO_FAST)
            return None
        self._last[user_id] = now
        return await handler(event, data)
