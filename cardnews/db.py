"""SQLite 연결. 웹 서버와 작업 프로세스는 이 DB로만 상태를 주고받아요."""

import sqlite3
from contextlib import closing, contextmanager

from cardnews import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    topic TEXT NOT NULL,
    stage TEXT NOT NULL,
    is_mock INTEGER NOT NULL,
    engine_name TEXT NOT NULL,
    engine_session_id TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    dispatch INTEGER NOT NULL DEFAULT 1,      -- 1이면 작업 프로세스가 가져갈 차례
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    progress TEXT NOT NULL DEFAULT '[]',
    question_id TEXT,
    error TEXT,
    worker_pid INTEGER,
    resumed_from TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_project ON runs(project_id, created_at);
CREATE TABLE IF NOT EXISTS idempotency (
    scope TEXT NOT NULL,
    request_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, request_id)
);
"""


def connect() -> sqlite3.Connection:
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def transaction():
    """쓰기 잠금을 먼저 잡는 트랜잭션. 읽고-확인하고-쓰기가 한 번에 일어나요."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
