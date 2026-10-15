from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.mittens import MITTENS


class MittenChoice(CallbackData, prefix="ask"):
    index: int


def mittens_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, mitten in enumerate(MITTENS):
        builder.button(text=mitten, callback_data=MittenChoice(index=i))
    builder.adjust(2)
    return builder.as_markup()
