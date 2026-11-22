"""SQLite connection management and schema migrations.

Schema strategy: an ordered list of migrations; `schema_version` stores the
number applied. New migrations are appended, never edited, so existing
databases upgrade in place without data loss.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from config.settings import get_settings

MIGRATIONS: list[str] = [
    # 1 - initial schema
    """
    CREATE TABLE projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        subject TEXT,
        academic_level TEXT,
        options_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE documents (
        document_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        file_type TEXT NOT NULL,
        storage_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        processing_status TEXT NOT NULL DEFAULT 'uploaded',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(project_id, sha256)
    );
    CREATE TABLE chunks (
        chunk_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        content TEXT NOT NULL,
        content_type TEXT NOT NULL,
        page_number INTEGER,
        slide_number INTEGER,
        heading TEXT,
        section_id TEXT,
        source_reference TEXT NOT NULL,
        extraction_confidence REAL NOT NULL DEFAULT 1.0,
        needs_review INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_chunks_project ON chunks(project_id, seq);
    CREATE TABLE analyses (
        project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
        analysis_json TEXT,
        strategy_json TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE topics (
        topic_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        parent_topic_id TEXT REFERENCES topics(topic_id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        learning_objectives_json TEXT NOT NULL DEFAULT '[]',
        prerequisites_json TEXT NOT NULL DEFAULT '[]',
        source_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
        order_index INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_topics_project ON topics(project_id, order_index);
    CREATE TABLE resources (
        resource_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        topic_id TEXT REFERENCES topics(topic_id) ON DELETE CASCADE,
        resource_type TEXT NOT NULL,
        version INTEGER NOT NULL,
        is_current INTEGER NOT NULL DEFAULT 1,
        content_json TEXT NOT NULL,
        prompt_id TEXT,
        prompt_version TEXT,
        provider TEXT,
        model TEXT,
        origin TEXT NOT NULL DEFAULT 'generated',
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_resources_lookup ON resources(project_id, topic_id, resource_type, is_current);
    CREATE TABLE generation_tasks (
        task_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        topic_id TEXT REFERENCES topics(topic_id) ON DELETE CASCADE,
        resource_type TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id, topic_id, resource_type)
    );
    CREATE TABLE evaluations (
        evaluation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        topic_id TEXT REFERENCES topics(topic_id) ON DELETE CASCADE,
        resource_id TEXT REFERENCES resources(resource_id) ON DELETE CASCADE,
        coverage_score REAL,
        report_json TEXT NOT NULL,
        evaluation_status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE stage_runs (
        run_id TEXT PRIMARY KEY,
        project_id TEXT,
        stage_id TEXT NOT NULL,
        prompt_version TEXT,
        provider TEXT,
        model TEXT,
        attempts INTEGER NOT NULL,
        success INTEGER NOT NULL,
        duration_s REAL,
        prompt_tokens INTEGER,
        output_tokens INTEGER,
        error TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE activity (
        activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn = None
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = self._open()
            return self._memory_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
        return conn

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def migrate(self) -> int:
        conn = self.connect()
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for index in range(current, len(MIGRATIONS)):
            conn.executescript("BEGIN;" + MIGRATIONS[index] + f"; UPDATE schema_version SET version = {index + 1}; COMMIT;")
        conn.commit()
        return len(MIGRATIONS)


_db: Database | None = None
_lock = threading.Lock()


def get_database() -> Database:
    global _db
    with _lock:
        if _db is None:
            _db = Database(get_settings().db_path)
        return _db
