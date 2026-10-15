import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from groq import AsyncGroq, RateLimitError

from bot.mittens import GROUPS, MITTENS, describe_scope, mitten_by_name
from bot.storage import Document

log = logging.getLogger(__name__)

_RATE_LIMIT_ATTEMPTS = 4
_MAX_RATE_LIMIT_WAIT = 20.0

_SEASONS = {12: "зима", 1: "зима", 2: "зима", 3: "весна", 4: "весна", 5: "весна",
            6: "літо", 7: "літо", 8: "літо", 9: "осінь", 10: "осінь", 11: "осінь"}
_MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
           "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")

ROUTE_PROMPT = """Ти — диспетчер бота-довідника для звірів лісу. Ліс складається з восьми рукавичок (кожна — окреме ОСМД):
{mittens}

Рукавички належать до частин лісу:
{groups}

Каталог типів документів (тип: для кого є такі документи):
{catalog}

Розбери питання звіра й поверни JSON:
{{
  "off_topic": true/false,
  "mittens": [...],
  "groups": [...],
  "unknown_places": [...],
  "all_mittens": true/false,
  "doc_types": [...],
  "wants_file": true/false
}}

Поля:
- off_topic — питання не стосується лісу, рукавичок чи порад (привітання, балачки).
- mittens — рукавички, про які питають, ТОЧНО як у списку.
- groups — частини лісу ("хвойний ліс", "листяний ліс", "біля річки"), лише якщо питають про частину лісу загалом, а не про рукавичку.
- unknown_places — названі місця, яких немає ні серед рукавичок, ні серед частин лісу (напр. "під кленом").
- all_mittens — true ЛИШЕ коли питання саме шукає рукавичку чи порівнює рукавички: «в якій рукавичці живе Кріт?», «де найменший внесок?», «у кого голова ОСМД — Сова?». Якщо питання просто без місця («скільки внесок?», «хто чергує?», «коли збори?») — false: бот перепитає рукавичку.
- doc_types — УСІ типи з каталогу, де може бути відповідь навіть частково (до 5), ТОЧНО як у каталозі. Напр. про їжу чи гриби — і «грибний путівник», і «що їсти», і «чим поживитись поруч із рукавичкою», і «їстівне й отруйне»; про мешканців і хто чим займається — «статут осмд» і «чергування в рукавичці».
- wants_file — звір просить надіслати сам документ/файл.

Як впізнавати місця:
- Рукавичку впізнавай у будь-якій формі: «під дубом», «біля дуба» → «Під дубом»; «в ліщині», «у ліщині», «ліщина» → «У ліщині»; «біля сосон», «в соснах» → «У соснах»; «біля греблі», «на греблі», «у бобрів» → «Біля бобрової греблі»; «під вербою», «біля верби» → «Під вербою»; «біля мурашника» → «Біля мурашника»; «на узліссі» → «На узліссі»; «під ялиною» → «Під ялиною».
- Частина лісу — це множина чи місцевість загалом: «під ялинами», «серед сосен», «в хвойному лісі» → "хвойний ліс"; «в листяному лісі», «під дубами» → "листяний ліс"; «біля річки», «на річці» → "біля річки".
- Якщо місце не назване — mittens, groups і unknown_places порожні."""

ANSWER_PROMPT = """Ти — бот-довідник, який відповідає звірям лісу лише за порадами з їхніх документів.
Сьогодні {today}, пора року — {season}.
Питання стосується: {target}.

Правила:
- Відповідай ТІЛЬКИ на основі наведених документів. Нічого не вигадуй і не додавай знань ззовні.
- {scope_rule}
- Збери відповідь з усіх доречних документів, а не з одного.
- Якщо у документах немає відповіді на питання — постав "found": false.
- Якщо документи суперечать один одному, вір конкретнішому: для рукавички > для частини лісу > для всього лісу. Загальну пораду можна згадати додатково («а загалом у лісі…»).
- Якщо суперечать однаково конкретні документи — вір новішому (дата «додано»).
- Частину документів розпізнано зі сканів, тож у тексті можуть бути дрібні помилки й сміттєві символи — ігноруй їх.
- Якщо питають про «зараз», «сьогодні», «цього тижня» — зістав сьогоднішню дату з документами. Якщо з документа не можна точно сказати, як саме сьогодні, наведи загальне правило й чесно скажи, що точно не знаєш.
- Пиши українською, коротко й дружньо, звертайся на «ти». Без markdown.

Поверни JSON:
{{
  "found": true/false,
  "answer": "текст відповіді (порожній, якщо found = false)",
  "used_doc_ids": [id документів, з яких узято відповідь]
}}"""

_EVERYWHERE_TARGET = "будь-яка з восьми рукавичок — шукай відповідь у документах усіх рукавичок"
_EVERYWHERE_RULE = "Документи з різних рукавичок: у відповіді завжди називай рукавичку, до якої належить кожен факт."
_SINGLE_RULE = (
    "Відповідай лише про «{target}». Якщо в питанні згадано інші місця — взагалі їх не згадуй, навіть щоб сказати, "
    "що про них нічого немає: на них відповідають окремим повідомленням. Документи вже відібрані саме для цього місця."
)
_WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя")


@dataclass
class Route:
    off_topic: bool = False
    mittens: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    unknown_places: list[str] = field(default_factory=list)
    all_mittens: bool = False
    doc_types: list[str] = field(default_factory=list)
    wants_file: bool = False


@dataclass
class Answer:
    found: bool
    text: str
    used_doc_ids: list[int]


class LLM:
    def __init__(self, api_key: str, model: str, timezone: str):
        self._client = AsyncGroq(api_key=api_key, max_retries=1)
        self._model = model
        self._tz = ZoneInfo(timezone)

    async def _complete(self, **kwargs):
        for attempt in range(_RATE_LIMIT_ATTEMPTS):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except RateLimitError as exc:
                if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                    raise
                delay = _retry_after(exc)
                log.info("Groq rate limit, чекаю %.1f с", delay)
                await asyncio.sleep(delay)

    async def _json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        extra = {"reasoning_effort": "low"} if "gpt-oss" in self._model else {}
        resp = await self._complete(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
            **extra,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            log.warning("LLM уперлася в ліміт токенів (%s)", max_tokens)
        content = choice.message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            log.warning("LLM повернула не JSON: %r", content[:500])
            return {}

    async def route(self, question: str, catalog: dict[str, str]) -> Route:
        system = ROUTE_PROMPT.format(
            mittens="\n".join(f"- {m}" for m in MITTENS),
            groups="\n".join(f"- {g}: {', '.join(m for m in MITTENS if m in ms)}" for g, ms in GROUPS.items())
            + "\n- На узліссі: не належить до жодної частини лісу",
            catalog="\n".join(f"- {t}: {d}" for t, d in catalog.items()),
        )
        data = await self._json(system, question, max_tokens=1500)
        route = Route(
            off_topic=bool(data.get("off_topic")),
            mittens=_unique(m for m in (mitten_by_name(x) for x in data.get("mittens") or []) if m),
            groups=_unique(g for g in (str(x).strip().casefold() for x in data.get("groups") or []) if g in GROUPS),
            unknown_places=_unique(str(x).strip() for x in data.get("unknown_places") or [] if str(x).strip()),
            all_mittens=bool(data.get("all_mittens")),
            doc_types=_unique(t for t in (str(x).strip() for x in data.get("doc_types") or []) if t in catalog),
            wants_file=bool(data.get("wants_file")),
        )
        log.info("route %r → %s", question, route)
        return route

    async def answer(self, question: str, target: str, docs: list[Document], everywhere: bool = False) -> Answer:
        now = datetime.now(self._tz)
        system = ANSWER_PROMPT.format(
            today=f"{_WEEKDAYS[now.weekday()]}, {now.day} {_MONTHS[now.month - 1]} {now.year}",
            season=_SEASONS[now.month],
            target=_EVERYWHERE_TARGET if everywhere else target,
            scope_rule=_EVERYWHERE_RULE if everywhere else _SINGLE_RULE.format(target=target),
        )
        documents = "\n\n".join(
            f"### Документ id={d.id}: {d.title}\n"
            f"(для: {describe_scope(d.scope)}; додано: {d.added_at.astimezone(self._tz):%d.%m.%Y %H:%M})\n{d.text}"
            for d in docs
        )
        data = await self._json(system, f"Документи:\n\n{documents}\n\nПитання: {question}", max_tokens=3000)
        ids = {d.id for d in docs}
        answer = Answer(
            found=bool(data.get("found")) and bool(str(data.get("answer") or "").strip()),
            text=str(data.get("answer") or "").strip(),
            used_doc_ids=[i for i in data.get("used_doc_ids") or [] if isinstance(i, int) and i in ids],
        )
        if answer.found and not answer.used_doc_ids:
            answer.used_doc_ids = [d.id for d in docs]
        return answer


def _retry_after(exc: RateLimitError) -> float:
    try:
        seconds = float(exc.response.headers.get("retry-after", ""))
    except (TypeError, ValueError):
        seconds = 5.0
    return min(max(seconds, 1.0), _MAX_RATE_LIMIT_WAIT)


def _unique(items) -> list:
    return list(dict.fromkeys(items))
