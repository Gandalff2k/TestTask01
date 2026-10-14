import asyncio
import hashlib
import html
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import aiohttp

from bot import parsing
from bot.mittens import describe_scope, doc_type_from_title, scope_from_intro, scope_from_title
from bot.storage import Storage

log = logging.getLogger(__name__)

LIST_URL = "https://drive.google.com/embeddedfolderview?id={folder_id}"
DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"
_PARALLEL_FILES = 8
_ocr_limit = asyncio.Semaphore(2)

_ENTRY = re.compile(
    r'<div class="flip-entry" id="entry-(?P<id>[^"]+)".*?'
    r'<div class="flip-entry-title">(?P<title>[^<]*)</div>.*?'
    r'<div class="flip-entry-last-modified"><div>(?P<modified>[^<]*)</div>',
    re.DOTALL,
)

ScopeClassifier = Callable[[str, str], Awaitable[frozenset[str] | None]]


@dataclass(frozen=True)
class DriveFile:
    id: str
    title: str
    modified: str


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"нових {len(self.added)}, оновлено {len(self.updated)}, прибрано {len(self.removed)}, "
            f"пропущено {len(self.skipped)}, помилок {len(self.failed)}"
        )


async def list_folder(session: aiohttp.ClientSession, folder_id: str) -> list[DriveFile]:
    async with session.get(LIST_URL.format(folder_id=folder_id)) as resp:
        resp.raise_for_status()
        page = await resp.text()
    return [
        DriveFile(id=m["id"], title=html.unescape(m["title"]).strip(), modified=m["modified"].strip())
        for m in _ENTRY.finditer(page)
    ]


async def download(session: aiohttp.ClientSession, file_id: str) -> bytes:
    async with session.get(DOWNLOAD_URL.format(file_id=file_id)) as resp:
        resp.raise_for_status()
        return await resp.read()


async def sync_folder(
    storage: Storage,
    folder_id: str,
    classify_scope: ScopeClassifier | None = None,
) -> SyncReport:
    report = SyncReport()
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        files = await list_folder(session, folder_id)
        if not files:
            log.warning("Тека %s порожня або недоступна, синхронізацію пропущено", folder_id)
            return report

        limit = asyncio.Semaphore(_PARALLEL_FILES)

        async def process(file: DriveFile) -> None:
            async with limit:
                try:
                    await _sync_file(session, storage, file, classify_scope, report)
                except Exception:
                    log.exception("Не вдалося обробити %s", file.title)
                    report.failed.append(file.title)

        supported = [f for f in files if parsing.is_supported(f.title)]
        report.skipped = [f.title for f in files if not parsing.is_supported(f.title)]
        await asyncio.gather(*(process(f) for f in supported))

    report.removed = [d.title for d in storage.deactivate_missing_drive({f.id for f in files})]
    log.info("Синхронізація «Лісового архіву»: %s", report)
    return report


async def _sync_file(
    session: aiohttp.ClientSession,
    storage: Storage,
    file: DriveFile,
    classify_scope: ScopeClassifier | None,
    report: SyncReport,
) -> None:
    existing = storage.by_drive_id(file.id)
    if existing and existing.drive_modified == file.modified:
        return

    data = await download(session, file.id)
    content_hash = hashlib.sha256(data).hexdigest()
    if existing and existing.content_hash == content_hash:
        storage.set_drive_modified(existing.id, file.modified)
        return

    async with _ocr_limit:
        text = await asyncio.to_thread(parsing.extract_text, file.title, data)

    scope = scope_from_title(file.title) or scope_from_intro(text)
    if scope is None and classify_scope is not None:
        scope = await classify_scope(file.title, text)
    if not scope:
        log.warning("Не вдалося визначити, для кого документ %s — пропускаю", file.title)
        report.failed.append(file.title)
        return

    doc = storage.add(
        title=file.title.rsplit(".", 1)[0],
        doc_type=doc_type_from_title(file.title),
        scope=scope,
        source="drive",
        filename=file.title,
        text=text,
        content_hash=content_hash,
        drive_id=file.id,
        drive_modified=file.modified,
    )
    (report.updated if existing else report.added).append(file.title)
    log.info("Архів: %s → %s", doc.title, describe_scope(doc.scope))


async def sync_forever(
    storage: Storage,
    folder_id: str,
    interval_minutes: int,
    classify_scope: ScopeClassifier | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await sync_folder(storage, folder_id, classify_scope)
        except Exception:
            log.exception("Синхронізація з Google Диском не вдалася, спробую пізніше")
