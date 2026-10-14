from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.mittens import MITTENS

router = Router(name="common")

HELP_TEXT = (
    "Я допомагаю знайти поради звірів з усіх восьми рукавичок.\n\n"
    "<b>Спитати</b>: просто напиши питання й назви місце, наприклад "
    "«скільки внесок під дубом?».\n"
    "<b>Додати документ</b>: надішли файл PDF, Word або TXT — я спитаю, "
    "для якої він рукавички та хто автор.\n"
    "<b>/docs</b> — які документи є для рукавички.\n\n"
    "Рукавички: " + ", ".join(MITTENS) + "."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer("Привіт! 🐭\n\n" + HELP_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
