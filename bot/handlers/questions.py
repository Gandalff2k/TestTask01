import html
import logging
from zoneinfo import ZoneInfo

import groq
from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot import drive
from bot.config import Settings
from bot.keyboards import MittenChoice, mittens_keyboard
from bot.llm import LLM
from bot.mittens import MITTENS
from bot.retrieval import (
    EVERYWHERE_TARGET, FOREST_TARGET, Target, catalog, group_target, has_local_versions, mitten_target, select,
)
from bot.storage import Document, Storage

log = logging.getLogger(__name__)
router = Router(name="questions")

OFF_TOPIC = (
    "Я допомагаю лише з порадами звірів нашого лісу 🐭 "
    "Спитай, наприклад, «скільки внесок під дубом?» або «які небезпеки біля річки?»."
)
BUSY = "Ой, забагато питань одразу — я не встигаю 🐭 Спробуй, будь ласка, за хвилинку."
FAILED = "Щось пішло не так, і я не змогла знайти відповідь. Спробуй, будь ласка, ще раз."
LOADING = "Я ще розбираю «Лісовий архів». Спробуй за хвилинку."
ASK_MITTEN = "Відповідь залежить від рукавички. Про яку питаєш?"
_MAX_EVERYWHERE_DOCS = 12


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_question(message: Message, state: FSMContext, storage_db: Storage, llm: LLM, settings: Settings) -> None:
    question = message.text.strip()
    docs = storage_db.active()
    if not docs:
        await message.answer(LOADING)
        return
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        await _handle(message, state, question, docs, llm, settings)
    except groq.RateLimitError:
        await message.answer(BUSY)
    except Exception:
        log.exception("Не вдалося відповісти на %r", question)
        await message.answer(FAILED)


@router.callback_query(MittenChoice.filter())
async def on_mitten_chosen(
    callback: CallbackQuery, callback_data: MittenChoice, state: FSMContext,
    storage_db: Storage, llm: LLM, settings: Settings,
) -> None:
    data = await state.get_data()
    question = data.get("pending_question")
    await callback.answer()
    if not question or not 0 <= callback_data.index < len(MITTENS):
        await callback.message.answer("Нагадай, будь ласка, питання — я його вже забула.")
        return
    mitten = MITTENS[callback_data.index]
    await callback.message.bot.send_chat_action(callback.message.chat.id, ChatAction.TYPING)
    try:
        text = await _answer_for(question, mitten_target(mitten), data.get("pending_types") or [],
                                 storage_db.active(), llm, settings, with_header=True)
        await callback.message.answer(text)
    except groq.RateLimitError:
        await callback.message.answer(BUSY)
    except Exception:
        log.exception("Не вдалося відповісти на %r для %s", question, mitten)
        await callback.message.answer(FAILED)


async def _handle(message: Message, state: FSMContext, question: str, docs: list[Document],
                  llm: LLM, settings: Settings) -> None:
    route = await llm.route(question, catalog(docs))
    targets = [mitten_target(m) for m in route.mittens] + [group_target(g) for g in route.groups]

    if route.off_topic and not targets and not route.unknown_places:
        await message.answer(OFF_TOPIC)
        return

    if route.unknown_places:
        names = ", ".join(f"«{html.escape(p)}»" for p in route.unknown_places)
        await message.answer(
            f"Рукавички {names} у нашому лісі немає. Ось усі вісім:\n" + "\n".join(f"• {m}" for m in MITTENS)
        )
        if not targets:
            return

    if route.wants_file:
        await _send_files(message, targets or [FOREST_TARGET], route.doc_types, docs)
        return

    if targets:
        for target in targets:
            await message.answer(await _answer_for(question, target, route.doc_types, docs, llm, settings,
                                                   with_header=len(targets) > 1))
        return

    if route.all_mittens:
        await message.answer(await _answer_for(question, EVERYWHERE_TARGET, route.doc_types, docs, llm, settings,
                                               with_header=False))
        return

    forest_docs = select(FOREST_TARGET, route.doc_types, docs)
    needs_mitten = has_local_versions(route.doc_types, docs)
    if forest_docs:
        answer = await llm.answer(question, FOREST_TARGET.label, forest_docs)
        if answer.found:
            await message.answer(_format(answer.text, answer.used_doc_ids, docs, settings))
        elif not needs_mitten:
            await message.answer(_not_found(FOREST_TARGET))
    elif not needs_mitten:
        await message.answer(_not_found(FOREST_TARGET))
    if needs_mitten:
        await state.update_data(pending_question=question, pending_types=route.doc_types)
        await message.answer(ASK_MITTEN, reply_markup=mittens_keyboard())


async def _answer_for(question: str, target: Target, doc_types: list[str], docs: list[Document],
                      llm: LLM, settings: Settings, with_header: bool) -> str:
    header = f"<b>{html.escape(target.label)}</b>\n" if with_header else ""
    selected = select(target, doc_types, docs)
    if target.everywhere:
        selected = selected[:_MAX_EVERYWHERE_DOCS]
    if not selected:
        return header + _not_found(target)
    answer = await llm.answer(question, target.label, selected, everywhere=target.everywhere)
    if not answer.found:
        return header + _not_found(target)
    return header + _format(answer.text, answer.used_doc_ids, docs, settings)


def _not_found(target: Target) -> str:
    where = "" if target.is_forest or target.everywhere else f" для «{html.escape(target.label)}»"
    return (
        f"У мене немає документа{where}, де була б відповідь на це питання. "
        "Якщо такий документ у когось є — надішли його мені, і я його додам 🐭"
    )


def _format(text: str, used_ids: list[int], docs: list[Document], settings: Settings) -> str:
    by_id = {d.id: d for d in docs}
    sources = [_source_line(by_id[i], settings) for i in used_ids if i in by_id]
    result = html.escape(text)
    if sources:
        result += "\n\n" + "\n".join(f"📄 {s}" for s in sources)
    return result


def _source_line(doc: Document, settings: Settings) -> str:
    title = html.escape(doc.title)
    if doc.source != "telegram":
        return title
    sent = doc.added_at.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m.%Y о %H:%M")
    return f"{title} — автор: {html.escape(doc.author or 'невідомо')}, надіслано {sent}"


async def _send_files(message: Message, targets: list[Target], doc_types: list[str], docs: list[Document]) -> None:
    chosen = list({d.id: d for t in targets for d in select(t, doc_types, docs)}.values())
    if not chosen:
        await message.answer("Не знайшла такого документа. Подивись список командою /docs.")
        return
    for doc in chosen:
        if doc.tg_file_id:
            await message.answer_document(doc.tg_file_id, caption=html.escape(doc.title))
        elif doc.drive_id:
            data = await drive.fetch(doc.drive_id)
            await message.answer_document(BufferedInputFile(data, filename=doc.filename), caption=html.escape(doc.title))
