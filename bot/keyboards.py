from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.mittens import FOREST, GROUPS, MITTENS

SCOPE_OPTIONS: tuple[str, ...] = (FOREST, *GROUPS, *MITTENS)


class MittenChoice(CallbackData, prefix="ask"):
    index: int


class ScopeToggle(CallbackData, prefix="scope"):
    index: int


class ScopeDone(CallbackData, prefix="scope_done"):
    pass


class DocsChoice(CallbackData, prefix="docs"):
    index: int


class RemoveDoc(CallbackData, prefix="rm"):
    doc_id: int


def remove_keyboard(docs: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for doc_id, title in docs:
        builder.button(text=f"🗑 Прибрати «{title[:40]}»", callback_data=RemoveDoc(doc_id=doc_id))
    builder.adjust(1)
    return builder.as_markup()


def mittens_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, mitten in enumerate(MITTENS):
        builder.button(text=mitten, callback_data=MittenChoice(index=i))
    builder.adjust(2)
    return builder.as_markup()


def scope_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, option in enumerate(SCOPE_OPTIONS):
        mark = "✅ " if option in selected else ""
        builder.button(text=f"{mark}{option}", callback_data=ScopeToggle(index=i))
    builder.button(text="Готово", callback_data=ScopeDone())
    builder.adjust(1, 3, 2, 2, 2, 2, 1)
    return builder.as_markup()


def docs_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=FOREST, callback_data=DocsChoice(index=-1))
    for i, mitten in enumerate(MITTENS):
        builder.button(text=mitten, callback_data=DocsChoice(index=i))
    builder.adjust(1, 2)
    return builder.as_markup()
