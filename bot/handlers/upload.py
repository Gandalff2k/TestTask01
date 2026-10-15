import asyncio
import hashlib
import html
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import groq
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Document, Message
from aiogram.utils.chat_action import ChatActionSender

from bot import parsing
from bot.config import Settings
from bot.keyboards import SCOPE_OPTIONS, RemoveDoc, ScopeDone, ScopeToggle, remove_keyboard, scope_keyboard
from bot.llm import LLM
from bot.mittens import describe_scope, scope_from_labels
from bot.retrieval import catalog
from bot.storage import Storage

log = logging.getLogger(__name__)
router = Router(name="upload")

_MAX_FILE_BYTES = 20 * 1024 * 1024
_MAX_AUTHOR_LEN = 100


class Upload(StatesGroup):
    choosing_scope = State()
    waiting_author = State()


@router.message(F.document, flags={"throttle": True})
async def on_document(message: Message, state: FSMContext, storage_db: Storage, llm: LLM) -> None:
    if await state.get_state() in (Upload.choosing_scope.state, Upload.waiting_author.state):
        pending = (await state.get_data()).get("title", "попередній документ")
        await message.answer(
            f"Спершу закінчимо з «{html.escape(pending)}» — дай відповідь вище або напиши /cancel. "
            "Цей файл надішли, будь ласка, ще раз після цього."
        )
        return
    await state.clear()
    document = message.document
    filename = document.file_name or "документ"
    if not parsing.is_supported(filename):
        await message.answer("Я вмію читати лише файли PDF, Word (.docx) або TXT. Надішли, будь ласка, в одному з цих форматів.")
        return
    if document.file_size and document.file_size > _MAX_FILE_BYTES:
        await message.answer("Файл завеликий — Telegram дає ботам завантажувати лише до 20 МБ.")
        return

    async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
        await _receive(message, state, storage_db, llm, document, filename)


async def _receive(message: Message, state: FSMContext, storage_db: Storage, llm: LLM, document: Document, filename: str) -> None:
    data = (await message.bot.download(document)).read()
    content_hash = hashlib.sha256(data).hexdigest()
    duplicate = storage_db.active_by_hash(content_hash)
    if duplicate:
        await message.answer(f"Такий документ у мене вже є: «{html.escape(duplicate.title)}». Дякую!")
        return

    try:
        text = await asyncio.to_thread(parsing.extract_text, filename, data)
    except parsing.TooManyPagesError:
        await message.answer(f"Документ задовгий — я читаю PDF до {parsing.MAX_PDF_PAGES} сторінок. Розділи його, будь ласка, на частини.")
        return
    except parsing.EmptyDocumentError:
        await message.answer("Не змогла прочитати в цьому файлі жодного тексту. Можливо, він порожній або пошкоджений.")
        return
    except Exception:
        log.exception("Не вдалося прочитати %s", filename)
        await message.answer("Не змогла прочитати цей файл. Спробуй, будь ласка, інший формат.")
        return

    try:
        result = await llm.classify(filename, text, catalog(storage_db.active()))
    except groq.RateLimitError:
        await message.answer("Ой, я зараз не встигаю  Надішли, будь ласка, файл ще раз за хвилинку.")
        return

    await state.update_data(
        filename=filename, file_id=document.file_id, text=text, content_hash=content_hash,
        title=result.title, doc_type=result.doc_type, is_supplement=result.is_supplement,
        scope=sorted(result.scope), selected=[],
    )
    if result.scope:
        await _ask_author(message, state, f"Отримала «{html.escape(result.title)}» — це порада для: "
                                         f"{html.escape(describe_scope(result.scope))}.")
    else:
        await state.set_state(Upload.choosing_scope)
        await message.answer(
            f"Отримала «{html.escape(result.title)}». З тексту не зрозуміло, для кого ця порада. "
            "Обери, будь ласка, рукавички чи частину лісу й натисни «Готово».",
            reply_markup=scope_keyboard(set()),
        )


@router.callback_query(Upload.choosing_scope, ScopeToggle.filter())
async def on_scope_toggle(callback: CallbackQuery, callback_data: ScopeToggle, state: FSMContext) -> None:
    if not 0 <= callback_data.index < len(SCOPE_OPTIONS):
        await callback.answer()
        return
    selected = set((await state.get_data()).get("selected") or [])
    selected ^= {SCOPE_OPTIONS[callback_data.index]}
    await state.update_data(selected=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=scope_keyboard(selected))
    await callback.answer()


@router.callback_query(Upload.choosing_scope, ScopeDone.filter())
async def on_scope_done(callback: CallbackQuery, state: FSMContext) -> None:
    scope = scope_from_labels((await state.get_data()).get("selected") or [])
    if not scope:
        await callback.answer("Обери хоча б одну рукавичку чи частину лісу", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(scope=sorted(scope))
    await _ask_author(callback.message, state, f"Записала: порада для {html.escape(describe_scope(scope))}.")


@router.message(Upload.choosing_scope)
async def on_text_while_choosing(message: Message) -> None:
    await message.answer("Обери, будь ласка, кнопками вище, для кого порада, і натисни «Готово». Або /cancel, щоб скасувати.")


@router.message(Upload.waiting_author, F.text, ~F.text.startswith("/"))
async def on_author(message: Message, state: FSMContext, storage_db: Storage, settings: Settings) -> None:
    author = " ".join(message.text.split())
    if not author or len(author) > _MAX_AUTHOR_LEN:
        await message.answer("Напиши, будь ласка, справжнє ім'я автора — коротко, одним повідомленням.")
        return

    data = await state.get_data()
    await state.clear()
    scope = frozenset(data["scope"])
    previous = [] if data["is_supplement"] else storage_db.same_document(data["doc_type"], scope)
    doc = storage_db.add(
        title=data["title"], doc_type=data["doc_type"], scope=scope, source="telegram",
        filename=data["filename"], text=data["text"], content_hash=data["content_hash"],
        tg_file_id=data["file_id"], author=author, added_at=datetime.now(timezone.utc),
        is_supplement=data["is_supplement"], uploader_id=message.from_user.id,
    )
    sent = doc.added_at.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m.%Y о %H:%M")
    lines = [
        f"Дякую! Додала «{html.escape(doc.title)}» для: {html.escape(describe_scope(doc.scope))}.",
        f"Автор: {html.escape(author)}, надіслано {sent}.",
    ]
    if previous:
        lines.append("Це новіша версія, тож вона замінила: " + ", ".join(f"«{html.escape(p.title)}»" for p in previous) + ".")
    elif doc.is_supplement:
        lines.append("Це доповнення: попередній документ лишається, а там, де вони розходяться, діятиме новіша інформація.")
    lines.append("Якщо надіслав помилково — натисни кнопку нижче або знайди документ у /mydocs.")
    await message.answer("\n".join(lines), reply_markup=remove_keyboard([(doc.id, doc.title)]))


@router.callback_query(RemoveDoc.filter())
async def on_remove(callback: CallbackQuery, callback_data: RemoveDoc, storage_db: Storage) -> None:
    try:
        doc = storage_db.get(callback_data.doc_id)
    except KeyError:
        doc = None
    if doc is None or doc.uploader_id != callback.from_user.id:
        await callback.answer("Прибрати можна лише документ, який надіслав ти сам.", show_alert=True)
        return
    if not doc.active:
        await callback.answer("Цей документ уже не діє.", show_alert=True)
        return
    restored = storage_db.remove(doc.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    text = f"Прибрала «{html.escape(doc.title)}»."
    if restored:
        text += " Знову діє попередня версія: " + ", ".join(f"«{html.escape(d.title)}»" for d in restored) + "."
    await callback.message.answer(text)


@router.message(Upload.waiting_author)
async def on_non_text_author(message: Message) -> None:
    await message.answer("Напиши, будь ласка, ім'я автора текстом. Або /cancel, щоб скасувати.")


async def _ask_author(message: Message, state: FSMContext, prefix: str) -> None:
    await state.set_state(Upload.waiting_author)
    await message.answer(f"{prefix}\n\nХто автор цього документа? Напиши, будь ласка, справжнє ім'я.")
