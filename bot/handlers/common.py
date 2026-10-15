import html
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.keyboards import DocsChoice, docs_keyboard, remove_keyboard
from bot.mittens import FOREST, MITTENS, mitten_by_name, scope_from_title
from bot.storage import Document, Storage

router = Router(name="common")
fallback_router = Router(name="fallback")

HELP_TEXT = (
    "Я допомагаю знайти поради звірів з усіх восьми рукавичок.\n\n"
    "<b>Спитати</b>: просто напиши питання й назви місце, наприклад "
    "«скільки внесок під дубом?».\n"
    "<b>Додати документ</b>: надішли файл PDF, Word або TXT — я спитаю, "
    "для якої він рукавички та хто автор.\n"
    "<b>/docs</b> — які документи є для рукавички.\n"
    "<b>/mydocs</b> — документи, які надіслав ти (там їх можна прибрати).\n"
    "<b>/cancel</b> — скасувати додавання документа.\n\n"
    "Рукавички: " + ", ".join(MITTENS) + "."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Привіт! 🐭\n\n" + HELP_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нема чого скасовувати ")
        return
    await state.clear()
    await message.answer("Скасувала. Документ не збережено.")


@router.message(Command("docs"))
async def cmd_docs(message: Message, command: CommandObject, storage_db: Storage, settings: Settings) -> None:
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Для якої рукавички показати документи?", reply_markup=docs_keyboard())
        return
    if arg.casefold() in (FOREST, "ліс", "всі", "усі"):
        await message.answer(_docs_text(None, storage_db, settings))
        return
    mitten = mitten_by_name(arg) or _single_mitten(arg)
    if mitten is None:
        await message.answer("Не знаю такої рукавички. Обери зі списку:", reply_markup=docs_keyboard())
        return
    await message.answer(_docs_text(mitten, storage_db, settings))


@router.message(Command("mydocs"))
async def cmd_mydocs(message: Message, storage_db: Storage, settings: Settings) -> None:
    docs = storage_db.uploaded_by(message.from_user.id)
    if not docs:
        await message.answer("Ти ще не надсилав мені документів, які зараз діють.")
        return
    await message.answer(
        "<b>Твої документи</b>\n" + _lines(docs, settings) + "\n\nЩоб прибрати документ, натисни кнопку:",
        reply_markup=remove_keyboard([(d.id, d.title) for d in docs]),
    )


@router.callback_query(DocsChoice.filter())
async def on_docs_choice(callback: CallbackQuery, callback_data: DocsChoice, storage_db: Storage,
                         settings: Settings) -> None:
    await callback.answer()
    mitten = MITTENS[callback_data.index] if 0 <= callback_data.index < len(MITTENS) else None
    await callback.message.answer(_docs_text(mitten, storage_db, settings))


@fallback_router.message(StateFilter(None))
async def on_other(message: Message) -> None:
    await message.answer("Я розумію текстові питання та файли PDF, Word або TXT ")


def _single_mitten(text: str) -> str | None:
    scope = scope_from_title(text)
    return next(iter(scope)) if scope and len(scope) == 1 else None


def _docs_text(mitten: str | None, storage: Storage, settings: Settings) -> str:
    if mitten is None:
        docs = storage.forest_wide()
        return "<b>Документи для всього лісу</b>\n" + _lines(docs, settings)
    docs = storage.active_for_mitten(mitten)
    own = [d for d in docs if d.scope == {mitten}]
    part = [d for d in docs if d.scope != {mitten} and not d.is_forest_wide]
    forest = [d for d in docs if d.is_forest_wide]
    sections = [f"<b>Документи для «{html.escape(mitten)}»</b>"]
    for title, items in (("Рукавички", own), ("Частини лісу", part), ("Усього лісу", forest)):
        if items:
            sections.append(f"\n<i>{title}:</i>\n" + _lines(items, settings))
    return "\n".join(sections)


def _lines(docs: list[Document], settings: Settings) -> str:
    if not docs:
        return "— поки нічого немає"
    tz = ZoneInfo(settings.timezone)
    lines = []
    for d in sorted(docs, key=lambda d: d.title):
        line = f"• {html.escape(d.title)}"
        if d.is_supplement:
            line += " (доповнення)"
        if d.source == "telegram":
            line += f" — {html.escape(d.author or 'автор невідомий')}, {d.added_at.astimezone(tz):%d.%m.%Y}"
        lines.append(line)
    return "\n".join(lines)
