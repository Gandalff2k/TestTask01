import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bot.mittens import ALL_MITTENS

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    doc_type       TEXT NOT NULL,
    scope          TEXT NOT NULL,          -- JSON-список рукавичок
    source         TEXT NOT NULL CHECK (source IN ('drive', 'telegram')),
    filename       TEXT NOT NULL,
    text           TEXT NOT NULL,
    drive_id       TEXT,
    drive_modified TEXT,
    content_hash   TEXT NOT NULL,          -- sha256 вмісту файлу
    tg_file_id     TEXT,
    author         TEXT,
    added_at       TEXT NOT NULL,          -- ISO-8601, UTC
    active         INTEGER NOT NULL DEFAULT 1,
    is_supplement  INTEGER NOT NULL DEFAULT 0,
    uploader_id    INTEGER,
    removed        INTEGER NOT NULL DEFAULT 0,
    replaced_by    INTEGER REFERENCES documents(id)
);
CREATE INDEX IF NOT EXISTS idx_documents_active ON documents(active);
CREATE INDEX IF NOT EXISTS idx_documents_drive_id ON documents(drive_id);
"""

_MIGRATIONS = {
    "is_supplement": "INTEGER NOT NULL DEFAULT 0",
    "uploader_id": "INTEGER",
    "removed": "INTEGER NOT NULL DEFAULT 0",
}


@dataclass(frozen=True)
class Document:
    id: int
    title: str
    doc_type: str
    scope: frozenset[str]
    source: str
    filename: str
    text: str
    drive_id: str | None
    drive_modified: str | None
    content_hash: str
    tg_file_id: str | None
    author: str | None
    added_at: datetime
    active: bool
    is_supplement: bool
    uploader_id: int | None
    removed: bool
    replaced_by: int | None

    @property
    def is_forest_wide(self) -> bool:
        return self.scope == ALL_MITTENS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_doc(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        title=row["title"],
        doc_type=row["doc_type"],
        scope=frozenset(json.loads(row["scope"])),
        source=row["source"],
        filename=row["filename"],
        text=row["text"],
        drive_id=row["drive_id"],
        drive_modified=row["drive_modified"],
        content_hash=row["content_hash"],
        tg_file_id=row["tg_file_id"],
        author=row["author"],
        added_at=datetime.fromisoformat(row["added_at"]),
        active=bool(row["active"]),
        is_supplement=bool(row["is_supplement"]),
        uploader_id=row["uploader_id"],
        removed=bool(row["removed"]),
        replaced_by=row["replaced_by"],
    )


class Storage:
    def __init__(self, path: Path | str):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(documents)")}
        for column, ddl in _MIGRATIONS.items():
            if column not in columns:
                self._conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        self._conn.close()

    def add(
        self,
        *,
        title: str,
        doc_type: str,
        scope: frozenset[str],
        source: str,
        filename: str,
        text: str,
        content_hash: str,
        drive_id: str | None = None,
        drive_modified: str | None = None,
        tg_file_id: str | None = None,
        author: str | None = None,
        added_at: datetime | None = None,
        is_supplement: bool = False,
        uploader_id: int | None = None,
    ) -> Document:
        added_at = added_at or _now()
        scope_json = json.dumps(sorted(scope), ensure_ascii=False)
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO documents (title, doc_type, scope, source, filename, text,
                       drive_id, drive_modified, content_hash, tg_file_id, author, added_at, is_supplement, uploader_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, doc_type, scope_json, source, filename, text,
                 drive_id, drive_modified, content_hash, tg_file_id, author, added_at.isoformat(), int(is_supplement), uploader_id),
            )
            new_id = cur.lastrowid
            if not is_supplement:
                self._conn.execute(
                    """UPDATE documents SET active = 0, replaced_by = ?
                       WHERE active = 1 AND id != ? AND doc_type = ? AND scope = ?""",
                    (new_id, new_id, doc_type, scope_json),
                )
        return self.get(new_id)

    def get(self, doc_id: int) -> Document:
        row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(doc_id)
        return _row_to_doc(row)

    def active(self) -> list[Document]:
        rows = self._conn.execute("SELECT * FROM documents WHERE active = 1 ORDER BY id")
        return [_row_to_doc(r) for r in rows]

    def active_for_mitten(self, mitten: str) -> list[Document]:
        return [d for d in self.active() if mitten in d.scope]

    def forest_wide(self) -> list[Document]:
        return [d for d in self.active() if d.is_forest_wide]

    def by_drive_id(self, drive_id: str) -> Document | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE drive_id = ? ORDER BY id DESC LIMIT 1", (drive_id,)
        ).fetchone()
        return _row_to_doc(row) if row else None

    def doc_types(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT doc_type FROM documents ORDER BY doc_type")
        return [r["doc_type"] for r in rows]

    def set_drive_modified(self, doc_id: int, drive_modified: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE documents SET drive_modified = ? WHERE id = ?", (drive_modified, doc_id))

    def deactivate_missing_drive(self, present_ids: set[str]) -> list[Document]:
        gone = [d for d in self.active() if d.source == "drive" and d.drive_id not in present_ids]
        with self._conn:
            for doc in gone:
                self._conn.execute("UPDATE documents SET active = 0 WHERE id = ?", (doc.id,))
        return gone

    def same_document(self, doc_type: str, scope: frozenset[str]) -> list[Document]:
        return [d for d in self.active() if d.doc_type == doc_type and d.scope == scope]

    def active_by_hash(self, content_hash: str) -> Document | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE active = 1 AND content_hash = ? LIMIT 1", (content_hash,)
        ).fetchone()
        return _row_to_doc(row) if row else None

    def uploaded_by(self, uploader_id: int) -> list[Document]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE active = 1 AND source = 'telegram' AND uploader_id = ? ORDER BY id",
            (uploader_id,),
        )
        return [_row_to_doc(r) for r in rows]

    def remove(self, doc_id: int) -> list[Document]:
        with self._conn:
            self._conn.execute("UPDATE documents SET active = 0, removed = 1 WHERE id = ?", (doc_id,))
            restored = self._conn.execute(
                "SELECT id FROM documents WHERE replaced_by = ? AND removed = 0", (doc_id,)
            ).fetchall()
            self._conn.execute(
                "UPDATE documents SET active = 1, replaced_by = NULL WHERE replaced_by = ? AND removed = 0", (doc_id,)
            )
        return [self.get(r["id"]) for r in restored]
