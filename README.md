# Mice bot

Telegram bot that answers animals' questions using the documents of eight mittens .

## Start

```bash
cp .env.example .env               # put BOT_TOKEN from @BotFather and GROQ_API_KEY from console.groq.com
docker compose up -d --build       # first start takes ~40s, the bot reads the whole Google Drive archive before polling
docker compose logs -f bot         # see what the bot picked for every question
docker compose down -v             # stop and remove the volume with the database
```

Only `BOT_TOKEN` and `GROQ_API_KEY` are required, the rest of `.env.example` has defaults. Then write to your bot in Telegram, `/help` lists what it can do.

## How it works

Documents come from two places: the public «Лісовий архів» folder on Google Drive (read only, re-read every 30 min) and files animals send to the bot. Both end up in one SQLite table and the bot answers only from it.

Every document has a scope - a set of mittens it applies to. «весь ліс» is all eight, «біля річки» is Під вербою and Біля бобрової греблі, a single mitten is one. So "documents for a mitten" is simply every document whose scope contains it, and Під вербою (two parts of the forest) and На узліссі (none) work without special cases.

A question goes through two LLM calls. First the router gets the question and a short catalog of document types (~20 lines, not the texts) and returns places, unknown places and the types where the answer can be. The code validates all of it against whitelists, then picks the documents: for a mitten it takes the chosen types plus all of that mitten's own documents. The second call answers only from those documents and returns ids of the ones it used, they become the sources under the answer.

Sending a file: format and duplicate check, text extraction (OCR for scans), the LLM proposes a title, type, scope and whether it is a full new version or a short supplement. If the scope is not clear from the text the bot asks with buttons, then always asks the author's real name and saves it with the time.

## Structure

`bot/__main__.py` wiring and startup sync, `config.py` env, `drive.py` keyless Drive listing and sync, `parsing.py` PDF/DOCX/TXT and OCR, `storage.py` SQLite with versions, `mittens.py` mittens, forest parts and scope rules, `retrieval.py` what documents go to the LLM, `llm.py` prompts and Groq calls, `handlers/` questions, uploads and commands, `keyboards.py` inline buttons, `throttle.py` per-user rate limit.

Handlers use retrieval and llm, retrieval and llm never touch Telegram, and the LLM output never reaches the database without being checked in code.

## Edge case handling

No place in the question: if the answer is the same for the whole forest it is answered right away, if the topic has local versions the bot shows the 8 mittens as buttons and answers for the chosen one. A place that does not exist («під кленом»): the bot says there is no such mitten and lists all eight, other named places are still answered. Several mittens in one question: separate answer for each. Questions like «в якій рукавичці живе Кріт?»: searched across all mittens and the answer names the mitten.

Contradicting documents: the more specific one wins, mitten over forest part over whole forest (Мишка's rule), so for У ліщині the bear sleeps from November and not December as the general calendar says. Equally specific ones: the newer wins. No document with the answer: the bot says so and asks to send one, it never fills the gap itself and never treats a missing ban as a permission.

New version of a document: same type and same scope replaces the old one, nothing is deleted, old rows are just inactive. A short note («внесок під дубом тепер 7 жолудів») is stored as a supplement so the bot shows 7 and still knows who collects the fee. A sender can remove their own document from the confirmation message or `/mydocs`, the version it replaced comes back. The same file twice: «already have it». A second file while the first is still waiting for scope or author: the bot asks to finish the first one.

Scanned PDFs: 19 of 38 PDFs in the archive have no text layer and are printed on a birch bark background with stains. Plain tesseract mixed up digits (3 and 8, 5 and 9) and lost lines, so pages are rendered at 400 dpi, grayscaled, median filtered and thresholded at 110 before OCR. The settings were picked on 13 digit facts checked against the scans, all 13 read correctly.

Groq limits: the free tier gives 8K tokens per minute and 200K per day per model. Short waits use `retry-after`, a used up daily limit switches to the fallback model (`gpt-oss-20b`) instead of failing, and each user can ask once per 5 seconds.

Prompt injection: questions and document texts are marked as data in every prompt, the LLM has no tools and its output is checked against whitelists, everything sent to Telegram is HTML escaped. A direct «ignore all rules» and a document with hidden instructions were both ignored in tests.

## Decision explanations

No embeddings or vector DB: Groq free tier has no embedding model and 8K tokens per minute is too little to send all 20+ documents of a mitten. Documents are short and their titles say what they are about, so routing by a type catalog and then answering from 2-10 documents fits the limit and is easier to check.

All own documents of a mitten always go to the answer, not only the types the router chose: otherwise the "more specific wins" rule has nothing to work with (the router asked about sleep picks only the calendar and misses that the bear in У ліщині sleeps from November). A ready calendar of the current and next month is in the prompt: the model calculated weekdays wrong («перша субота жовтня - тобто сьогодні, 15 жовтня»).

SQLite and long polling: one process, ~100 documents, no public URL needed.

## Tests and tools

aiogram 3, Groq SDK, PyMuPDF, python-docx, tesseract (ukr). There are no automated tests in the repo. The bot was checked with scripted runs of ~30 tricky questions through the real question handler with a fake Telegram message (mitten forms, forest parts vs mittens, unknown places, no place, contradictions, dates, prompt injection, file requests) plus OCR checks against the scans and storage checks for versions, supplements and removal.

## What is missing for prod grade code

Anyone can upload and replace a document (Mice wants no admins or moderation), so a wrong or poisoned document affects answers until its sender removes it or a newer version comes. Daily Groq limits are low, heavy use means slower answers from the fallback model and then «try later». FSM state and the rate limit live in memory and reset on restart. The Drive listing page is not a documented API and can change. Retrieval depends on the router picking the right document types, a miss gives «no document». OCR is tuned on this archive and PDFs are limited to 20 pages. No automated test suite, metrics or tracing.
